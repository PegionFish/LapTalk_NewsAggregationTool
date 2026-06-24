"""
AI 预筛选 API — 保留的 pipeline 模块，仅保留标题批量筛选功能。
其他管线逻辑已迁移到:
  - pipeline_article.py (文章级)
  - pipeline_event.py   (事件级)
"""
import os, sqlite3, time, logging, threading
from datetime import datetime
from fastapi import APIRouter

from config import config
from utils.task_lock import task_lock
from utils.task_state import task_state
from utils.db import get_db_connection, safe_commit

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)


# ── 进度追踪（内存 + DB 双写）───────────────────────────────
def _log(state, msg: str, task_type: str = ''):
    ts = datetime.now().strftime('%H:%M:%S')
    state["log"].append(f"[{ts}] {msg}")
    if task_type:
        task_state.update(task_type, log_msg=msg)


def _sync_state(state: dict, task_type: str):
    """将内存状态同步到 DB。"""
    task_state.update(task_type,
        running=state.get('running', False),
        total=state.get('total', 0),
        done=state.get('done', 0),
        failed=state.get('failed', 0),
        current=state.get('current', ''),
    )


def _is_request_timeout_error(exc: Exception) -> bool:
    return "request timed out" in str(exc).lower()


def _queue_retry(state, item_id, retry_counts, reason: str = '', max_retries: int = 4, task_type: str = '') -> bool:
    """通用重试队列：超时、空返回、异常都回池子，最多重试 max_retries 次。"""
    count = retry_counts.get(item_id, 0) + 1
    retry_counts[item_id] = count
    if count <= max_retries:
        label = f"{reason}，" if reason else ""
        _log(state, f"#{item_id} {label}排入重试队列 ({count}/{max_retries + 1})", task_type)
        return True
    _log(state, f"#{item_id} 已达最大重试次数 ({count})，放弃", task_type)
    return False


def _queue_timeout_retry(state, item_id, retry_counts, max_retries=4, task_type=''):
    return _queue_retry(state, item_id, retry_counts, reason='Request Timed Out', max_retries=max_retries, task_type=task_type)


def _new_state() -> dict:
    """创建后台任务进度状态。"""
    return {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": [],
            "cancelled": False}


def _check_cancelled(state: dict) -> bool:
    """检查任务是否被取消，如已取消则更新状态。"""
    if state.get("cancelled"):
        state["running"] = False
        state["current"] = "已取消"
        return True
    return False


def _check_and_lock(task_type: str) -> tuple[bool, str]:
    """检查并获取任务锁。返回 (ok, message)。"""
    ok, reason = task_lock.acquire(task_type)
    if not ok:
        return False, f"无法启动: {reason}"
    return True, ''


def _unlock(task_type: str):
    """释放任务锁。"""
    task_lock.release(task_type)


def _force_reset(task_type: str, state: dict) -> dict:
    """强制重置卡住的任务状态 — 清除内存状态、锁、DB 持久化。"""
    was_running = state.get("running", False)
    state["running"] = False
    state["current"] = "已强制重置"
    state.setdefault("log", []).append(f"[{datetime.now().strftime('%H:%M:%S')}] 管理员强制重置")
    task_lock.release(task_type)
    task_state.clear(task_type)
    logger.warning(f"[ForceReset] Task '{task_type}' force-reset (was_running={was_running})")
    return {"ok": True, "message": f"任务 '{task_type}' 已强制重置", "was_running": was_running}


def _reset_state(state: dict, **extra) -> dict:
    """就地重置任务状态 dict，保持引用不丢失。"""
    state.clear()
    state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": [],
                  "cancelled": False})
    if extra:
        state.update(extra)
    return state


def _conn():
    """创建带超时配置的数据库连接，防止 WAL 并发写锁导致数据丢失。"""
    return get_db_connection(config.db_path)


# ── 模块级状态 ─────────────────────────────────────────────

_filter_state = _new_state()


# ═════════════════════════════════════════════════════════
# AI 预筛选 — 标题批量判断，筛掉不需要的文章
# ═════════════════════════════════════════════════════════

def _batch_ai_filter():
    """对未筛选的文章标题批量调用 AI，标记通过/拒绝。"""
    global _filter_state
    _reset_state(_filter_state)
    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title, source FROM news_articles
            WHERE content_status = 'pending'
              AND (ai_filtered = 0)
            ORDER BY fetched_at DESC
        """).fetchall()
        db.close()

        if not rows:
            _filter_state["running"] = False
            return

        _filter_state["total"] = len(rows)
        _log(_filter_state, f"待筛选 {len(rows)} 篇标题")

        from pipeline.ai_filter import filter_batch

        BATCH = 200
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            _filter_state["current"] = f"批次 {i // BATCH + 1} ({len(batch)} 篇)"
            batch_ids = filter_batch(batch)

            if batch_ids is None:
                # API 调用失败 — 保持 ai_filtered=0，等待下次重试
                _log(_filter_state, f"批次 {i // BATCH + 1} API 失败，跳过，保持待筛选状态")
                time.sleep(1.0)
                continue

            db2 = _conn()
            for aid, title, source in batch:
                if aid in batch_ids:
                    db2.execute("UPDATE news_articles SET ai_filtered=1 WHERE id=?", (aid,))
                    _filter_state["done"] += 1
                else:
                    db2.execute("UPDATE news_articles SET ai_filtered=-1 WHERE id=?", (aid,))
                    _filter_state["done"] += 1
                    _filter_state["failed"] += 1
            safe_commit(db2); db2.close()

            approved = _filter_state["done"] - _filter_state["failed"]
            rejected = _filter_state["failed"]
            _log(_filter_state, f"[{_filter_state['done']}/{len(rows)}] 通过={approved} 拒绝={rejected}")
            time.sleep(0.1)

    except Exception as e:
        logger.error(f"batch-ai-filter: {e}")
    finally:
        _filter_state["running"] = False
        _unlock('ai_filter')
        task_state.finish('ai_filter', success=True)


@router.post("/batch-ai-filter")
def start_batch_ai_filter():
    """启动 AI 预筛选 — 批量判断文章标题是否值得缓存。"""
    global _filter_state
    if _filter_state.get("running"):
        return {"ok": False, "message": "AI 筛选已在运行中"}
    ok, msg = _check_and_lock('ai_filter')
    if not ok:
        return {"ok": False, "message": msg}
    db = _conn()
    n = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status = 'pending'
          AND (ai_filtered = 0)
    """).fetchone()[0]
    db.close()
    task_state.init_state('ai_filter', total=n)
    _filter_state["running"] = True
    _filter_state["total"] = n
    _filter_state["current"] = "启动中..."
    _filter_state["running"] = True
    threading.Thread(target=_batch_ai_filter, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 预筛选，预计 {n} 篇", "pending": n}


@router.get("/batch-ai-filter/status")
def get_batch_ai_filter_status():
    """查询 AI 预筛选进度。"""
    return dict(_filter_state)
