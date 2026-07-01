"""文章级管线 API — 缓存→清洗→翻译→分析+KCS"""
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from fastapi import APIRouter

from config import config
from scheduler.task_scheduler import get_scheduler
from utils.task_state import task_state
from api.dashboard import DashboardStream

router = APIRouter(prefix="/api/pipeline/article", tags=["pipeline-article"])
logger = logging.getLogger(__name__)

_article_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
_task_id: str | None = None  # 当前批处理在 TaskScheduler 中的 task_id


def _reset_state():
    _article_state.clear()
    _article_state.update({"running": True, "total": 0, "done": 0, "failed": 0, "cancelled": False, "current": "", "log": []})


def _run_single(aid: int):
    global _article_state
    from pipeline.process_article import process_article
    _article_state["current"] = f"#{aid}"
    r = process_article(aid)
    if r["ok"]:
        _article_state["done"] += 1
        _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ✅ {r['steps']}")
        DashboardStream.publish("article_done", {"id": aid, "title": "", "ok": True, "steps": r["steps"]})
    else:
        _article_state["failed"] += 1
        _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ❌ {r.get('error', '')}")
        DashboardStream.publish("article_failed", {"id": aid, "title": "", "error": r.get("error", ""), "step": "unknown"})
    _article_state["current"] = ""


def _run_batch():
    """批处理全部待处理文章。50 线程并行，每步即时写 DB。"""
    global _article_state
    _reset_state()
    try:
        from pipeline.process_article import process_article, _conn, recover_stuck_articles

        # 恢复异常中断的文章
        recover_stuck_articles()

        # 查询待处理（标题通道：pending 无缓存也可处理，KCS+事件匹配基于标题）
        db = _conn()
        rows = db.execute("""
            SELECT id FROM news_articles
            WHERE content_status IN ('pending', 'fetched', 'translated')
              AND (ai_filtered IS NULL OR ai_filtered != -1)
              AND (ai_analyzed = 0 OR (ai_cleaned_content IS NULL OR ai_cleaned_content = '') AND ai_cleaned_content != '[EMPTY]'
                   OR (translated_content IS NULL OR translated_content = '') AND translated_content != '[EMPTY]'
                   OR ai_keywords IS NULL OR ai_keywords = ''
                   OR ai_category IS NULL OR ai_category = ''
                   OR ai_priority_score IS NULL OR ai_priority_score = 0.0)
            ORDER BY id DESC
        """).fetchall()
        db.close()

        total = len(rows)
        _article_state["total"] = total
        DashboardStream.publish("article_batch_start", {"total": total})

        if total == 0:
            return  # finally 会处理 publish + finish

        # process_article 每步即时写 DB，并行仅加速 AI 调用
        done = 0; failed = 0
        balance_paused = False
        MAX_WORKERS = config.ai_workers
        ARTICLE_TIMEOUT = 180  # 单篇文章最长处理时间（秒），超时跳过
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_aid = {executor.submit(process_article, aid): aid for (aid,) in rows}
            pending = set(future_to_aid)
            while pending:
                # 取消检查
                if _article_state.get("cancelled"):
                    for future in pending:
                        if future.cancel():  # 仅对未开始的 future 计为失败
                            aid = future_to_aid[future]
                            failed += 1
                            _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ⏹️ 用户取消")
                    _article_state["done"] = done
                    _article_state["failed"] = failed
                    _article_state["current"] = f"{done+failed}/{total}"
                    break

                done_now, pending = wait(pending, timeout=ARTICLE_TIMEOUT, return_when=FIRST_COMPLETED)
                if not done_now:
                    # 超时：所有剩余 future 都卡住了，标记为失败
                    for future in pending:
                        if future.cancel():  # 仅对未开始的 future 计为失败
                            aid = future_to_aid[future]
                            failed += 1
                            _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ❌ 超时({ARTICLE_TIMEOUT}s)")
                            DashboardStream.publish("article_failed", {"id": aid, "error": f"超时({ARTICLE_TIMEOUT}s)", "step": "timeout"})
                    _article_state["done"] = done
                    _article_state["failed"] = failed
                    _article_state["current"] = f"{done+failed}/{total}"
                    break
                for future in done_now:
                    aid = future_to_aid[future]
                    try:
                        r = future.result()
                        if r["ok"]:
                            done += 1
                            DashboardStream.publish("article_done", {"id": aid, "ok": True, "steps": r.get("steps", {})})
                        else:
                            failed += 1
                            err = r.get('error', '')[:100]
                            _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ❌ {err}")
                            DashboardStream.publish("article_failed", {"id": aid, "error": err, "step": "unknown"})
                    except Exception as e:
                        from ai_client import BalanceInsufficientError
                        if isinstance(e, BalanceInsufficientError):
                            _article_state["current"] = "余额不足，已暂停"
                            _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ⏸️ 余额不足，管线暂停")
                            DashboardStream.publish("article_paused", {"error": str(e)})
                            balance_paused = True
                            break
                        failed += 1
                        err = str(e)[:100]
                        _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ❌ {err}")
                        DashboardStream.publish("article_failed", {"id": aid, "error": err, "step": "thread"})
                    _article_state["done"] = done
                    _article_state["failed"] = failed
                    _article_state["current"] = f"{done+failed}/{total}"
                if balance_paused:
                    break

        _article_state["current"] = "完成"
    except Exception:
        logger.exception("_run_batch 未预期异常")
        _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ _run_batch 未预期异常")
    finally:
        DashboardStream.publish("article_batch_done", {
            "done": _article_state.get("done", 0),
            "failed": _article_state.get("failed", 0),
        })
        _article_state["running"] = False
        task_state.finish('article', success=True)


