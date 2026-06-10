#!/usr/bin/env python3
"""
文章页面本地存档 — 保存 HTML 文件到磁盘，DB 只记录路径

页面文件保存在 hot_reports/content/{article_id}.html
DB 中 articles.local_path 指向文件路径。

用法:
  python3 fetch_content.py                          # 全量补抓
  python3 fetch_content.py --limit 50               # 抓 50 篇
  python3 fetch_content.py --source Guru3D          # 只抓某来源
  python3 fetch_content.py --recent 3               # 最近 3 天的
  python3 fetch_content.py --path-only              # 只存路径(已下载的不重抓)
"""

import os, sys, re, time, sqlite3, urllib.request, urllib.error
from datetime import datetime, timedelta
from urllib.parse import urlparse

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
DELAY = 0.5
TIMEOUT = 15
BLOCKED = ['expreview.com', 'solidot.org', 'weibo.com', 'douyin.com']


def can_fetch(url: str) -> bool:
    return bool(url and url.startswith('http') and not any(d in url for d in BLOCKED))


def download_page(url: str) -> dict:
    """下载页面 HTML，返回 {'html': str, 'error': str|None}"""
    if not can_fetch(url):
        return {'html': '', 'error': 'Blocked'}
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            # detect encoding
            ct = resp.headers.get('Content-Type', '')
            cs = 'utf-8'
            if 'charset=' in ct:
                cs = ct.split('charset=')[-1].split(';')[0].strip()
            try:
                html = raw.decode(cs, errors='replace')
            except:
                html = raw.decode('utf-8', errors='replace')
        return {'html': html, 'error': None}
    except urllib.error.HTTPError as e:
        return {'html': '', 'error': f'HTTP {e.code}'}
    except Exception as e:
        return {'html': '', 'error': str(e)[:80]}


def archive_pages(db_path: str, limit: int = 0, source: str = None, recent: int = 0):
    """遍历 articles，找出尚未存档的页面，下载并保存 HTML 文件"""

    # ── 准备 DB + 目录 ──
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(articles)")]
    if 'local_path' not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN local_path TEXT DEFAULT ''")
        conn.commit()

    content_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'content')
    os.makedirs(content_dir, exist_ok=True)

    # ── 查询未存档文章 ──
    where = ["(local_path IS NULL OR local_path = '')"]
    params = []
    if source:
        where.append("source = ?")
        params.append(source)
    if recent:
        cutoff = (datetime.now() - timedelta(days=recent)).isoformat()
        where.append("fetched_at >= ?")
        params.append(cutoff)

    sql = f"""SELECT id, title, url, source FROM articles
              WHERE {' AND '.join(where)}
              ORDER BY id DESC"""
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    conn.close()

    if total == 0:
        print("✅ 所有文章已有本地存档")
        return

    print(f"📡 需要存档 {total} 篇文章")

    ok = err = skip = 0
    for idx, (aid, title, url, src) in enumerate(rows, 1):
        if not can_fetch(url):
            skip += 1
            continue

        print(f"  [{idx}/{total}] {src:20s} {title[:45]:45s}", end=" ", flush=True)
        res = download_page(url)

        conn2 = sqlite3.connect(db_path)
        if res['error']:
            print(f"❌ {res['error']}")
            conn2.execute("UPDATE articles SET local_path=? WHERE id=?",
                         (f'[ERR:{res["error"]}]', aid))
            err += 1
        elif res['html']:
            # save HTML to file
            file_path = os.path.join(content_dir, f'{aid}.html')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(res['html'])
            size = len(res['html'].encode('utf-8'))
            # store RELATIVE path in DB
            rel_path = f'content/{aid}.html'
            conn2.execute("UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                         (rel_path, datetime.now().isoformat(timespec='seconds'), aid))
            print(f"✅ {size//1024}KB")
            ok += 1
        else:
            print("⚠️ 空")
            skip += 1

        conn2.commit()
        conn2.close()
        time.sleep(DELAY)

    print(f"\n📊 完成: {ok} 成功, {err} 失败, {skip} 跳过 | 存档目录: {content_dir}")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    default_db = os.environ.get('NEWS_DB_PATH', os.path.expanduser(
        '~/claw_skill_news_aggregation/hot_reports/news.db'))
    p.add_argument('--db', default=default_db)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--source')
    p.add_argument('--recent', type=int, default=0)
    args = p.parse_args()
    archive_pages(args.db, args.limit, args.source, args.recent)
