"""文章级管线 API — 缓存→清洗→翻译→分析+KCS"""
import threading, logging
from datetime import datetime
from fastapi import APIRouter

from config import config
from utils.task_lock import task_lock
from utils.task_state import task_state
from api.dashboard import DashboardStream

router = APIRouter(prefix="/api/pipeline/article", tags=["pipeline-article"])
logger = logging.getLogger(__name__)

_article_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}


def _reset_state():
    _article_state.clear()
    _article_state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []})


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
    global _article_state
    _reset_state()
    # 恢复上次异常中断的文章
    from pipeline.process_article import process_all_pending, recover_stuck_articles
    recover_stuck_articles()
    DashboardStream.publish("article_batch_start", {"total": _article_state.get("total", 0)})
    try:
        result = process_all_pending()
        _article_state["total"] = result["total"]
        _article_state["done"] = result["done"]
        _article_state["failed"] = result["failed"]
        _article_state["log"].extend(result["log"])
    except Exception as e:
        logger.error(f"article batch: {e}")
        _article_state["log"].append(f"❌ {e}")
    finally:
        DashboardStream.publish("article_batch_done", {"done": _article_state.get("done", 0), "failed": _article_state.get("failed", 0)})
        _article_state["running"] = False
        task_lock.release('article')
        task_state.finish('article', success=True)


@router.post("/{article_id}/process")
def start_article_process(article_id: int):
    """单篇完整处理"""
    from pipeline.process_article import process_article
    r = process_article(article_id)
    return r


@router.post("/batch-process")
def start_article_batch():
    global _article_state
    if _article_state.get("running"):
        return {"ok": False, "message": "文章处理已在运行中"}
    ok, msg = task_lock.acquire('article')
    if not ok:
        return {"ok": False, "message": msg}
    from utils.db import get_db_connection
    db = get_db_connection(config.db_path)
    n = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
          AND ai_filtered != -1
          AND (local_path != '' OR text_content != '')
          AND (ai_analyzed = 0 OR ai_cleaned_content IS NULL OR ai_cleaned_content = ''
               OR translated_content IS NULL OR translated_content = ''
               OR ai_keywords IS NULL OR ai_keywords = '')
    """).fetchone()[0]
    db.close()
    task_state.init_state('article', total=n)
    _article_state["running"] = True
    _article_state["total"] = n
    threading.Thread(target=_run_batch, daemon=True).start()
    return {"ok": True, "message": f"启动文章批量处理，预计 {n} 篇", "pending": n}


@router.get("/status")
def get_article_status():
    return dict(_article_state)
