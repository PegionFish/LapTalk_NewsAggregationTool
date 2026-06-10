#!/usr/bin/env python3
"""
AI 翻译管道步骤 — 将英文文章翻译为中文。
由 run_all.py 编排调用，环境变量 NEWS_DB_PATH 指定数据库路径。
也可独立运行：python translate_content.py [--limit N] [--recent D]

- 篇间 5 秒延迟防止 API 超限
- 翻译失败记 content_status='failed'，不阻塞后续文章
- 后台静默执行，不影响页面归档和 AI 分析流程
"""
import os, sys, time, sqlite3, logging
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config
from translation_client import translate_to_chinese

logger = logging.getLogger(__name__)

TRANSLATE_DELAY = 5  # 篇间延迟秒数


def translate_articles(db_path: str, limit: int = 0, recent: int = 0) -> dict:
    """翻译所有待处理的英文文章。

    Returns:
        {'translated': int, 'failed': int, 'skipped': int}
    """
    if not config.translation_api_key:
        logger.warning("翻译 API Key 未配置 — 跳过翻译")
        return {'translated': 0, 'failed': 0, 'skipped': 0}

    conn = sqlite3.connect(db_path)

    # 查询待翻译文章：已获取文本 + 英文 + 未翻译
    where = ["content_status='fetched'", "content_lang='en'", "(translated_content IS NULL OR translated_content='')"]
    params = []
    if recent:
        cutoff = (datetime.now() - timedelta(days=recent)).isoformat()
        where.append("fetched_at >= ?")
        params.append(cutoff)

    sql = f"SELECT id, title, text_content FROM articles WHERE {' AND '.join(where)} ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    total = len(rows)
    if total == 0:
        print("✅ 所有英文文章已翻译")
        return {'translated': 0, 'failed': 0, 'skipped': 0}

    print(f"🌐 待翻译 {total} 篇英文文章")

    translated = failed = 0
    for idx, (aid, title, text) in enumerate(rows, 1):
        if not text:
            continue
        print(f"  [{idx}/{total}] #{aid} {title[:50]:50s}", end=" ", flush=True)
        try:
            result = translate_to_chinese(text)
            if result:
                conn2 = sqlite3.connect(db_path)
                conn2.execute("""
                    UPDATE articles SET
                        translated_content=?, content_status='translated', translated_at=?
                    WHERE id=?
                """, (result, datetime.now().isoformat(timespec='seconds'), aid))
                conn2.commit()
                conn2.close()
                print("✅")
                translated += 1
            else:
                print("⚠️ 空结果")
        except Exception as e:
            conn2 = sqlite3.connect(db_path)
            conn2.execute("UPDATE articles SET content_status='failed' WHERE id=?", (aid,))
            conn2.commit()
            conn2.close()
            print(f"❌ {str(e)[:60]}")
            failed += 1

        # 篇间延迟
        if idx < total:
            time.sleep(TRANSLATE_DELAY)

    print(f"\n📊 翻译完成: {translated} 成功, {failed} 失败")
    return {'translated': translated, 'failed': failed, 'skipped': total - translated - failed}


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [translate] %(message)s')

    p = argparse.ArgumentParser(description='翻译英文文章为中文')
    p.add_argument('--limit', type=int, default=0, help='限制翻译篇数')
    p.add_argument('--recent', type=int, default=0, help='只翻译最近 N 天的文章')
    p.add_argument('--db', default=os.environ.get('NEWS_DB_PATH', config.db_path),
                   help='数据库路径')
    args = p.parse_args()

    if not args.db:
        print("Error: 请通过 --db 或 NEWS_DB_PATH 环境变量指定数据库路径")
        sys.exit(1)

    translate_articles(args.db, args.limit, args.recent)
