"""
批量 AI 处理 API — 遍历数据库，对未处理文章执行翻译或分析。
后台异步执行，立即返回待处理数量。
"""
import os, sqlite3, time, logging, threading
from datetime import datetime
from fastapi import APIRouter

from config import config

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)

# ── 进度追踪（内存）───────────────────────────────────────
_translate_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": ""}
_analyze_state  = {"running": False, "total": 0, "done": 0, "failed": 0, "current": ""}


def _conn():
    return sqlite3.connect(config.db_path)


# ═════════════════════════════════════════════════════════
# 批量翻译
# ═════════════════════════════════════════════════════════

def _batch_translate():
    global _translate_state
    _translate_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": ""}

    try:
        cache_dir = config.content_cache_path
        if not os.path.isdir(cache_dir):
            _translate_state["running"] = False
            return

        # 找出有 HTML 缓存但未翻译的文章
        db = _conn()
        rows = db.execute("""
            SELECT id, title, local_path
            FROM articles
            WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'
              AND (translated_content IS NULL OR translated_content = '')
            ORDER BY id DESC
        """).fetchall()
        db.close()

        if not rows:
            _translate_state["running"] = False
            return

        _translate_state["total"] = len(rows)

        from translation_client import translate_html

        for idx, (aid, title, local_path) in enumerate(rows, 1):
            html_path = os.path.join(cache_dir, os.path.basename(local_path))
            if not os.path.isfile(html_path):
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            _translate_state["current"] = f"#{aid} {title[:50]}"

            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    html = f.read()
            except Exception:
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            if len(html) < 100:
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            # 语言检测：仅翻译英文文章
            from utils.text import detect_language
            lang = detect_language(html[:10000])

            if lang != 'en':
                db2 = _conn()
                db2.execute("UPDATE articles SET content_lang=? WHERE id=?", (lang, aid))
                db2.commit()
                db2.close()
                _translate_state["done"] += 1
                continue

            try:
                result = translate_html(html)
                if result and len(result) > 100:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE articles SET translated_content=?, content_status='translated', content_lang='en', translated_at=? WHERE id=?",
                        (result, datetime.now().isoformat(timespec='seconds'), aid)
                    )
                    db2.commit()
                    db2.close()
                else:
                    _translate_state["failed"] += 1
                    _translate_state["done"] += 1
                    continue
            except Exception as e:
                logger.warning(f"Translate failed for #{aid}: {e}")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            _translate_state["done"] += 1

            if idx < len(rows):
                time.sleep(5)  # 篇间延迟防超限

    except Exception as e:
        logger.error(f"Batch translate error: {e}")
    finally:
        _translate_state["running"] = False


# ═════════════════════════════════════════════════════════
# 批量分析
# ═════════════════════════════════════════════════════════

def _batch_analyze():
    global _analyze_state
    _analyze_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": ""}

    try:
        db = _conn()
        # 查找有文本内容但未 AI 分析的文章
        rows = db.execute("""
            SELECT id, title, text_content
            FROM articles
            WHERE text_content != ''
              AND (ai_analyzed IS NULL OR ai_analyzed = 0 OR ai_summary IS NULL OR ai_summary = '')
            ORDER BY id DESC
        """).fetchall()
        db.close()

        if not rows:
            _analyze_state["running"] = False
            return

        _analyze_state["total"] = len(rows)

        from ai_client import analyze_article as ai_analyze

        for idx, (aid, title, text) in enumerate(rows, 1):
            _analyze_state["current"] = f"#{aid} {title[:50]}"

            try:
                analysis = ai_analyze(title, text)
                if analysis:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE articles SET ai_summary=?, ai_analyzed=1 WHERE id=?",
                        (analysis, aid)
                    )
                    db2.commit()
                    db2.close()
                else:
                    _analyze_state["failed"] += 1
                    _analyze_state["done"] += 1
                    continue
            except Exception as e:
                logger.warning(f"Analyze failed for #{aid}: {e}")
                _analyze_state["failed"] += 1
                _analyze_state["done"] += 1
                continue

            _analyze_state["done"] += 1

            if idx < len(rows):
                time.sleep(1)  # 篇间短暂延迟

    except Exception as e:
        logger.error(f"Batch analyze error: {e}")
    finally:
        _analyze_state["running"] = False


# ═════════════════════════════════════════════════════════
# API 端点
# ═════════════════════════════════════════════════════════

@router.post("/batch-translate")
def start_batch_translate():
    """启动批量翻译 — 遍历所有有 HTML 缓存但未翻译的英文文章。"""
    global _translate_state
    if _translate_state.get("running"):
        return {"ok": False, "message": "翻译任务已在运行中", "state": _translate_state}

    # 预计算待处理数量
    db = _conn()
    pending = db.execute("""
        SELECT COUNT(*) FROM articles
        WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'
          AND (translated_content IS NULL OR translated_content = '')
    """).fetchone()[0]
    db.close()

    threading.Thread(target=_batch_translate, daemon=True).start()
    return {"ok": True, "message": f"启动批量翻译，预计 {pending} 篇", "pending": pending}


@router.get("/batch-translate/status")
def get_batch_translate_status():
    """查询批量翻译进度。"""
    return dict(_translate_state)


@router.post("/batch-analyze")
def start_batch_analyze():
    """启动批量分析 — 遍历所有有文本内容但未 AI 分析的文章。"""
    global _analyze_state
    if _analyze_state.get("running"):
        return {"ok": False, "message": "分析任务已在运行中", "state": _analyze_state}

    db = _conn()
    pending = db.execute("""
        SELECT COUNT(*) FROM articles
        WHERE text_content != ''
          AND (ai_analyzed IS NULL OR ai_analyzed = 0 OR ai_summary IS NULL OR ai_summary = '')
    """).fetchone()[0]
    db.close()

    threading.Thread(target=_batch_analyze, daemon=True).start()
    return {"ok": True, "message": f"启动批量分析，预计 {pending} 篇", "pending": pending}


@router.get("/batch-analyze/status")
def get_batch_analyze_status():
    """查询批量分析进度。"""
    return dict(_analyze_state)
