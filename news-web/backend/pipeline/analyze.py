#!/usr/bin/env python3
"""
AI 分析脚本 — 使用 OpenAI 兼容 API 增强事件分析和关系推荐
由 run_all.py 编排调用，环境变量 NEWS_DB_PATH 指定数据库路径
"""
import os, sys, re, sqlite3, logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

logger = logging.getLogger(__name__)

from config import config
from ai_client import chat, summarize_events, extract_keywords_ai, extract_keywords_batch


def analyze_events(db_path: str) -> tuple:
    """
    Analyze events using AI:
    0. Extract keywords for news_articles with content (AI-powered, replaces rule engine)
    1. Re-summarize event titles for events with ≥2 news_articles (improve clustering titles)
    2. Generate cross-event relation suggestions for recent events
    Returns the number of events improved.
    """
    conn = sqlite3.connect(db_path)
    improved = 0
    keywords_extracted = 0

    try:
        # ── 0. AI 关键词提取（批量模式）─────────────────────
        # 标题通道：pending 文章也可基于标题提取关键词，正文缺失时用标题替代
        pending_news_articles = conn.execute("""
            SELECT a.id, a.title, a.text_content, a.source
            FROM news_articles a
            WHERE content_status IN ('pending', 'fetched', 'translated')
              AND (a.ai_keywords IS NULL OR a.ai_keywords = '')
            ORDER BY a.id DESC LIMIT 100
        """).fetchall()

        if pending_news_articles:
            logger.info(f"AI 关键词提取: {len(pending_news_articles)} 篇待处理（批量模式）")
            import json as _json

            # 每批最多 50 篇，合并为一次 API 调用
            KW_BATCH = 50
            for batch_start in range(0, len(pending_news_articles), KW_BATCH):
                batch_rows = pending_news_articles[batch_start:batch_start + KW_BATCH]
                batch_articles = [
                    {"id": aid, "title": title, "text": text or '', "source": source or ''}
                    for aid, title, text, source in batch_rows
                ]
                try:
                    batch_kws = extract_keywords_batch(batch_articles)
                    if batch_kws:
                        for i, kws in enumerate(batch_kws):
                            if kws:
                                aid = batch_articles[i]["id"]
                                conn.execute(
                                    "UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?",
                                    (_json.dumps(kws, ensure_ascii=False),
                                     _json.dumps(kws, ensure_ascii=False), aid)
                                )
                                keywords_extracted += 1
                    else:
                        # 批量失败回退到逐篇模式
                        logger.warning("批量关键词提取失败，回退到逐篇模式")
                        for aid, title, text, source in batch_rows:
                            try:
                                kws = extract_keywords_ai(title, text or '', source or '')
                                if kws:
                                    conn.execute(
                                        "UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?",
                                        (_json.dumps(kws, ensure_ascii=False),
                                         _json.dumps(kws, ensure_ascii=False), aid)
                                    )
                                    keywords_extracted += 1
                            except Exception as e:
                                logger.warning(f"  extract_keywords_ai failed for #{aid}: {e}")
                except Exception as e:
                    logger.warning(f"  批量关键词提取异常: {e}，回退逐篇")
                    for aid, title, text, source in batch_rows:
                        try:
                            kws = extract_keywords_ai(title, text or '', source or '')
                            if kws:
                                conn.execute(
                                    "UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?",
                                    (_json.dumps(kws, ensure_ascii=False),
                                     _json.dumps(kws, ensure_ascii=False), aid)
                                )
                                keywords_extracted += 1
                        except Exception as e2:
                            logger.warning(f"  extract_keywords_ai failed for #{aid}: {e2}")
            conn.commit()
            logger.info(f"AI 关键词提取完成: {keywords_extracted}/{len(pending_news_articles)} 篇")

        # ── 1. Improve event titles ──────────────────────────
        events = conn.execute("""
            SELECT e.id, e.title, e.article_count
            FROM events e
            WHERE e.status = 'active' AND e.article_count >= 2
            LIMIT 30
        """).fetchall()

        for evt_id, current_title, art_count in events:
            news_articles = conn.execute("""
                SELECT a.title FROM news_article_events ae
                JOIN news_articles a ON a.id = ae.article_id
                WHERE ae.event_id = ? LIMIT 20
            """, (evt_id,)).fetchall()

            if len(news_articles) < 2:
                continue

            titles_text = "\n".join(f"- {a[0]}" for a in news_articles)
            try:
                ai_title = summarize_events(titles_text)
                if ai_title and len(ai_title) > 0 and ai_title != current_title:
                    conn.execute(
                        "UPDATE events SET title = ? WHERE id = ?",
                        (ai_title[:200], evt_id)
                    )
                    logger.info(f"  AI renamed event #{evt_id}: {current_title[:40]} → {ai_title[:60]}")
                    improved += 1
            except Exception as e:
                logger.warning(f"  summarize_events failed for #{evt_id}: {e}")

        # ── 2. Generate event relation suggestions (BATCHED) ────
        recent_events = conn.execute("""
            SELECT e.id, e.title FROM events e
            WHERE e.status = 'active' AND e.article_count >= 1
            ORDER BY e.last_seen DESC LIMIT 20
        """).fetchall()

        if len(recent_events) >= 2:
            # 收集所有候选配对（无已有关系），批量发送 AI 请求
            candidate_pairs = []
            for i, evt1 in enumerate(recent_events):
                for j, evt2 in enumerate(recent_events):
                    if i >= j:
                        continue
                    existing = conn.execute(
                        "SELECT COUNT(*) FROM event_relations WHERE from_event_id=? AND to_event_id=?",
                        (evt1[0], evt2[0])
                    ).fetchone()[0]
                    if existing == 0:
                        candidate_pairs.append((evt1, evt2))

            # 每批最多 50 个配对，一次 API 调用处理一批
            BATCH_SIZE = 50
            for batch_start in range(0, len(candidate_pairs), BATCH_SIZE):
                batch = candidate_pairs[batch_start:batch_start + BATCH_SIZE]
                if not batch:
                    break

                # 构造批量 prompt
                pairs_text = ""
                for idx, (evt1, evt2) in enumerate(batch, 1):
                    pairs_text += f"  Pair {idx}: A=[{evt1[1]}] B=[{evt2[1]}]\n"

                try:
                    response = chat(
                        f"请判断以下每对事件是否相关。如果相关，指定关系类型（before、after、update、spawn 或 related）。"
                        f"如果不相关，写 'unrelated'。\n\n"
                        f"每对输出一行，格式如下：\n"
                        f"  Pair N: relation_type - 简要理由\n\n"
                        f"{pairs_text}",
                        system_prompt=(
                            "你是资深新闻事件关系分析专家。对每对事件判断关系：\n"
                            "- 'before' = 事件 A 发生在事件 B 之前（时间先后）\n"
                            "- 'after' = 事件 A 发生在事件 B 之后\n"
                            "- 'update' = 事件 A 是事件 B 的更新/补充信息\n"
                            "- 'spawn' = 事件 A 导致/催生了事件 B（因果关系）\n"
                            "- 'related' = 同一大话题，但无明确时间/因果联系\n"
                            "- 'unrelated' = 不同话题，无有意义的关联\n"
                            "每对只输出一行，理由部分简明扼要。"
                        ),
                        max_tokens=2048,
                    )
                    if response:
                        # 解析批量结果
                        for idx, (evt1, evt2) in enumerate(batch, 1):
                            # 查找 Pair N 对应的行
                            pattern = rf'Pair\s*{idx}\s*:\s*(\w+)\s*[-–—]\s*(.+)'
                            match = re.search(pattern, response, re.IGNORECASE)
                            if match:
                                rel_type = match.group(1).lower()
                                if rel_type in ('before', 'after', 'update', 'spawn', 'related'):
                                    conn.execute("""
                                        INSERT OR IGNORE INTO event_relations
                                            (from_event_id, to_event_id, relation, created_by, created_at)
                                        VALUES (?, ?, ?, 'auto', datetime('now'))
                                    """, (evt1[0], evt2[0], rel_type))
                                    logger.info(f"  AI relation: #{evt1[0]} --{rel_type}--> #{evt2[0]}")
                except Exception as e:
                    logger.warning(f"  AI batch relation check failed: {e}")

        conn.commit()
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        conn.rollback()
    finally:
        conn.close()

    return improved, keywords_extracted


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [AI] %(message)s')
    db = os.environ.get('NEWS_DB_PATH', config.db_path)
    if not db:
        print("Error: NEWS_DB_PATH not set and config.db_path is empty")
        sys.exit(1)
    n, n_kw = analyze_events(db)
    print(f"AI analysis complete — {n} events improved, {n_kw} keywords extracted")
