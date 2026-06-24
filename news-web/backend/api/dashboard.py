"""仪表盘 SSE 端点 + 审计日志 — 替代所有独立轮询。"""
import asyncio, json, logging, os
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from config import config
from utils.db import get_db_connection

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)

_AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
_AUDIT_PATH = os.path.join(_AUDIT_DIR, 'dashboard_audit.log')


def _audit_log(event: str, data: dict):
    """写入审计日志（JSONL 格式）。"""
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        entry = {"ts": datetime.now().isoformat(timespec='seconds'), "event": event, "data": data}
        with open(_AUDIT_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.warning(f"审计日志写入失败: {e}")


def rotate_audit_log():
    """轮转审计日志：当前文件重命名为带日期后缀，保留 7 天。"""
    try:
        if not os.path.exists(_AUDIT_PATH):
            return
        today = datetime.now().strftime('%Y-%m-%d')
        rotated = f"{_AUDIT_PATH}.{today}"
        # Remove existing rotated file if present
        if os.path.exists(rotated):
            os.remove(rotated)
        os.rename(_AUDIT_PATH, rotated)
        # 清理超过 7 天的日志
        import glob, time
        cutoff = time.time() - 7 * 86400
        for old in glob.glob(f"{_AUDIT_PATH}.*"):
            if os.path.getmtime(old) < cutoff:
                os.remove(old)
    except Exception as e:
        logger.warning(f"审计日志轮转失败: {e}")


import queue as _queue_mod

class DashboardStream:
    """SSE 广播单例。使用线程安全队列，支持从子线程 publish。"""
    _queues: list[_queue_mod.Queue] = []

    @classmethod
    def publish(cls, event: str, data: dict):
        payload = (event, data)
        for q in cls._queues:
            try:
                q.put_nowait(payload)
            except _queue_mod.Full:
                pass
        _audit_log(event, data)

    @classmethod
    def subscribe(cls) -> _queue_mod.Queue:
        q = _queue_mod.Queue(maxsize=256)
        cls._queues.append(q)
        return q

    @classmethod
    def unsubscribe(cls, q: _queue_mod.Queue):
        try:
            cls._queues.remove(q)
        except ValueError:
            pass


def _get_stats_snapshot() -> dict:
    """获取当前统计快照。"""
    try:
        db = get_db_connection(config.db_path)
        articles = db.execute(
            "SELECT COUNT(*) FROM news_articles"
            " WHERE (ai_filtered IS NULL OR ai_filtered != -1)"
            " AND (content_status IS NULL OR content_status != 'dead')"
        ).fetchone()[0]
        events = db.execute("""
            SELECT COUNT(DISTINCT ae.event_id) FROM news_article_events ae
            JOIN news_articles a ON a.id = ae.article_id
            WHERE (a.ai_filtered IS NULL OR a.ai_filtered != -1)
            AND (a.content_status IS NULL OR a.content_status != 'dead')
        """).fetchone()[0]
        chains = db.execute("SELECT COUNT(*) FROM logic_chains").fetchone()[0]
        cached = db.execute(
            "SELECT COUNT(*) FROM news_articles"
            " WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'"
            " AND (ai_filtered IS NULL OR ai_filtered != -1)"
        ).fetchone()[0]
        pending = db.execute(
            "SELECT COUNT(*) FROM news_articles"
            " WHERE content_status='pending'"
            " AND (ai_filtered IS NULL OR ai_filtered != -1)"
        ).fetchone()[0]
        failed = db.execute(
            "SELECT COUNT(*) FROM news_articles"
            " WHERE local_path LIKE '[ERR:%'"
            " AND (ai_filtered IS NULL OR ai_filtered != -1)"
        ).fetchone()[0]
        db.close()
        return {"articles": articles, "events": events, "chains": chains,
                "cached": cached, "pending": pending, "failed": failed}
    except Exception:
        return {"articles": 0, "events": 0, "chains": 0, "cached": 0, "pending": 0, "failed": 0}


@router.get("/stream")
async def dashboard_stream(request: Request):
    """SSE 端点 — 推送仪表盘所有状态事件。"""
    async def event_generator():
        q = DashboardStream.subscribe()
        try:
            # 初始快照：stats + 当前管线状态
            stats = _get_stats_snapshot()
            yield f"event: stats\ndata: {json.dumps(stats, ensure_ascii=False)}\n\n"
            # 推送当前文章管线状态（懒导入避免循环引用）
            try:
                from api.pipeline_article import _article_state
                if _article_state.get("running"):
                    yield f"event: article_state\ndata: {json.dumps({'running': True, 'total': _article_state.get('total', 0), 'done': _article_state.get('done', 0), 'failed': _article_state.get('failed', 0), 'current': _article_state.get('current', '')}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
            # 推送当前事件管线状态（懒导入避免循环引用）
            try:
                from api.pipeline_event import _event_state
                if _event_state.get("running"):
                    yield f"event: event_state\ndata: {json.dumps({'running': True, 'steps': _event_state.get('steps', [])}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
            last_stats = datetime.now()
            loop = asyncio.get_event_loop()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(
                        loop.run_in_executor(None, q.get), timeout=5)
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    now = datetime.now()
                    if (now - last_stats).total_seconds() >= 10:
                        stats = _get_stats_snapshot()
                        yield f"event: stats\ndata: {json.dumps(stats, ensure_ascii=False)}\n\n"
                        last_stats = now
        finally:
            DashboardStream.unsubscribe(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
