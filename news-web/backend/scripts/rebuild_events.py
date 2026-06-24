#!/usr/bin/env python3
"""一次性全量重建事件数据。
清空所有事件相关表，对已处理文章逐篇进行 AI 语义聚类重建。

用法:
  cd news-web/backend
  python3 scripts/rebuild_events.py          # 全量重建
  python3 scripts/rebuild_events.py --dry-run # 预览不清空
"""
import sys, os, time, argparse, logging

# 路径修正
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from config import config
from utils.db import get_db_connection, safe_commit

logging.basicConfig(level=logging.INFO, format='%(asctime)s [Rebuild] %(message)s')
logger = logging.getLogger('rebuild')


def clear_all_events(db):
    """清空所有事件相关表。"""
    tables = ['chain_relations', 'chain_events', 'logic_chains',
              'event_relations', 'news_article_events', 'events']
    for t in tables:
        count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        db.execute(f"DELETE FROM {t}")
        logger.info(f"  清空 {t}: {count} 行")
    safe_commit(db)


def reset_article_status(db):
    """将所有已处理文章标记为 pending_cluster，等待重新匹配。"""
    count = db.execute("""
        UPDATE news_articles
        SET content_status = 'pending_cluster'
        WHERE content_status IN ('processed', 'fetched', 'translated')
          AND ai_keywords IS NOT NULL AND ai_keywords != ''
    """).rowcount
    safe_commit(db)
    logger.info(f"  重置 {count} 篇文章状态 → pending_cluster")


def rebuild_all(db_path: str, dry_run: bool = False):
    """清空并全量重建。"""
    db = get_db_connection(db_path)

    # 统计当前状态
    evt_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    art_count = db.execute("SELECT COUNT(*) FROM news_articles WHERE content_status IN ('processed','fetched','translated') AND ai_keywords IS NOT NULL AND ai_keywords != ''").fetchone()[0]

    logger.info(f"当前: {evt_count} 事件, {art_count} 篇可聚类文章")

    if dry_run:
        logger.info("[DRY RUN] 不执行实际清空和重建")
        db.close()
        return

    # Phase 1: 清空
    logger.info("Phase 1: 清空所有事件数据...")
    clear_all_events(db)

    # Phase 2: 重置文章状态
    logger.info("Phase 2: 重置文章状态...")
    reset_article_status(db)
    db.close()

    # Phase 3: 逐篇重建 — 按 fetched_at 从旧到新
    logger.info("Phase 3: 逐篇 AI 语义聚类...")
    from pipeline.event_matching import match_article_to_event

    db2 = get_db_connection(db_path)
    rows = db2.execute("""
        SELECT id, title FROM news_articles
        WHERE content_status = 'pending_cluster'
        ORDER BY fetched_at ASC
    """).fetchall()
    db2.close()

    total = len(rows)
    matched = 0
    pending = 0
    start_time = time.time()

    for i, (aid, title) in enumerate(rows):
        try:
            event_id = match_article_to_event(aid)
            if event_id:
                matched += 1
            else:
                pending += 1
        except Exception as e:
            logger.warning(f"  #{aid} 匹配异常: {e}")
            pending += 1

        # 进度报告
        if (i + 1) % 50 == 0 or (i + 1) == total:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            logger.info(
                f"  进度: {i + 1}/{total} ({100*(i+1)/total:.1f}%) — "
                f"已匹配: {matched}, pending: {pending}, "
                f"速率: {rate:.1f} 篇/秒"
            )

        time.sleep(0.3)  # API 速率保护

    elapsed = time.time() - start_time
    logger.info(f"重建完成: {matched}/{total} 篇已匹配, {pending} 篇 pending, 耗时: {elapsed:.0f}s")

    # Phase 4: 最终统计
    db3 = get_db_connection(db_path)
    evt_final = db3.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    evt_multi = db3.execute("""
        SELECT COUNT(*) FROM events e
        JOIN news_article_events ae ON ae.event_id = e.id
        GROUP BY e.id HAVING COUNT(ae.article_id) >= 2
    """).fetchall()
    db3.close()
    logger.info(f"最终: {evt_final} 事件, {len(evt_multi)} 个 ≥2 篇文章")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='全量重建事件数据')
    parser.add_argument('--dry-run', action='store_true', help='预览不清空')
    args = parser.parse_args()

    rebuild_all(config.db_path, dry_run=args.dry_run)
