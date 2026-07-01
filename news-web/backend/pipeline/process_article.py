#!/usr/bin/env python3
"""单篇文章处理编排器 —— 清洗→翻译→分析+KCS 线性执行。
每步完成后立即写入 DB，进度不丢失。缓存由数据采集环节负责。
"""
import sys, os, time, logging, json as _json
from datetime import datetime
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

from config import config
from ai_client import clean_article_content, analyze_article, extract_keywords_classify_score_ai
from translation_client import translate_html_preserve_structure, translate_html
from dbwriter.db_writer import get_db_writer
from utils.db import safe_commit

logger = logging.getLogger(__name__)


def _conn():
    from utils.db import get_db_connection
    return get_db_connection(config.db_path)


def _is_not_empty(val) -> bool:
    if val is None: return False
    if isinstance(val, str): return len(val.strip()) > 0
    if isinstance(val, (int, float)): return val > 0
    return bool(val)


def _write_and_wait(sql: str, params: tuple = (), timeout: float = 30.0) -> bool:
    """通过 Writer 写 DB 并等待确认。超时返回 False 由调用方处理。"""
    try:
        writer = get_db_writer()
    except RuntimeError:
        # Writer 未初始化，降级为直连
        logger.warning("DbWriter 未初始化，降级为直连 safe_commit")
        db = _conn()
        try:
            db.execute(sql, params)
            from utils.db import safe_commit
            safe_commit(db)
        finally:
            db.close()
        return True

    event = writer.submit(sql, params)
    if not event.wait(timeout=timeout):
        logger.error(f"DbWriter 确认超时 ({timeout}s)，SQL: {sql[:100]}")
        return False
    return True


def recover_stuck_articles():
    db = _conn()
    try:
        count = db.execute("SELECT COUNT(*) FROM news_articles WHERE content_status='processing'").fetchone()[0]
        if count > 0:
            db.execute("UPDATE news_articles SET content_status='fetched' WHERE content_status='processing'")
            safe_commit(db)
            logger.info(f"恢复 {count} 篇 stuck processing → fetched")
    finally:
        db.close()


