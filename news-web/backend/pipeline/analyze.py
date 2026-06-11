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

            # 每批最多 15 个配对，一次 API 调用处理一批
            BATCH_SIZE = 15
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
                        f"For each pair below, determine if the two events are related. "
                        f"If related, specify the relation type (before, after, update, spawn, or related). "
                        f"If unrelated, write 'unrelated'.\n\n"
                        f"Output one line per pair in this exact format:\n"
                        f"  Pair N: relation_type - brief reason\n\n"
                        f"{pairs_text}",
                        system_prompt=(
                            "You are a senior news event relationship analyst. "
                            "For each event pair, determine the relationship:\n"
                            "- 'before' = Event A happened before Event B (temporal order)\n"
                            "- 'after' = Event A happened after Event B\n"
                            "- 'update' = Event A provides new information / update to Event B\n"
                            "- 'spawn' = Event A caused or led to Event B (causal)\n"
                            "- 'related' = same general topic but no clear temporal/causal link\n"
                            "- 'unrelated' = different topics, no meaningful connection\n"
                            "Output ONLY one line per pair, no explanations beyond the reason phrase."
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

    return improved


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [AI] %(message)s')
    db = os.environ.get('NEWS_DB_PATH', config.db_path)
    if not db:
        print("Error: NEWS_DB_PATH not set and config.db_path is empty")
        sys.exit(1)
    n = analyze_events(db)
    print(f"AI analysis complete — {n} events improved")
