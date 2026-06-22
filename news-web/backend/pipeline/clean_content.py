#!/usr/bin/env python3
"""
AI 内容清洗管道步骤 — 将缓存 HTML 送入 LLM 提取纯净文章正文。
由 run_all.py 编排调用，环境变量 NEWS_DB_PATH 指定数据库路径。
也可独立运行：python clean_content.py [--limit N] [--recent D]

- 直接传原始 HTML 给 DeepSeek V3.2，利用 160K 上下文识别正文区域
- 清洗后 HTML 存入 ai_cleaned_content 列（仅正文，去广告/导航/侧栏/弹窗）
- 篇间 5 秒延迟防止 API 超限
- 后台静默执行，不影响其他管道步骤
"""
import os, sys, time, sqlite3, logging
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config
from api.articles import _sanitize_html
from ai_client import clean_article_content

logger = logging.getLogger(__name__)

CLEAN_DELAY = 5  # 篇间延迟秒数


def clean_articles(db_path: str, limit: int = 0, recent: int = 0) -> dict:
    """清洗所有已缓存但未清洗的文章 HTML。

    Returns:
        {'cleaned': int, 'failed': int, 'skipped': int}
    """
    if not config.openai_api_key:
        logger.warning("AI API Key 未配置 — 跳过内容清洗")
        return {'cleaned': 0, 'failed': 0, 'skipped': 0}

    conn = sqlite3.connect(db_path)

    # 查询已缓存 HTML 但尚未清洗的文章
    where = [
        "local_path != ''",
        "local_path NOT LIKE '[ERR:%'",
        "(ai_cleaned_content IS NULL OR ai_cleaned_content = '')",
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
        print("✅ 所有文章已完成 AI 内容清洗")
        return {'cleaned': 0, 'failed': 0, 'skipped': 0}

    print(f"🧹 待清洗 {total} 篇文章 (HTML → 纯净正文)")

    cache_dir = config.content_cache_path
    cleaned = failed = 0

    for idx, (aid, title, local_path) in enumerate(rows, 1):
        # 读取磁盘 HTML 文件
        html_path = os.path.join(cache_dir, os.path.basename(local_path))
        if not os.path.isfile(html_path):
            print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⚠️ HTML 文件不存在")
            continue

        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html = f.read()
        except Exception:
            print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⚠️ 读取失败")
            continue

        if len(html) < 200:
            print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⏭ HTML 太短")
            continue

        # 预处理：sanitize 后再送 AI
        html = _sanitize_html(html)

        print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} [{len(html)//1024}KB]", end=" ", flush=True)

        try:
            result = clean_article_content(html)
            if result and len(result) > 100:
                # 安全防线：对 AI 输出再做一次 sanitize
                result = _sanitize_html(result)

                conn2 = sqlite3.connect(db_path)
                conn2.execute(
                    "UPDATE articles SET ai_cleaned_content=? WHERE id=?",
                    (result, aid)
                )
                conn2.commit()
                conn2.close()
                print(f"✅ [{len(result)//1024}KB]")
                cleaned += 1
            else:
                print("⚠️ AI 返回空或过短")
        except Exception as e:
            print(f"❌ {str(e)[:300]}")
            failed += 1

        if idx < total:
            time.sleep(CLEAN_DELAY)

    print(f"\n📊 清洗完成: {cleaned} 成功, {failed} 失败")
    return {'cleaned': cleaned, 'failed': failed, 'skipped': total - cleaned - failed}


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [clean] %(message)s')

    p = argparse.ArgumentParser(description='AI 清洗文章 HTML 提取纯净正文')
    p.add_argument('--limit', type=int, default=0, help='限制清洗篇数')
    p.add_argument('--recent', type=int, default=0, help='只清洗最近 N 天的文章')
    p.add_argument('--db', default=os.environ.get('NEWS_DB_PATH', config.db_path),
                   help='数据库路径')
    args = p.parse_args()

    if not args.db:
        print("Error: 请通过 --db 或 NEWS_DB_PATH 环境变量指定数据库路径")
        sys.exit(1)

    clean_articles(args.db, args.limit, args.recent)