def process_article(article_id: int) -> dict:
    """单篇处理：清洗→翻译→分析+KCS。每步即时写 DB，已完成的跳过。"""
    result = {"ok": True, "steps": {}, "error": ""}
    db = _conn()
    try:
        row = db.execute("""
            SELECT id, title, local_path, text_content, source, fetched_at,
                   ai_cleaned_content, translated_content, ai_summary,
                   ai_keywords, ai_category, ai_priority_score
            FROM news_articles WHERE id=?
        """, (article_id,)).fetchone()
        if not row:
            db.close(); return {"ok": False, "error": f"文章 #{article_id} 不存在"}
        aid, title, local_path, text_content, source, fetched_at = row[:6]
        ex_clean, ex_trans, ex_summary = row[6], row[7], row[8]
        ex_kw, ex_cat, ex_score = row[9], row[10], row[11]

        _write_and_wait("UPDATE news_articles SET content_status='processing' WHERE id=?", (aid,))

        html = ""
        has_full_content = False
        if local_path and not local_path.startswith('[ERR:') and os.path.exists(local_path):
            with open(local_path, encoding='utf-8', errors='replace') as f:
                html = f.read()
            has_full_content = bool(html and len(html.strip()) >= 100)
        elif text_content:
            html = text_content
            has_full_content = bool(html and len(html.strip()) >= 100)
        # 无缓存内容时仍继续处理 — 标题通道：清洗/翻译跳过，KCS+事件匹配基于标题

        # Step 1: 清洗（仅在有缓存内容时执行）
        if _is_not_empty(ex_clean) and len(ex_clean.strip()) > 50:
            result["steps"]["cleaned"] = f"{len(ex_clean)} chars"
        elif _is_not_empty(ex_trans) and len(ex_trans.strip()) > 50:
            result["steps"]["cleaned"] = "skipped (翻译已完成)"
        elif not has_full_content:
            result["steps"]["cleaned"] = "skipped (无缓存内容，标题通道)"
        else:
            try:
                c = clean_article_content(html)
                if c and len(c.strip()) > 50:
                    _write_and_wait("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (c, aid))
                    result["steps"]["cleaned"] = f"{len(c)} chars"
                else:
                    _write_and_wait("UPDATE news_articles SET ai_cleaned_content='[EMPTY]' WHERE id=?", (aid,))
                    result["steps"]["cleaned"] = "empty"
            except Exception as e:
                result["steps"]["cleaned"] = f"error: {e}"
                logger.warning(f"#{aid} 清洗: {e}")

        # Step 2: 翻译（仅在有缓存内容时执行）
        if _is_not_empty(ex_trans) and len(ex_trans.strip()) > 50:
            result["steps"]["translated"] = f"{len(ex_trans)} chars"
        elif not has_full_content:
            result["steps"]["translated"] = "skipped (无缓存内容，标题通道)"
        else:
            try:
                t = translate_html_preserve_structure(html) if (config.translation_enabled and config.translation_api_key) else translate_html(html)
                if t:
                    _write_and_wait("UPDATE news_articles SET translated_content=? WHERE id=?", (t, aid))
                    result["steps"]["translated"] = f"{len(t)} chars"
                else:
                    result["steps"]["translated"] = "empty"
            except Exception as e:
                result["steps"]["translated"] = f"error: {e}"

        # Step 3: 分析+KCS
        row3 = db.execute("SELECT ai_cleaned_content, text_content FROM news_articles WHERE id=?", (aid,)).fetchone()
        content = (row3[0] or row3[1]) if row3 else html
        # 无缓存内容时用标题作为摘要素材
        if not content or len(content.strip()) < 50:
            content = title

        if _is_not_empty(ex_summary) and len(ex_summary.strip()) > 50:
            result["steps"]["analyzed"] = True
        else:
            try:
                s = analyze_article(title, content)
                if s:
                    _write_and_wait("UPDATE news_articles SET ai_summary=?, ai_analyzed=1 WHERE id=?", (s, aid))
                    result["steps"]["analyzed"] = True
                else:
                    result["steps"]["analyzed"] = False
            except Exception as e:
                result["steps"]["analyzed"] = f"error: {e}"

        if _is_not_empty(ex_kw) and _is_not_empty(ex_cat) and _is_not_empty(ex_score):
            result["steps"]["kcs"] = f"{ex_cat} {ex_score:.0f}"
        else:
            try:
                days = 0
                if fetched_at:
                    try: days = max(0, (datetime.now() - datetime.fromisoformat(fetched_at)).days)
                    except Exception: pass
                # 标题通道：KCS 可基于标题+来源完成关键词提取和分类
                k = extract_keywords_classify_score_ai(title, content, source or "", days)
                if k:
                    for col, val in [("keywords", _json.dumps(k.get("keywords",[]), ensure_ascii=False)),
                                      ("ai_keywords", _json.dumps(k.get("keywords",[]), ensure_ascii=False)),
                                      ("ai_category", k.get("category","")),
                                      ("ai_tags", _json.dumps(k.get("tags",[]), ensure_ascii=False)),
                                      ("priority_score", k.get("score",0)),
                                      ("priority_label", k.get("label","medium")),
                                      ("ai_priority_score", k.get("score",0))]:
                        if val is not None:
                            _write_and_wait(f"UPDATE news_articles SET {col}=? WHERE id=?", (val, aid))
                    result["steps"]["kcs"] = f"{k.get('category','?')} {k.get('label','medium')}({k.get('score',0):.0f})"
                else:
                    result["steps"]["kcs"] = "empty"
            except Exception as e:
                result["steps"]["kcs"] = f"error: {e}"

        # Step 4: AI 语义事件匹配（替代旧版 bigram link_articles_to_events）
        try:
            from pipeline.event_matching import match_article_to_event
            matched_event = match_article_to_event(aid, db)
            if matched_event:
                result["steps"]["event_match"] = f"Event#{matched_event}"
            else:
                result["steps"]["event_match"] = "pending_cluster"
        except Exception as e:
            result["steps"]["event_match"] = f"error: {e}"
            logger.warning(f"#{aid} 事件匹配: {e}")

        # 确定最终状态：事件匹配成功 → processed，否则 → pending_cluster
        matched = result["steps"].get("event_match") and str(result["steps"]["event_match"]).startswith("Event#")
        ok = result["steps"].get("analyzed") == True
        if ok and matched:
            final_status = "processed"
        elif ok and not matched:
            final_status = "pending_cluster"
        else:
            final_status = "fetched"
        _write_and_wait("UPDATE news_articles SET content_status=? WHERE id=?", (final_status, aid))
    except Exception as e:
        from ai_client import BalanceInsufficientError
        if isinstance(e, BalanceInsufficientError):
            raise  # 余额不足，穿透到批处理层暂停管线
        result["ok"] = False; result["error"] = str(e)
        logger.error(f"process_article #{article_id}: {e}")
    finally:
        db.close()
    return result


def process_all_pending() -> dict:
    db = _conn()
    rows = db.execute("""
        SELECT id FROM news_articles
        WHERE content_status IN ('pending', 'fetched', 'translated')
          AND (ai_filtered IS NULL OR ai_filtered != -1)
          AND (ai_analyzed = 0 OR (ai_cleaned_content IS NULL OR ai_cleaned_content = '') AND ai_cleaned_content != '[EMPTY]'
               OR translated_content IS NULL OR translated_content = ''
               OR ai_keywords IS NULL OR ai_keywords = ''
               OR ai_category IS NULL OR ai_category = ''
               OR ai_priority_score IS NULL OR ai_priority_score = 0.0)
        ORDER BY id DESC
    """).fetchall()
    db.close()
    total = len(rows); done = 0; failed = 0; log = []
    log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始 {total} 篇")
    for (aid,) in rows:
        r = process_article(aid)
        if r["ok"]: done += 1
        else: failed += 1; log.append(f"#{aid} ❌ {r.get('error','')[:100]}")
        time.sleep(0.3)
    log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 完成: {done}/{total}, 失败: {failed}")
    return {"total": total, "done": done, "failed": failed, "log": log}
