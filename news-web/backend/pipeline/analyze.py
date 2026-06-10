#!/usr/bin/env python3
"""
AI 分析脚本 — 使用 OpenAI 兼容 API 增强事件分析和关系推荐
由 run_all.py 编排调用，环境变量 NEWS_DB_PATH 指定数据库路径
"""
import os, sys, sqlite3, logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

logger = logging.getLogger(__name__)

from config import config
from ai_client import chat, summarize_events
from db.news_db import extract_entities, extract_keywords


def analyze_events(db_path: str) -> int:
    """
    Analyze events using AI:
    1. Re-summarize event titles for events with ≥2 articles (improve clustering titles)
    2. Generate cross-event relation suggestions for recent events
    Returns the number of events improved.
    """
    conn = sqlite3.connect(db_path)
    improved = 0

    try:
        # ── 1. Improve event titles ──────────────────────────
        events = conn.execute("""
            SELECT e.id, e.title, e.article_count
            FROM events e
            WHERE e.status = 'active' AND e.article_count >= 2
            LIMIT 30
        """).fetchall()

        for evt_id, current_title, art_count in events:
            articles = conn.execute("""
                SELECT a.title FROM article_events ae
                JOIN articles a ON a.id = ae.article_id
                WHERE ae.event_id = ? LIMIT 20
            """, (evt_id,)).fetchall()

            if len(articles) < 2:
                continue

            titles_text = "\n".join(f"- {a[0]}" for a in articles)
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

        # ── 2. Generate event relation suggestions ────────────
        recent_events = conn.execute("""
            SELECT e.id, e.title FROM events e
            WHERE e.status = 'active' AND e.article_count >= 1
            ORDER BY e.last_seen DESC LIMIT 20
        """).fetchall()

        if len(recent_events) >= 2:
            event_text = "\n".join(
                f"[{e[0]}] {e[1]} (first_seen: {row[2] if len(row)>2 else '?'})"
                for e, row in zip(recent_events, conn.execute("""
                    SELECT id, title, first_seen FROM events
                    WHERE status='active' ORDER BY last_seen DESC LIMIT 20
                """).fetchall())
            )

            for i, evt1 in enumerate(recent_events):
                for j, evt2 in enumerate(recent_events):
                    if i >= j:
                        continue
                    # Check if relation already exists
                    existing = conn.execute(
                        "SELECT COUNT(*) FROM event_relations WHERE from_event_id=? AND to_event_id=?",
                        (evt1[0], evt2[0])
                    ).fetchone()[0]
                    if existing > 0:
                        continue

                    try:
                        prompt = (
                            f"Event A: {evt1[1]}\n"
                            f"Event B: {evt2[1]}\n\n"
                            f"Are these two events related? If yes, reply with the relation type "
                            f"(before, after, update, spawn, or related) and a one-line explanation. "
                            f"If not related, reply 'unrelated'."
                        )
                        response = chat(prompt, system_prompt=(
                            "You are a news event analysis assistant. "
                            "Determine if two events are causally, temporally, or topically related. "
                            "Output only the relation type or 'unrelated'."
                        ))
                        if response and 'unrelated' not in response.lower():
                            for rel_type in ['before', 'after', 'update', 'spawn', 'related']:
                                if rel_type in response.lower():
                                    conn.execute("""
                                        INSERT OR IGNORE INTO event_relations
                                            (from_event_id, to_event_id, relation, created_by, created_at)
                                        VALUES (?, ?, ?, 'auto', datetime('now'))
                                    """, (evt1[0], evt2[0], rel_type))
                                    logger.info(f"  AI relation: #{evt1[0]} --{rel_type}--> #{evt2[0]}")
                                    break
                    except Exception as e:
                        logger.warning(f"  AI relation check failed for #{evt1[0]}↔#{evt2[0]}: {e}")

        conn.commit()
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        conn.rollback()
    finally:
        conn.close()

    return improved


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [AI] %(message)s')
    db = os.environ.get('NEWS_DB_PATH', config.db_path)
    if not db:
        print("Error: NEWS_DB_PATH not set and config.db_path is empty")
        sys.exit(1)
    n = analyze_events(db)
    print(f"AI analysis complete — {n} events improved")
