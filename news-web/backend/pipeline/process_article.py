#!/usr/bin/env python3
"""单篇文章处理编排器 —— 缓存→清洗→翻译→分析+KCS 线性执行。"""
import sys, os, sqlite3, time, logging, json as _json
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

from config import config
from ai_client import clean_article_content, analyze_article, extract_keywords_classify_score_ai
from translation_client import translate_html_preserve_structure, translate_html

logger = logging.getLogger(__name__)


def _conn():
    from utils.db import get_db_connection
    return get_db_connection(config.db_path)


def process_article(article_id: int) -> dict:
    """单篇文章完整处理：缓存(如未缓存)→清洗→翻译→分析+KCS。
    每步完成后立即写入 DB，失败不阻断后续步骤。
    返回 {"ok": bool, "steps": {...}, "error": str}
    """
    result = {"ok": True, "steps": {}, "error": ""}
    db = _conn()

    try:
        row = db.execute("""
            SELECT id, title, url, local_path, text_content, source, content_status, fetched_at
            FROM news_articles WHERE id=?
        """, (article_id,)).fetchone()
        if not row:
            return {"ok": False, "error": f"文章 #{article_id} 不存在"}

        aid, title, url, local_path, text_content, source, status, fetched_at = row

        # ── Step 1: 内容缓存 ──
        if not local_path or local_path.startswith('[ERR:'):
            from pipeline.fetch_content import fetch_article_content
            fetch_result = fetch_article_content(url, aid, config.content_cache_path)
            result["steps"]["cached"] = fetch_result.get("ok", False)
        else:
            result["steps"]["cached"] = True

        # 重新读取以确保拿到最新的 local_path
        row = db.execute("SELECT local_path, text_content FROM news_articles WHERE id=?", (aid,)).fetchone()
        local_path, text_content = row if row else ("", "")

        # 读取 HTML 内容
        html = ""
        if local_path and not local_path.startswith('[ERR:') and os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8', errors='replace') as f:
                html = f.read()
        elif text_content:
            html = text_content

        if not html or len(html.strip()) < 100:
            db.close()
            return {"ok": False, "error": f"#{aid} 无有效 HTML 内容", "steps": result["steps"]}

        # ── Step 2: 内容清洗 ──
        try:
            cleaned = clean_article_content(html)
            if cleaned and len(cleaned.strip()) > 50:
                db.execute("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (cleaned, aid))
                db.commit()
                result["steps"]["cleaned"] = f"{len(cleaned)} chars"
                from api.dashboard import DashboardStream
                DashboardStream.publish("article_progress", {"id": aid, "title": title, "step": "cleaning", "current": "清洗完成"})
            else:
                result["steps"]["cleaned"] = "empty"
        except Exception as e:
            result["steps"]["cleaned"] = f"error: {e}"
            logger.warning(f"#{aid} 清洗失败: {e}")

        # ── Step 3: 翻译 ──
        try:
            if config.translation_enabled and config.translation_api_key:
                translated = translate_html_preserve_structure(html)
            else:
                translated = translate_html(html)
            if translated:
                db.execute("UPDATE news_articles SET translated_content=? WHERE id=?", (translated, aid))
                db.commit()
                result["steps"]["translated"] = f"{len(translated)} chars"
            else:
                result["steps"]["translated"] = "empty"
        except Exception as e:
            result["steps"]["translated"] = f"error: {e}"
            logger.warning(f"#{aid} 翻译失败: {e}")

        # ── Step 4: 分析+KCS ──
        row = db.execute("SELECT ai_cleaned_content, text_content, fetched_at FROM news_articles WHERE id=?", (aid,)).fetchone()
        content_for_ai = (row[0] or row[1]) if row else html

        # a) 分析摘要
        try:
            summary = analyze_article(title, content_for_ai)
            if summary:
                db.execute("UPDATE news_articles SET ai_summary=?, ai_analyzed=1 WHERE id=?", (summary, aid))
                db.commit()
                result["steps"]["analyzed"] = True
            else:
                result["steps"]["analyzed"] = False
        except Exception as e:
            result["steps"]["analyzed"] = f"error: {e}"
            logger.warning(f"#{aid} 分析失败: {e}")

        # b) KCS 合并
        try:
            days = 0
            if fetched_at:
                try:
                    days = max(0, (datetime.now() - datetime.fromisoformat(fetched_at)).days)
                except Exception:
                    pass
            kcs = extract_keywords_classify_score_ai(title, content_for_ai, source, days)
            if kcs:
                kws = kcs.get("keywords", [])
                if kws:
                    db.execute("UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?",
                               (_json.dumps(kws, ensure_ascii=False), _json.dumps(kws, ensure_ascii=False), aid))
                if kcs.get("category"):
                    db.execute("UPDATE news_articles SET ai_category=?, ai_tags=? WHERE id=?",
                               (kcs["category"], _json.dumps(kcs.get("tags", []), ensure_ascii=False), aid))
                if "score" in kcs:
                    db.execute("UPDATE news_articles SET priority_score=?, priority_label=?, ai_priority_score=? WHERE id=?",
                               (kcs["score"], kcs.get("label", "medium"), kcs["score"], aid))
                db.commit()
                result["steps"]["kcs"] = f"{kcs.get('category','?')} {kcs.get('label','medium')}({kcs.get('score',0):.0f})"
                from api.dashboard import DashboardStream
                DashboardStream.publish("article_progress", {"id": aid, "title": title, "step": "kcs", "current": "KCS完成"})
            else:
                result["steps"]["kcs"] = "empty"
        except Exception as e:
            result["steps"]["kcs"] = f"error: {e}"
            logger.warning(f"#{aid} KCS 失败: {e}")

        db.commit()
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"process_article #{article_id} 异常: {e}")
    finally:
        db.close()
    return result


def process_all_pending() -> dict:
    """遍历所有待处理文章，逐篇执行 process_article()。返回进度汇总。"""

    db = _conn()
    rows = db.execute("""
        SELECT id FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
          AND ai_filtered != -1
          AND (ai_analyzed = 0 OR ai_cleaned_content IS NULL OR ai_cleaned_content = ''
               OR translated_content IS NULL OR translated_content = ''
               OR ai_keywords IS NULL OR ai_keywords = ''
               OR ai_category IS NULL OR ai_category = ''
               OR ai_priority_score IS NULL OR ai_priority_score = 0.0)
        ORDER BY id DESC
    """).fetchall()
    db.close()

    total = len(rows)
    done = 0
    failed = 0
    log: list[str] = []

    log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理 {total} 篇文章")

    for (aid,) in rows:
        r = process_article(aid)
        if r["ok"]:
            done += 1
        else:
            failed += 1
            log.append(f"#{aid} ❌ {r.get('error', '未知错误')}")
        time.sleep(0.5)

    log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 完成: {done}/{total}, 失败: {failed}")
    return {"total": total, "done": done, "failed": failed, "log": log}
