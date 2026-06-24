#!/usr/bin/env python3
"""单篇文章处理编排器 —— 缓存→清洗→翻译→分析+KCS 线性执行。
支持两种模式：
- 直接写入：process_article() 每步完成后写入 DB（单篇/小批量）
- 收集模式：process_article_collect() 返回更新字典，由调用方批量写入
"""
import sys, os, sqlite3, time, logging, json as _json
from datetime import datetime
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

from config import config
from ai_client import clean_article_content, analyze_article, extract_keywords_classify_score_ai
from translation_client import translate_html_preserve_structure, translate_html

logger = logging.getLogger(__name__)


def _conn():
    from utils.db import get_db_connection
    return get_db_connection(config.db_path)


def _is_not_empty(val) -> bool:
    """判断 DB 字段是否已有有效内容。"""
    if val is None:
        return False
    if isinstance(val, str):
        return len(val.strip()) > 0
    if isinstance(val, (int, float)):
        return val > 0
    return bool(val)


def recover_stuck_articles():
    """恢复卡在 'processing' 状态的文章（服务重启后调用）。
    将其重置为 'fetched'，以便下一轮处理重新拾取。
    """
    db = _conn()
    try:
        count = db.execute(
            "SELECT COUNT(*) FROM news_articles WHERE content_status='processing'"
        ).fetchone()[0]
        if count > 0:
            db.execute(
                "UPDATE news_articles SET content_status='fetched' WHERE content_status='processing'"
            )
            db.commit()
            logger.info(f"恢复 {count} 篇卡在 processing 状态的文章 → fetched")
    except Exception as e:
        logger.warning(f"恢复 stuck articles 失败: {e}")
    finally:
        db.close()


def process_article(article_id: int) -> dict:
    """单篇文章完整处理：缓存(如未缓存)→清洗→翻译→分析+KCS。
    每步写入 DB，已完成的步骤自动跳过。
    返回 {"ok": bool, "steps": {...}, "error": str}
    """
    result = {"ok": True, "steps": {}, "error": ""}
    db = _conn()

    try:
        row = db.execute("""
            SELECT id, title, url, local_path, text_content, source, content_status, fetched_at,
                   ai_cleaned_content, translated_content, ai_summary,
                   ai_keywords, ai_category, ai_priority_score
            FROM news_articles WHERE id=?
        """, (article_id,)).fetchone()
        if not row:
            db.close()
            return {"ok": False, "error": f"文章 #{article_id} 不存在"}

        aid = row[0]; title = row[1]; url = row[2]; local_path = row[3]
        text_content = row[4]; source = row[5]; status = row[6]; fetched_at = row[7]
        existing_cleaned = row[8]; existing_translated = row[9]; existing_summary = row[10]
        existing_keywords = row[11]; existing_category = row[12]; existing_score = row[13]

        # 标记处理中
        db.execute("UPDATE news_articles SET content_status='processing' WHERE id=?", (aid,))
        db.commit()

        # ── Step 1: 内容缓存 ──
        if not local_path or local_path.startswith('[ERR:'):
            from pipeline.fetch_content import fetch_article_content
            fetch_result = fetch_article_content(url, aid, config.content_cache_path)
            result["steps"]["cached"] = fetch_result.get("ok", False)
        else:
            result["steps"]["cached"] = True

        # 重新读取 local_path
        row2 = db.execute("SELECT local_path, text_content FROM news_articles WHERE id=?", (aid,)).fetchone()
        local_path, text_content = row2 if row2 else ("", "")

        # 读取 HTML
        html = ""
        if local_path and not local_path.startswith('[ERR:') and os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8', errors='replace') as f:
                html = f.read()
        elif text_content:
            html = text_content

        if not html or len(html.strip()) < 100:
            db.execute("UPDATE news_articles SET content_status='failed' WHERE id=?", (aid,))
            db.commit(); db.close()
            return {"ok": False, "error": f"#{aid} 无有效 HTML 内容", "steps": result["steps"]}

        # ── Step 2: 内容清洗（跳过已完成）──
        if _is_not_empty(existing_cleaned) and len(existing_cleaned.strip()) > 50:
            result["steps"]["cleaned"] = f"{len(existing_cleaned)} chars (已缓存)"
        else:
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

        # ── Step 3: 翻译（跳过已完成）──
        if _is_not_empty(existing_translated) and len(existing_translated.strip()) > 50:
            result["steps"]["translated"] = f"{len(existing_translated)} chars (已缓存)"
        else:
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
        row3 = db.execute("SELECT ai_cleaned_content, text_content, fetched_at FROM news_articles WHERE id=?", (aid,)).fetchone()
        content_for_ai = (row3[0] or row3[1]) if row3 else html

        # a) 分析摘要（跳过已完成）
        if _is_not_empty(existing_summary) and len(existing_summary.strip()) > 50:
            result["steps"]["analyzed"] = True
        else:
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

        # b) KCS 合并（跳过已完成 — 三个字段都有有效值就跳过）
        kcs_already_done = (
            _is_not_empty(existing_keywords) and
            _is_not_empty(existing_category) and
            _is_not_empty(existing_score)
        )
        if kcs_already_done:
            result["steps"]["kcs"] = f"{existing_category} {existing_score:.0f} (已缓存)"
        else:
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

        # 标记处理完成
        cleaned_ok = isinstance(result["steps"].get("cleaned"), str) and not result["steps"]["cleaned"].startswith(("error", "empty"))
        analyzed_ok = result["steps"].get("analyzed") == True
        new_status = 'processed' if (cleaned_ok or _is_not_empty(existing_cleaned)) and analyzed_ok else 'fetched'
        db.execute("UPDATE news_articles SET content_status=? WHERE id=?", (new_status, aid))
        db.commit()
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"process_article #{article_id} 异常: {e}")
        try:
            db.execute("UPDATE news_articles SET content_status='fetched' WHERE id=?", (article_id,))
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
    return result


