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
from urllib.parse import urlparse, urljoin, urlunparse
from html.parser import HTMLParser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config
from utils.text import extract_text_from_html, detect_language

DELAY = 0.5
TIMEOUT = 15
BLOCKED = ['expreview.com', 'solidot.org', 'weibo.com', 'douyin.com']


def sanitize_html(html: str) -> str:
    """切除脚本和追踪标签——下载时就清理，缓存即干净。"""
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<noscript[\s\S]*?</noscript>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    html = re.sub(r'<iframe[\s\S]*?</iframe>', '', html, flags=re.IGNORECASE)
    return html


def can_fetch(url: str) -> bool:
    return bool(url and url.startswith('http') and not any(d in url for d in BLOCKED))


def download_page(url: str) -> dict:
    """下载页面 HTML，返回 {'html': str, 'error': str|None}"""
    if not can_fetch(url):
        return {'html': '', 'error': 'Blocked'}
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': config.user_agent,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
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


def extract_img_srcs(html: str, base_url: str) -> list:
    """从 HTML 中提取所有 <img> 的 src，解析为绝对 URL 并去重。"""
    urls = set()
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        src = m.group(1)
        if src.startswith('data:'):
            continue  # 跳过 data: URI (base64 内联)
        abs_url = urljoin(base_url, src)
        # 去除 query string 和 fragment 用于去重判断
        clean = urlunparse(urlparse(abs_url)._replace(query='', fragment=''))
        urls.add(clean)
    return list(urls)


def download_images(img_urls: list, img_dir: str, page_url: str) -> int:
    """下载图片到本地目录，返回成功下载数。"""
    os.makedirs(img_dir, exist_ok=True)
    downloaded = 0
    for i, img_url in enumerate(img_urls):
        if not can_fetch(img_url):
            continue
        try:
            ext = os.path.splitext(urlparse(img_url).path)[1]
            if not ext or len(ext) > 5:
                ext = '.jpg'
            file_name = f'{i:03d}{ext}'
            file_path = os.path.join(img_dir, file_name)
            if os.path.exists(file_path):
                downloaded += 1
                continue
            req = urllib.request.Request(img_url, headers={
                'User-Agent': config.user_agent,
                'Accept': 'image/webp,image/apng,image/*,*/*',
                'Referer': page_url,
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            if len(raw) < 100:
                continue
            with open(file_path, 'wb') as f:
                f.write(raw)
            downloaded += 1
        except Exception:
            continue
    return downloaded


def archive_pages(db_path: str, limit: int = 0, source: str = None, recent: int = 0):
    """遍历 articles，找出尚未存档的页面，下载并保存 HTML 文件"""

    # ── 准备 DB + 目录 ──
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(articles)")]
    if 'local_path' not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN local_path TEXT DEFAULT ''")
        conn.commit()

    content_dir = config.content_cache_path
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
            html = sanitize_html(res['html'])
            # 下载页面图片
            imgs = 0
            try:
                img_urls = extract_img_srcs(html, url)
                if img_urls:
                    article_img_dir = os.path.join(content_dir, str(aid), 'images')
                    imgs = download_images(img_urls, article_img_dir, url)
            except Exception:
                pass

            # 保存 HTML 到磁盘
            file_path = os.path.join(content_dir, f'{aid}.html')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html)
            size = len(html.encode('utf-8'))
            # 提取纯文本 + 语言检测
            text = extract_text_from_html(html)
            lang = detect_language(text)
            now = datetime.now().isoformat(timespec='seconds')
            rel_path = f'{os.path.basename(content_dir)}/{aid}.html'
            conn2.execute("""
                UPDATE articles SET
                    local_path=?, content_fetched_at=?,
                    text_content=?, content_lang=?, content_status='fetched'
                WHERE id=?
            """, (rel_path, now, text, lang, aid))
            img_info = f' 🖼{imgs}张' if imgs > 0 else ''
            print(f"✅ {size//1024}KB [{lang}]{img_info}", end="")
            # 内联翻译：英文文章且翻译功能已启用时立即翻译
            translated = False
            if lang == 'en' and config.translation_enabled and config.translation_api_key:
                try:
                    from translation_client import translate_to_chinese
                    translation = translate_to_chinese(text)
                    if translation:
                        conn2.execute("""
                            UPDATE articles SET
                                translated_content=?, content_status='translated', translated_at=?
                            WHERE id=?
                        """, (translation, datetime.now().isoformat(timespec='seconds'), aid))
                        translated = True
                except Exception as e:
                    print(f" [译❌]", end="")
            if translated:
                print(" [译✅]", end="")
            print()
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
