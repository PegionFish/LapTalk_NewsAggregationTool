#!/usr/bin/env python3
"""
AI 翻译管道步骤 — 将英文文章的 HTML 页面翻译为中文。
由 run_all.py 编排调用，环境变量 NEWS_DB_PATH 指定数据库路径。
也可独立运行：python translate_content.py [--limit N] [--recent D]

- 直接传原始 HTML 给 DeepSeek，LLM 自行区分标签和文本
- 翻译后的 HTML 存入 translated_content 列
- 篇间 5 秒延迟防止 API 超限
- 后台静默执行，不影响页面归档和 AI 分析流程
"""
import os, sys, time, sqlite3, logging
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config
from translation_client import translate_html

logger = logging.getLogger(__name__)

TRANSLATE_DELAY = 5  # 篇间延迟秒数


def translate_articles(db_path: str, limit: int = 0, recent: int = 0) -> dict:
    """翻译所有待处理的英文文章 HTML。

    Returns:
        {'translated': int, 'failed': int, 'skipped': int}
    """
    if not config.translation_api_key:
        logger.warning("翻译 API Key 未配置 — 跳过翻译")
        return {'translated': 0, 'failed': 0, 'skipped': 0}

    conn = sqlite3.connect(db_path)

    # 查询已下载 HTML 的英文文章，且尚未翻译
    where = [
        "content_lang='en'",
        "local_path != ''",
        "local_path NOT LIKE '[ERR:%'",
        "(translated_content IS NULL OR translated_content = '')",
        "content_status NOT IN ('dead', 'metadata_only')",
    ]
    params: list = []
    if recent:
        cutoff = (datetime.now() - timedelta(days=recent)).isoformat()
        where.append("fetched_at >= ?")
        params.append(cutoff)

    sql = f"SELECT id, title, local_path FROM articles WHERE {' AND '.join(where)} ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    total = len(rows)
    if total == 0:
        print("✅ 所有英文文章已翻译")
        return {'translated': 0, 'failed': 0, 'skipped': 0}

    print(f"🌐 待翻译 {total} 篇英文文章 (HTML → 中文)")

    cache_dir = config.content_cache_path
    translated = failed = 0

    for idx, (aid, title, local_path) in enumerate(rows, 1):
        # 读取磁盘 HTML 文件
        html_path = os.path.join(cache_dir, os.path.basename(local_path))
        if not os.path.isfile(html_path):
            print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⚠️ HTML 文件不存在")
            # 写入标记避免下次重复查询
            conn2 = sqlite3.connect(db_path)
            conn2.execute("UPDATE articles SET translated_content='[ERR:FILE_MISSING]' WHERE id=?", (aid,))
            conn2.commit()
            conn2.close()
            continue

        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html = f.read()
        except Exception:
            print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⚠️ 读取失败")
            conn2 = sqlite3.connect(db_path)
            conn2.execute("UPDATE articles SET translated_content='[ERR:READ_FAILED]' WHERE id=?", (aid,))
            conn2.commit()
            conn2.close()
            continue

        if len(html) < 100:
            conn2 = sqlite3.connect(db_path)
            conn2.execute("UPDATE articles SET translated_content='[ERR:HTML_TOO_SHORT]' WHERE id=?", (aid,))
            conn2.commit()
            conn2.close()
            continue

        print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} [{len(html)//1024}KB]", end=" ", flush=True)

        try:
            result = translate_html(html)
            if result and len(result) > 100:
                conn2 = sqlite3.connect(db_path)
                conn2.execute("""
                    UPDATE articles SET
                        translated_content=?, content_status='translated', translated_at=?
                    WHERE id=?
                """, (result, datetime.now().isoformat(timespec='seconds'), aid))
                conn2.commit()
                conn2.close()
                print(f"✅ [{len(result)//1024}KB]")
                translated += 1
            else:
                print("⚠️ 空结果")
        except Exception as e:
            conn2 = sqlite3.connect(db_path)
            conn2.execute("UPDATE articles SET content_status='failed' WHERE id=?", (aid,))
            conn2.commit()
            conn2.close()
            print(f"❌ {str(e)[:300]}")
            failed += 1

        if idx < total:
            time.sleep(TRANSLATE_DELAY)

    print(f"\n📊 翻译完成: {translated} 成功, {failed} 失败")
    return {'translated': translated, 'failed': failed, 'skipped': total - translated - failed}


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [translate] %(message)s')

    p = argparse.ArgumentParser(description='翻译英文文章 HTML 为中文')
    p.add_argument('--limit', type=int, default=0, help='限制翻译篇数')
    p.add_argument('--recent', type=int, default=0, help='只翻译最近 N 天的文章')
    p.add_argument('--db', default=os.environ.get('NEWS_DB_PATH', config.db_path),
                   help='数据库路径')
    args = p.parse_args()

    if not args.db:
        print("Error: 请通过 --db 或 NEWS_DB_PATH 环境变量指定数据库路径")
        sys.exit(1)

    translate_articles(args.db, args.limit, args.recent)
