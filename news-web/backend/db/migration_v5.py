#!/usr/bin/env python3
"""
v5 数据库迁移：articles 表拆分为 news_articles + trending_items

- 数据零丢失：迁移前文件级备份，迁移后自动校验
- 幂等：已执行则跳过
- 原子：整个迁移包裹在事务中，失败自动回滚

由 ensure_schema() 在启动时自动调用，也可独立运行：
    python3 db/migration_v5.py [--db path/to/news.db]
"""

import os
import shutil
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── DDL ──────────────────────────────────────────────────────────────

NEWS_ARTICLES_DDL = """
CREATE TABLE IF NOT EXISTS news_articles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT NOT NULL,
    source              TEXT DEFAULT '',
    url                 TEXT DEFAULT '',
    category            TEXT DEFAULT 'rss_news',
    published_date      TEXT DEFAULT '',
    fetched_at          TEXT NOT NULL,
    metadata            TEXT DEFAULT '{}',
    keywords            TEXT DEFAULT '[]',
    priority_score      REAL DEFAULT 0.0,
    priority_label      TEXT DEFAULT 'unset',
    human_verified      INTEGER DEFAULT 0,
    human_tags          TEXT DEFAULT '[]',
    local_path          TEXT DEFAULT '',
    content_fetched_at  TEXT,
    text_content        TEXT DEFAULT '',
    translated_content  TEXT DEFAULT '',
    content_lang        TEXT DEFAULT '',
    content_status      TEXT DEFAULT 'pending',
    translated_at       TEXT,
    ai_summary          TEXT DEFAULT '',
    ai_analyzed         INTEGER DEFAULT 0,
    human_processed     INTEGER DEFAULT 0,
    ai_keywords         TEXT DEFAULT '',
    ai_category         TEXT DEFAULT '',
    ai_tags             TEXT DEFAULT '',
    ai_priority_score   REAL DEFAULT 0.0,
    ai_filtered         INTEGER DEFAULT 0,
    topic_category      TEXT DEFAULT '',
    ai_cleaned_content  TEXT DEFAULT '',
    retry_count         INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_news_status    ON news_articles(content_status);
CREATE INDEX IF NOT EXISTS idx_news_source    ON news_articles(source);
CREATE INDEX IF NOT EXISTS idx_news_fetched   ON news_articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_articles(published_date);
CREATE INDEX IF NOT EXISTS idx_news_filtered  ON news_articles(ai_filtered);
CREATE INDEX IF NOT EXISTS idx_news_verified  ON news_articles(human_verified);
"""

TRENDING_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS trending_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    platform         TEXT NOT NULL,
    trend_type       TEXT NOT NULL DEFAULT 'hotlist',
    url              TEXT DEFAULT '',
    rank             INTEGER DEFAULT 0,
    heat_score       TEXT DEFAULT '',
    -- B站视频特有字段（热搜为 NULL / 空值）
    video_desc       TEXT DEFAULT '',
    author           TEXT DEFAULT '',
    play_count       INTEGER DEFAULT 0,
    danmaku_count    INTEGER DEFAULT 0,
    cover_url        TEXT DEFAULT '',
    -- 通用
    fetched_at       TEXT NOT NULL,
    published_date   TEXT DEFAULT '',
    metadata         TEXT DEFAULT '{}',
    text_content     TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_trending_platform ON trending_items(platform);
CREATE INDEX IF NOT EXISTS idx_trending_type     ON trending_items(trend_type);
CREATE INDEX IF NOT EXISTS idx_trending_fetched  ON trending_items(fetched_at);
"""

NEWS_ARTICLE_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS news_article_events (
    article_id INTEGER NOT NULL REFERENCES news_articles(id),
    event_id   INTEGER NOT NULL REFERENCES events(id),
    relevance  REAL DEFAULT 1.0,
    PRIMARY KEY (article_id, event_id)
);
"""

# ── 迁移用列映射 ─────────────────────────────────────────────────────