@router.post("/{article_id}/process")
def start_article_process(article_id: int):
    """单篇完整处理"""
    from pipeline.process_article import process_article
    r = process_article(article_id)
    return r


@router.post("/batch-process")
def start_article_batch():
    global _article_state, _task_id
    if _article_state.get("running"):
        return {"ok": False, "message": "文章处理已在运行中"}
    try:
        scheduler = get_scheduler()
    except RuntimeError:
        return {"ok": False, "message": "调度器尚未初始化，无法启动文章批量处理"}
    if "article_batch" in scheduler.status["active_types"]:
        return {"ok": False, "message": "文章处理已在运行中"}
    from utils.db import get_db_connection
    db = get_db_connection(config.db_path)
    # 标题通道：pending 文章也可直接处理
    n = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status IN ('pending', 'fetched', 'translated')
          AND ai_filtered != -1
          AND (ai_analyzed = 0 OR ai_cleaned_content IS NULL OR ai_cleaned_content = ''
               OR translated_content IS NULL OR translated_content = ''
               OR ai_keywords IS NULL OR ai_keywords = '')
    """).fetchone()[0]
    db.close()
    task_state.init_state('article', total=n)
    _article_state["running"] = True
    _article_state["total"] = n
    _task_id = scheduler.submit("article_batch", _run_batch)
    return {"ok": True, "message": f"启动文章批量处理，预计 {n} 篇", "pending": n}


@router.get("/status")
def get_article_status():
    return dict(_article_state)


@router.post("/cancel")
def cancel_article_batch():
    """取消文章批处理。正在处理的文章将继续完成，未开始的跳过。"""
    global _article_state, _task_id
    if not _article_state.get("running"):
        return {"ok": False, "message": "没有正在运行的文章处理"}
    _article_state["cancelled"] = True
    _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ⏹️ 用户取消")
    # 同时通过 TaskScheduler 取消队列中未开始的任务
    if _task_id:
        try:
            scheduler = get_scheduler()
            scheduler.cancel(_task_id)
        except Exception:
            pass
    _task_id = None
    return {"ok": True, "message": "取消信号已发送"}
