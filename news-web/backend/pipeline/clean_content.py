#!/usr/bin/env python3
"""
AI 内容清洗管道步骤 — 将缓存 HTML 送入 LLM 提取纯净文章正文。
由 run_all.py 编排调用，环境变量 NEWS_DB_PATH 指定数据库路径。
也可独立运行：python clean_content.py [--limit N] [--recent D]

- 直接传原始 HTML 给 DeepSeek V3.2，利用 160K 上下文识别正文区域
- 清洗后 HTML 存入 ai_cleaned_content 列（仅正文，去广告/导航/侧栏/弹窗）
- 受控并发（MAX_WORKERS=8），平衡 API 压力与处理速度
- 后台静默执行，不影响其他管道步骤
"""
import os, sys, time, sqlite3, logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config
from api.news import _sanitize_html
from ai_client import clean_article_content

logger = logging.getLogger(__name__)

MAX_WORKERS = 8       # 并发数 — 平衡 API QPS 与处理速度
ARTICLE_TIMEOUT = 180  # 单篇最长处理时间（秒），超时跳过


def _clean_one(article: tuple, cache_dir: str, db_path: str, idx: int, total: int) -> dict:
    """清洗单篇文章（线程安全 — 独立 DB 连接）。"""
    aid, title, local_path = article
    result = {"id": aid, "title": title, "status": "skipped", "detail": ""}

    html_path = os.path.join(cache_dir, os.path.basename(local_path))
    if not os.path.isfile(html_path):
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:FILE_MISSING]' WHERE id=?", (aid,))
        conn.commit(); conn.close()
        result["detail"] = "FILE_MISSING"
        logger.warning(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⚠️ HTML 文件不存在")
        return result

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except Exception:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:READ_FAILED]' WHERE id=?", (aid,))
        conn.commit(); conn.close()
        result["detail"] = "READ_FAILED"
        logger.warning(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⚠️ 读取失败")
        return result

    if len(html) < 200:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:HTML_TOO_SHORT]' WHERE id=?", (aid,))
        conn.commit(); conn.close()
        result["detail"] = f"HTML_TOO_SHORT({len(html)}B)"
        print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} ⏭ HTML 太短 ({len(html)} 字符)")
        return result

    html = _sanitize_html(html)
    print(f"  [{idx}/{total}] #{aid} {title[:45]:45s} [{len(html)//1024}KB]", end=" ", flush=True)

    try:
        cleaned = clean_article_content(html)
        if cleaned and len(cleaned) > 100:
            cleaned = _sanitize_html(cleaned)
            conn = sqlite3.connect(db_path)
            conn.execute("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (cleaned, aid))
            conn.commit(); conn.close()
            print(f"✅ [{len(cleaned)//1024}KB]")
            result["status"] = "cleaned"
            result["detail"] = f"{len(cleaned)} chars"
        else:
            print("⚠️ AI 返回空或过短")
            result["detail"] = "AI_EMPTY"
    except Exception as e:
        print(f"❌ {str(e)[:300]}")
        result["status"] = "failed"
        result["detail"] = str(e)[:200]

    return result


def clean_news_articles(db_path: str, limit: int = 0, recent: int = 0) -> dict:
    """清洗所有已缓存但未清洗的文章 HTML（受控并发）。

    Returns:
        {'cleaned': int, 'failed': int, 'skipped': int}
    """
    if not config.openai_api_key:
        logger.warning("AI API Key 未配置 — 跳过内容清洗")
        return {'cleaned': 0, 'failed': 0, 'skipped': 0}

    conn = sqlite3.connect(db_path)

    where = [
        "content_status IN ('fetched', 'translated')",
        "(ai_cleaned_content IS NULL OR ai_cleaned_content = '')",
    ]
    params: list = []
    if recent:
        cutoff = (datetime.now() - timedelta(days=recent)).isoformat()
        where.append("fetched_at >= ?")
        params.append(cutoff)

    sql = f"SELECT id, title, local_path FROM news_articles WHERE {' AND '.join(where)} ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    total = len(rows)
    if total == 0:
        print("✅ 所有文章已完成 AI 内容清洗")
        return {'cleaned': 0, 'failed': 0, 'skipped': 0}

    print(f"🧹 待清洗 {total} 篇文章 (HTML → 纯净正文) [并发: {MAX_WORKERS}]")

    cache_dir = config.content_cache_path
    cleaned = failed = skipped = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {
            executor.submit(_clean_one, row, cache_dir, db_path, i, total): i
            for i, row in enumerate(rows, 1)
        }
        for future in as_completed(future_to_idx):
            try:
                r = future.result()
            except Exception as e:
                logger.warning(f"clean_content 线程异常: {e}")
                failed += 1
                continue
            if r["status"] == "cleaned":
                cleaned += 1
            elif r["status"] == "failed":
                failed += 1
            else:
                skipped += 1

    print(f"\n📊 清洗完成: {cleaned} 成功, {failed} 失败, {skipped} 跳过")
    return {'cleaned': cleaned, 'failed': failed, 'skipped': skipped}


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

    clean_news_articles(args.db, args.limit, args.recent)