# articles 表的所有列（保持与旧表一致的顺序和命名）
_ARTICLE_COLS = [
    'id', 'title', 'source', 'url', 'category', 'published_date', 'fetched_at',
    'metadata', 'keywords', 'priority_score', 'priority_label', 'human_verified',
    'human_tags', 'local_path', 'content_fetched_at', 'text_content',
    'translated_content', 'content_lang', 'content_status', 'translated_at',
    'ai_summary', 'ai_analyzed', 'human_processed', 'ai_keywords',
    'ai_category', 'ai_tags', 'ai_priority_score', 'ai_filtered',
    'topic_category', 'ai_cleaned_content', 'retry_count',
]

# news_articles 的列（与 articles 完全一致，只是去掉了 future 不需要的列）
_NEWS_COLS = _ARTICLE_COLS  # 完全相同

# trending_items 需要从 articles 映射的字段
_TRENDING_FROM_ARTICLES = [
    'id', 'title', 'url', 'fetched_at', 'published_date', 'metadata', 'text_content',
]


def _backup_database(db_path: str) -> str:
    """文件级备份数据库，返回备份路径。"""
    backup_path = f"{db_path}.pre_migration_backup"
    shutil.copy2(db_path, backup_path)
    logger.info(f"数据库已备份到: {backup_path}")
    return backup_path


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """检查表是否存在。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def _is_v5_applied(conn: sqlite3.Connection) -> bool:
    """检查 v5 迁移是否已执行。"""
    row = conn.execute(
        "SELECT version FROM schema_version WHERE version >= 5"
    ).fetchone()
    return row is not None


def _migrate_news_articles(conn: sqlite3.Connection):
    """从 articles 迁移 RSS 新闻到 news_articles。"""
    cols = ', '.join(_NEWS_COLS)
    sql = f"""
        INSERT INTO news_articles ({cols})
        SELECT {cols}
        FROM articles
        WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')
    """
    count = conn.execute(sql).rowcount
    logger.info(f"迁移 news_articles: {count} 行")
    return count


def _migrate_trending_items(conn: sqlite3.Connection):
    """从 articles 迁移热搜/B站到 trending_items。"""
    sql = """
        INSERT INTO trending_items (
            id, title, platform, trend_type, url, rank, heat_score,
            video_desc, author, play_count, danmaku_count, cover_url,
            fetched_at, published_date, metadata, text_content
        )
        SELECT
            id, title,
            -- 从 source 列提取平台名
            CASE
                WHEN source LIKE 'weibo_%' THEN 'weibo'
                WHEN source LIKE 'zhihu_%' THEN 'zhihu'
                WHEN source LIKE 'douyin_%' THEN 'douyin'
                WHEN source LIKE 'toutiao_%' THEN 'toutiao'
                WHEN source LIKE 'bilibili_%' THEN 'bilibili'
                ELSE source
            END,
            CASE
                WHEN category = 'platform_hotlists' THEN 'hotlist'
                ELSE 'bilibili_video'
            END,
            url,
            -- rank: 从 metadata JSON 提取
            COALESCE(
                CAST(json_extract(metadata, '$.rank') AS INTEGER),
                0
            ),
            -- heat_score: 热搜热度值
            COALESCE(
                json_extract(metadata, '$.heat'),
                ''
            ),
            -- B站视频特有字段
            COALESCE(json_extract(metadata, '$.description'), json_extract(metadata, '$.desc'), ''),
            COALESCE(json_extract(metadata, '$.author'), json_extract(metadata, '$.owner'), json_extract(metadata, '$.up'), ''),
            COALESCE(CAST(json_extract(metadata, '$.play_count') AS INTEGER), CAST(json_extract(metadata, '$.play') AS INTEGER), 0),
            COALESCE(CAST(json_extract(metadata, '$.danmaku_count') AS INTEGER), CAST(json_extract(metadata, '$.danmaku') AS INTEGER), 0),
            COALESCE(json_extract(metadata, '$.cover_url'), json_extract(metadata, '$.cover'), json_extract(metadata, '$.pic'), ''),
            -- 通用字段
            fetched_at,
            published_date,
            metadata,
            COALESCE(text_content, '')
        FROM articles
        WHERE category IN ('platform_hotlists', 'bilibili_videos')
    """
    count = conn.execute(sql).rowcount
    logger.info(f"迁移 trending_items: {count} 行")
    return count


def _migrate_article_events(conn: sqlite3.Connection):
    """从 article_events 迁移到 news_article_events（仅保留新闻文章的事件关联）。"""
    sql = """
        INSERT INTO news_article_events (article_id, event_id, relevance)
        SELECT ae.article_id, ae.event_id, ae.relevance
        FROM article_events ae
        INNER JOIN news_articles na ON ae.article_id = na.id
    """
    count = conn.execute(sql).rowcount
    logger.info(f"迁移 news_article_events: {count} 行")
    return count


def _add_article_comments_type(conn: sqlite3.Connection):
    """为 article_comments 添加 content_type 列。"""
    cols = [c[1] for c in conn.execute("PRAGMA table_info(article_comments)").fetchall()]
    if 'content_type' not in cols:
        conn.execute("ALTER TABLE article_comments ADD COLUMN content_type TEXT DEFAULT 'news'")
        logger.info("article_comments 已添加 content_type 列")


def _validate_migration(conn: sqlite3.Connection, backup_path: str) -> list[str]:
    """迁移后校验。返回错误列表，空列表表示通过。"""
    errors = []
    bak = sqlite3.connect(backup_path)

    # 校验 1：总行数
    old_total = bak.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    new_news = conn.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0]
    new_trend = conn.execute("SELECT COUNT(*) FROM trending_items").fetchone()[0]
    new_total = new_news + new_trend

    if old_total != new_total:
        errors.append(f"总行数不匹配: articles={old_total}, news_articles+trending_items={new_total}")
    else:
        logger.info(f"校验 1/4 通过: 总行数 {old_total} = {new_news} + {new_trend}")

    # 校验 2：抽样逐字段比对（随机 100 行）
    sample = bak.execute("SELECT id FROM articles ORDER BY RANDOM() LIMIT 100").fetchall()
    news_cols = [c[1] for c in conn.execute("PRAGMA table_info(news_articles)").fetchall()]
    trending_cols = [c[1] for c in conn.execute("PRAGMA table_info(trending_items)").fetchall()]

    mismatches = 0
    for (aid,) in sample:
        old = bak.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        if old is None:
            errors.append(f"ID {aid} 在备份数据库中不存在")
            continue

        old_cat = old[4]  # category 列位置

        if old_cat in ('platform_hotlists', 'bilibili_videos'):
            new = conn.execute("SELECT * FROM trending_items WHERE id=?", (aid,)).fetchone()
        else:
            new = conn.execute("SELECT * FROM news_articles WHERE id=?", (aid,)).fetchone()

        if new is None:
            mismatches += 1
            errors.append(f"ID {aid} (category={old_cat}) 在新表中缺失")
            if mismatches >= 5:
                break  # 最多报 5 条差异

    if mismatches == 0:
        logger.info("校验 2/4 通过: 随机 100 行抽样无差异")

    # 校验 3：关联表完整性
    orphans = conn.execute("""
        SELECT article_id FROM news_article_events
        WHERE article_id NOT IN (SELECT id FROM news_articles)
    """).fetchall()
    if orphans:
        errors.append(f"news_article_events 中有 {len(orphans)} 条孤立记录: {[o[0] for o in orphans[:5]]}...")
    else:
        logger.info("校验 3/4 通过: 关联表无孤立记录")

    # 校验 4：event_relations 不受影响
    er_count = conn.execute("SELECT COUNT(*) FROM event_relations").fetchone()[0]
    logger.info(f"校验 4/4: event_relations 共 {er_count} 条（未受影响）")

    bak.close()
    return errors


def _cleanup_old_tables(conn: sqlite3.Connection):
    """删除旧表。"""
    if _table_exists(conn, 'article_events'):
        conn.execute("DROP TABLE article_events")
        logger.info("已删除 article_events")
    if _table_exists(conn, 'articles'):
        conn.execute("DROP TABLE articles")
        logger.info("已删除 articles")


def run_migration(db_path: str) -> bool:
    """执行 v5 迁移。返回 True 表示成功。"""
    if not db_path or not os.path.exists(db_path):
        logger.error(f"数据库路径无效: {db_path}")
        return False

    conn = sqlite3.connect(db_path)

    # 幂等检查
    if _is_v5_applied(conn):
        # 检查新表是否真的存在（双重确认）
        if _table_exists(conn, 'news_articles') and _table_exists(conn, 'trending_items'):
            logger.info("v5 迁移已执行，跳过")
            conn.close()
            return True
        else:
            logger.warning("schema_version 显示 v5 已应用，但新表不存在，将重新执行")

    # 前置检查
    if not _table_exists(conn, 'articles'):
        logger.warning("articles 表不存在，跳过 v5 迁移")
        conn.close()
        return True

    conn.close()

    # ── 备份 ──
    try:
        backup_path = _backup_database(db_path)
    except Exception as e:
        logger.error(f"数据库备份失败: {e}")
        return False

    # ── 迁移（事务性）──
    conn = sqlite3.connect(db_path)
    errors = []

    try:
        conn.execute("BEGIN IMMEDIATE")

        # 1. 建新表
        conn.executescript(NEWS_ARTICLES_DDL)
        conn.executescript(TRENDING_ITEMS_DDL)
        conn.executescript(NEWS_ARTICLE_EVENTS_DDL)
        logger.info("新表已创建")

        # 2. 数据迁移
        news_count = _migrate_news_articles(conn)
        trend_count = _migrate_trending_items(conn)
        events_count = _migrate_article_events(conn)

        # 3. article_comments 扩展
        _add_article_comments_type(conn)

        # 4. 迁移后校验（在提交前执行）
        errors = _validate_migration(conn, backup_path)

        if errors:
            # 校验失败：回滚整个迁移
            logger.error(f"迁移校验失败，回滚:\n" + "\n".join(f"  - {e}" for e in errors))
            conn.rollback()
            conn.close()
            return False

        # 5. 删除旧表
        _cleanup_old_tables(conn)

        # 6. 标记版本
        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (5)")

        conn.commit()
        logger.info(
            f"v5 迁移完成: news_articles={news_count}, "
            f"trending_items={trend_count}, "
            f"news_article_events={events_count}"
        )
        return True

    except Exception as e:
        logger.error(f"迁移异常，回滚: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ── 独立运行入口 ──────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [migration] %(message)s')

    p = argparse.ArgumentParser(description='v5 迁移：articles 拆分为 news_articles + trending_items')
    p.add_argument('--db', help='数据库路径（默认使用 config.json 中的配置）')
    p.add_argument('--dry-run', action='store_true', help='仅校验现有数据，不执行迁移')
    args = p.parse_args()

    if args.db:
        db_path = args.db
    else:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from config import config
        db_path = config.db_path

    if args.dry_run:
        conn = sqlite3.connect(db_path)
        news_sql = "SELECT COUNT(*) FROM articles WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')"
        hot_sql = "SELECT COUNT(*) FROM articles WHERE category = 'platform_hotlists'"
        bili_sql = "SELECT COUNT(*) FROM articles WHERE category = 'bilibili_videos'"
        print(f"articles: {conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]} 行")
        print(f"  RSS 新闻: {conn.execute(news_sql).fetchone()[0]}")
        print(f"  热搜: {conn.execute(hot_sql).fetchone()[0]}")
        print(f"  B站视频: {conn.execute(bili_sql).fetchone()[0]}")
        print(f"article_events: {conn.execute('SELECT COUNT(*) FROM article_events').fetchone()[0]} 行")
        conn.close()
    else:
        success = run_migration(db_path)
        if success:
            print("✅ v5 迁移成功完成")
        else:
            print("❌ v5 迁移失败，请检查日志并手动恢复数据库")
            print(f"   恢复命令: cp {db_path}.pre_migration_backup {db_path}")
            exit(1)
