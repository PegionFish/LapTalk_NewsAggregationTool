"""AI 语义事件匹配 — 替代旧版 bigram 聚类。
在 process_article() KCS 完成后调用，将文章关联到已有事件或标记 pending_cluster。
"""
import logging, json as _json
from datetime import datetime, timedelta
from config import config
from ai_client import match_article_to_events_ai
from utils.db import get_db_connection, safe_commit

logger = logging.getLogger(__name__)

# 候选事件筛选参数
MAX_CANDIDATES = 50        # AI 单次匹配的候选事件上限
CATEGORY_DAYS = 30         # 候选事件的时间窗口（天）


def _get_candidate_events(db, category: str, keywords: list[str], article_id: int) -> list[tuple[int, str]]:
    """筛选候选事件：同 category + 关键词交集 + 30 天内。

    优先级排序：
    1. 有关键词交集且 ≥2 篇的事件
    2. 同 category 且 ≥2 篇的事件
    3. 其余匹配条件的事件

    Args:
        db: 数据库连接
        category: 文章的 ai_category (如 'AI/LLM', 'Mobile')
        keywords: 文章的 ai_keywords 列表
        article_id: 当前文章 ID (排除自身已关联的事件)

    Returns:
        [(event_id, event_title), ...] 最多 MAX_CANDIDATES 个
    """
    cutoff = (datetime.now() - timedelta(days=CATEGORY_DAYS)).strftime('%Y-%m-%d')

    # 查询候选：最近 30 天的事件（含关键词聚合）
    rows = db.execute("""
        SELECT e.id, e.title, e.article_count,
               GROUP_CONCAT(a.ai_keywords, ' ') as all_kw
        FROM events e
        JOIN news_article_events ae ON ae.event_id = e.id
        JOIN news_articles a ON a.id = ae.article_id
        WHERE e.status = 'active'
          AND e.last_seen >= ?
        GROUP BY e.id
        HAVING COUNT(ae.article_id) >= 1
        ORDER BY e.article_count DESC
        LIMIT 200
    """, (cutoff,)).fetchall()

    if not rows:
        return []

    # 按关键词交集排序
    kw_set = set(k.lower() for k in keywords if len(k) > 1)
    scored = []
    for eid, etitle, count, all_kw_str in rows:
        all_kw = set((all_kw_str or '').lower().split())
        overlap = len(kw_set & all_kw)
        # 同 category 加分
        cat_bonus = 2 if category and _category_overlap(category, etitle) else 0
        score = overlap + cat_bonus + min(count, 10) * 0.1
        scored.append((score, eid, etitle))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [(eid, etitle) for _, eid, etitle in scored[:MAX_CANDIDATES]]


def _category_overlap(category: str, event_title: str) -> bool:
    """检查文章 category 是否与事件标题中的关键词匹配。
    用于对同 category 事件加分。
    """
    cat_keywords = {
        'AI/LLM': ['ai', 'llm', 'gpt', 'claude', 'gemini', 'openai', 'anthropic', 'deepseek'],
        'Mobile': ['ios', 'android', 'iphone', 'ipad', 'pixel', 'mobile', '手机'],
        'PC/Hardware': ['cpu', 'gpu', 'amd', 'intel', 'nvidia', 'chip', '硬件', '服务器'],
        'Gaming': ['game', 'gaming', 'xbox', 'playstation', 'nintendo', '游戏'],
        'Security': ['security', '漏洞', '攻击', 'hack', '安全'],
        'Semiconductors': ['chip', '半导体', 'wafer', 'tsmc', 'samsung', '制程'],
        'Enterprise': ['cloud', 'aws', 'azure', 'google cloud', '企业'],
        'Automotive': ['car', 'ev', 'tesla', '自动驾驶', '汽车'],
        'Space': ['spacex', 'nasa', '火箭', '卫星', 'space'],
        'Regulation': ['regulation', 'ban', '法规', '监管', '禁止'],
        'OpenSource': ['open source', '开源', 'linux', 'github'],
    }
    patterns = cat_keywords.get(category, [])
    etitle_lower = event_title.lower()
    return any(p in etitle_lower for p in patterns)


def match_article_to_event(article_id: int, db=None) -> int | None:
    """对单篇文章进行 AI 语义事件匹配。

    在 process_article() KCS 完成后调用。

    Args:
        article_id: 文章 ID

    Returns:
        匹配的 event_id，或 None（文章标记为 pending_cluster）
    """
    own_db = db is None
    if own_db:
        db = get_db_connection(config.db_path)
    try:
        # 获取文章信息
        row = db.execute("""
            SELECT id, title, ai_category, ai_keywords
            FROM news_articles WHERE id = ?
        """, (article_id,)).fetchone()
        if not row:
            return None

        aid, title, category, kw_json = row
        try:
            keywords = _json.loads(kw_json or '[]')
        except (_json.JSONDecodeError, TypeError):
            keywords = []

        # 筛选候选事件
        candidates = _get_candidate_events(db, category or '', keywords, aid)

        if not candidates:
            logger.info(f"#{aid} 无候选事件，标记 pending_cluster")
            db.execute(
                "UPDATE news_articles SET content_status = 'pending_cluster' WHERE id = ?",
                (aid,)
            )
            safe_commit(db)
            return None

        # AI 语义匹配
        result = match_article_to_events_ai(title, candidates)

        if result and result.get('event_id'):
            event_id = result['event_id']
            confidence = result.get('confidence', 0.0)
            # 写入关联
            db.execute(
                "INSERT OR IGNORE INTO news_article_events (article_id, event_id, relevance) VALUES (?, ?, ?)",
                (aid, event_id, round(confidence, 2))
            )
            # 更新事件 article_count 和 last_seen
            row_date = db.execute(
                "SELECT published_date, fetched_at FROM news_articles WHERE id = ?",
                (aid,)
            ).fetchone()
            event_date = (row_date[0] or row_date[1])[:10] if row_date else datetime.now().strftime('%Y-%m-%d')
            db.execute(
                "UPDATE events SET last_seen = MAX(last_seen, ?), article_count = article_count + 1 WHERE id = ?",
                (event_date, event_id)
            )
            safe_commit(db)
            logger.info(
                f"#{aid} AI 匹配 → Event#{event_id} (置信度: {confidence:.2f}) — {result.get('reason', '')}"
            )
            return event_id
        else:
            # AI 无法确定归属
            logger.info(f"#{aid} AI 无法确定归属，标记 pending_cluster")
            db.execute(
                "UPDATE news_articles SET content_status = 'pending_cluster' WHERE id = ?",
                (aid,)
            )
            safe_commit(db)
            return None

    except Exception as e:
        logger.error(f"match_article_to_event #{article_id} 异常: {e}")
        # 失败时不阻塞文章处理，标记 pending_cluster 等待下次批处理
        try:
            db.execute(
                "UPDATE news_articles SET content_status = 'pending_cluster' WHERE id = ?",
                (article_id,)
            )
            safe_commit(db)
        except Exception:
            pass
        return None
    finally:
        if own_db:
            db.close()