def process_article_collect(article_id: int) -> dict:
    """与 process_article 相同的处理逻辑，但不写入 DB。
    返回 {"ok": bool, "steps": {...}, "updates": {column: value, ...}, "error": str}
    调用方负责批量写入 updates。
    """
    result = {"ok": True, "steps": {}, "updates": {}, "error": ""}
    db = _conn()

    try:
        row = db.execute("""
            SELECT id, title, url, local_path, text_content, source, content_status, fetched_at,
                   ai_cleaned_content, translated_content, ai_summary,
                   ai_keywords, ai_category, ai_priority_score
            FROM news_articles WHERE id=?
        """, (article_id,)).fetchone()
        if not row:
            db.close()
            return {"ok": False, "error": f"文章 #{article_id} 不存在", "steps": {}, "updates": {}}

        aid = row[0]; title = row[1]; url = row[2]; local_path = row[3]
        text_content = row[4]; source = row[5]; fetched_at = row[7]
        existing_cleaned = row[8]; existing_translated = row[9]; existing_summary = row[10]
        existing_keywords = row[11]; existing_category = row[12]; existing_score = row[13]

        updates: dict[str, Any] = {}
        result["updates"] = updates
        updates["content_status"] = "processing"

        # ── Step 1: 内容缓存 ──
        if not local_path or local_path.startswith('[ERR:'):
            from pipeline.fetch_content import fetch_article_content
            fr = fetch_article_content(url, aid, config.content_cache_path)
            result["steps"]["cached"] = fr.get("ok", False)
        else:
            result["steps"]["cached"] = True

        row2 = db.execute("SELECT local_path, text_content FROM news_articles WHERE id=?", (aid,)).fetchone()
        local_path, text_content = row2 if row2 else ("", "")

        html = ""
        if local_path and not local_path.startswith('[ERR:') and os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8', errors='replace') as f:
                html = f.read()
        elif text_content:
            html = text_content

        if not html or len(html.strip()) < 100:
            updates["content_status"] = "failed"
            db.close()
            return {"ok": False, "error": f"#{aid} 无有效 HTML 内容", "steps": result["steps"], "updates": updates}

        # ── Step 2: 内容清洗 ──
        if _is_not_empty(existing_cleaned) and len(existing_cleaned.strip()) > 50:
            result["steps"]["cleaned"] = f"{len(existing_cleaned)} chars (已缓存)"
        else:
            try:
                cleaned = clean_article_content(html)
                if cleaned and len(cleaned.strip()) > 50:
                    updates["ai_cleaned_content"] = cleaned
                    result["steps"]["cleaned"] = f"{len(cleaned)} chars"
                    from api.dashboard import DashboardStream
                    DashboardStream.publish("article_progress", {"id": aid, "title": title, "step": "cleaning", "done": 0, "total": 0, "current": f"#{aid} 清洗完成"})
                else:
                    result["steps"]["cleaned"] = "empty"
            except Exception as e:
                result["steps"]["cleaned"] = f"error: {e}"
                logger.warning(f"#{aid} 清洗失败: {e}")
                from api.dashboard import DashboardStream
                DashboardStream.publish("article_failed", {"id": aid, "title": title, "error": f"清洗: {e}", "step": "cleaning"})

        # ── Step 3: 翻译 ──
        if _is_not_empty(existing_translated) and len(existing_translated.strip()) > 50:
            result["steps"]["translated"] = f"{len(existing_translated)} chars (已缓存)"
        else:
            try:
                if config.translation_enabled and config.translation_api_key:
                    translated = translate_html_preserve_structure(html)
                else:
                    translated = translate_html(html)
                if translated:
                    updates["translated_content"] = translated
                    result["steps"]["translated"] = f"{len(translated)} chars"
                else:
                    result["steps"]["translated"] = "empty"
            except Exception as e:
                result["steps"]["translated"] = f"error: {e}"

        # ── Step 4: 分析+KCS ──
        row3 = db.execute("SELECT ai_cleaned_content, text_content, fetched_at FROM news_articles WHERE id=?", (aid,)).fetchone()
        content_for_ai = (row3[0] or row3[1]) if row3 else html

        # a) 分析摘要
        if _is_not_empty(existing_summary) and len(existing_summary.strip()) > 50:
            result["steps"]["analyzed"] = True
        else:
            try:
                summary = analyze_article(title, content_for_ai)
                if summary:
                    updates["ai_summary"] = summary
                    updates["ai_analyzed"] = 1
                    result["steps"]["analyzed"] = True
                else:
                    result["steps"]["analyzed"] = False
            except Exception as e:
                result["steps"]["analyzed"] = f"error: {e}"

        # b) KCS 合并
        kcs_already_done = (
            _is_not_empty(existing_keywords) and
            _is_not_empty(existing_category) and
            _is_not_empty(existing_score)
        )
        if kcs_already_done:
            result["steps"]["kcs"] = f"{existing_category} {existing_score:.0f} (已缓存)"
        else:
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
                        updates["keywords"] = _json.dumps(kws, ensure_ascii=False)
                        updates["ai_keywords"] = _json.dumps(kws, ensure_ascii=False)
                    if kcs.get("category"):
                        updates["ai_category"] = kcs["category"]
                        updates["ai_tags"] = _json.dumps(kcs.get("tags", []), ensure_ascii=False)
                    if "score" in kcs:
                        updates["priority_score"] = kcs["score"]
                        updates["priority_label"] = kcs.get("label", "medium")
                        updates["ai_priority_score"] = kcs["score"]
                    result["steps"]["kcs"] = f"{kcs.get('category','?')} {kcs.get('label','medium')}({kcs.get('score',0):.0f})"
                    from api.dashboard import DashboardStream
                    DashboardStream.publish("article_progress", {"id": aid, "title": title, "step": "kcs", "done": 0, "total": 0, "current": f"#{aid} KCS完成"})
                else:
                    result["steps"]["kcs"] = "empty"
            except Exception as e:
                result["steps"]["kcs"] = f"error: {e}"

        # 最终状态
        cleaned_ok = isinstance(result["steps"].get("cleaned"), str) and not result["steps"]["cleaned"].startswith(("error", "empty"))
        analyzed_ok = result["steps"].get("analyzed") == True
        updates["content_status"] = "processed" if (cleaned_ok or _is_not_empty(existing_cleaned)) and analyzed_ok else "fetched"
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"process_article_collect #{article_id} 异常: {e}")
        result.setdefault("updates", {})["content_status"] = "fetched"
    finally:
        db.close()
    return result


def flush_updates_batch(db: sqlite3.Connection, article_updates: list[tuple[int, dict]]):
    """批量写入文章处理结果到 DB。在单个事务中完成，避免写锁竞争。"""
    for aid, updates in article_updates:
        if not updates:
            continue
        set_clauses = []
        values = []
        for col, val in updates.items():
            set_clauses.append(f"{col}=?")
            values.append(val)
        if set_clauses:
            values.append(aid)
            db.execute(f"UPDATE news_articles SET {', '.join(set_clauses)} WHERE id=?", values)
    db.commit()


def process_all_pending() -> dict:
    """遍历所有待处理文章（content_status IN ('fetched','translated') 且非 processing/processed），
    逐篇执行 process_article()。返回进度汇总。
    """
    db = _conn()
    rows = db.execute("""
        SELECT id FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
          AND ai_filtered != -1
          AND (local_path != '' OR text_content != '')
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
            log.append(f"#{aid} ❌ {r.get('error', '未知错误')[:120]}")
        time.sleep(0.5)

    log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 完成: {done}/{total}, 失败: {failed}")
    return {"total": total, "done": done, "failed": failed, "log": log}
