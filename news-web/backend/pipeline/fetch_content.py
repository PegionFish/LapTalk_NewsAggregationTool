#!/usr/bin/env python3
"""
文章页面本地存档 — 保存 HTML 文件到磁盘，DB 只记录路径

页面文件保存在 hot_reports/content/{article_id}.html
DB 中 news_articles.local_path 指向文件路径。

用法:
  python3 fetch_content.py                          # 全量补抓
  python3 fetch_content.py --limit 50               # 抓 50 篇
  python3 fetch_content.py --source Guru3D          # 只抓某来源
  python3 fetch_content.py --recent 3               # 最近 3 天的
  python3 fetch_content.py --path-only              # 只存路径(已下载的不重抓)
"""

import os, sys, re, time, sqlite3, urllib.request, urllib.error, logging
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, urlunparse
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config
from utils.text import FULL_TEXT_MAX_LENGTH, extract_text_from_html, detect_language

logger = logging.getLogger(__name__)

# ── 境外代理 — 如已配置代理则启用 ──────────────────────
try:
    from utils.proxy import setup_urllib_proxy
    setup_urllib_proxy()
except Exception:
    pass

DELAY = 0.5
TIMEOUT = 300
BLOCKED = ['weibo.com', 'douyin.com']


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


def download_page(url: str, retries: int = 2, timeout: int = 300) -> dict:
    """下载页面 HTML，返回 {'html': str, 'error': str|None}。网络临时错误自动重试。

    Args:
        timeout: 单次请求超时秒数，默认 300s（正常下载）；批量重试传入 60s 即可。
    """
    if not can_fetch(url):
        return {'html': '', 'error': 'Blocked'}
    last_error = ''
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': config.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            if e.code == 403 and attempt < retries:
                time.sleep(1)
                continue
            logger.debug(f"[fetch_content] HTTP {e.code} from {url[:80]}: {e.reason}")
            return {'html': '', 'error': f'HTTP {e.code}'}
        except (urllib.error.URLError, OSError, ConnectionError) as e:
            last_error = str(e)[:300]
            if attempt < retries:
                logger.debug(f"[fetch_content] 临时网络错误 {url[:80]} (重试 {attempt + 1}/{retries}): {last_error[:100]}")
                time.sleep(1)
                continue
            logger.warning(f"[fetch_content] 网络错误 {url[:80]}: {last_error[:100]}")
            return {'html': '', 'error': last_error}
        except Exception as e:
            logger.warning(f"[fetch_content] 未知错误 {url[:80]}: {type(e).__name__}: {e}")
            return {'html': '', 'error': str(e)[:300]}
    return {'html': '', 'error': last_error}


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


def fetch_article_content(url: str, article_id: int, db_path: str = None) -> dict:
    """下载并归档单篇文章页面，返回缓存结果。"""
    if db_path is None:
        db_path = config.db_path
    if not db_path:
        return {'ok': False, 'error': 'database_not_configured'}

    if not can_fetch(url):
        return {'ok': False, 'error': 'Blocked'}

    res = download_page(url)
    conn = sqlite3.connect(db_path)
    try:
        if res['error']:
            conn.execute("UPDATE news_articles SET local_path=? WHERE id=?",
                         (f'[ERR:{res["error"]}]', article_id))
            conn.commit()
            return {'ok': False, 'error': res['error']}

        if not res['html']:
            return {'ok': False, 'error': 'empty_response'}

        html = sanitize_html(res['html'])
        content_dir = config.content_cache_path
        os.makedirs(content_dir, exist_ok=True)

        imgs = 0
        try:
            img_urls = extract_img_srcs(html, url)
            if img_urls:
                article_img_dir = os.path.join(content_dir, str(article_id), 'images')
                imgs = download_images(img_urls, article_img_dir, url)
        except Exception:
            pass

        file_path = os.path.join(content_dir, f'{article_id}.html')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html)
        size = len(html.encode('utf-8'))

        text = extract_text_from_html(html, max_length=FULL_TEXT_MAX_LENGTH)
        lang = detect_language(text)
        now = datetime.now().isoformat(timespec='seconds')
        rel_path = f'{os.path.basename(content_dir)}/{article_id}.html'
        conn.execute("""
            UPDATE news_articles SET
                local_path=?, content_fetched_at=?,
                text_content=?, content_lang=?, content_status='fetched'
            WHERE id=?
        """, (rel_path, now, text, lang, article_id))

        conn.commit()
        return {
            'ok': True,
            'local_path': rel_path,
            'content_status': 'fetched',
            'size': size,
            'images': imgs,
            'lang': lang,
        }
    finally:
        conn.close()


MAX_WORKERS = 8  # 并行下载线程数


def _fetch_single(args):
    """单篇文章下载（供线程池调用）。失败时递增 retry_count，连续 ≥2 次 404/410 标记 dead。"""
    aid, title, url, src, content_dir, db_path = args
    if not can_fetch(url):
        return {'aid': aid, 'status': 'skip', 'msg': 'blocked'}

    res = download_page(url)
    if res['error']:
        # 递增 retry_count 并检查是否应标记 dead
        DEAD_CODES = {404, 410, 451}
        err_code = None
        for code in DEAD_CODES:
            if f'HTTP {code}' in res['error']:
                err_code = code
                break
        conn = sqlite3.connect(db_path)
        if err_code is not None:
            # 同类型错误递增计数
            conn.execute("""
                UPDATE news_articles SET
                    local_path=?, content_fetched_at=?,
                    retry_count = CASE
                        WHEN local_path LIKE ('[ERR:HTTP ' || ? || '%') THEN retry_count + 1
                        ELSE 1
                    END
                WHERE id=?
            """, (f'[ERR:{res["error"]}]', datetime.now().isoformat(timespec='seconds'),
                  str(err_code), aid))
            # 检查是否该标记 dead
            rc = conn.execute("SELECT retry_count FROM news_articles WHERE id=?", (aid,)).fetchone()
            if rc and rc[0] >= 2:
                conn.execute("UPDATE news_articles SET content_status='dead' WHERE id=?", (aid,))
        else:
            conn.execute("""
                UPDATE news_articles SET local_path=?, content_fetched_at=?, retry_count=retry_count+1
                WHERE id=?
            """, (f'[ERR:{res["error"]}]', datetime.now().isoformat(timespec='seconds'), aid))
        conn.commit()
        conn.close()
        return {'aid': aid, 'status': 'error', 'msg': res['error'][:80]}

    if not res['html']:
        return {'aid': aid, 'status': 'skip', 'msg': 'empty'}

    html = sanitize_html(res['html'])

    # 下载图片
    imgs = 0
    try:
        img_urls = extract_img_srcs(html, url)
        if img_urls:
            article_img_dir = os.path.join(content_dir, str(aid), 'images')
            imgs = download_images(img_urls, article_img_dir, url)
    except Exception:
        pass

    # 保存 HTML
    file_path = os.path.join(content_dir, f'{aid}.html')
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html)
    size = len(html.encode('utf-8'))

    # 提取文本 + 语言检测
    text = extract_text_from_html(html, max_length=FULL_TEXT_MAX_LENGTH)
    lang = detect_language(text)
    now = datetime.now().isoformat(timespec='seconds')
    rel_path = f'{os.path.basename(content_dir)}/{aid}.html'

    # 写入 DB（翻译由 translate_content.py 独立处理）
    conn = sqlite3.connect(db_path)
    conn.execute("""
        UPDATE news_articles SET
            local_path=?, content_fetched_at=?,
            text_content=?, content_lang=?, content_status='fetched'
        WHERE id=?
    """, (rel_path, now, text, lang, aid))
    conn.commit()
    conn.close()

    return {
        'aid': aid, 'status': 'ok', 'src': src, 'title': title[:40],
        'size': size, 'lang': lang, 'imgs': imgs,
    }


def archive_pages(db_path: str, limit: int = 0, source: str = None, recent: int = 0):
    """遍历 news_articles，找出尚未存档的页面，多线程并行下载并保存 HTML 文件"""

    # ── 准备 DB + 目录 ──
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(news_articles)")]
    if 'local_path' not in cols:
        conn.execute("ALTER TABLE news_articles ADD COLUMN local_path TEXT DEFAULT ''")
        conn.commit()

    content_dir = config.content_cache_path
    os.makedirs(content_dir, exist_ok=True)

    # ── 查询未存档文章 ──
    where = [
        "content_status = 'pending'",
        "ai_filtered = 1",
    ]
    params = []
    if source:
        where.append("source = ?")
        params.append(source)
    if recent:
        cutoff = (datetime.now() - timedelta(days=recent)).isoformat()
        where.append("fetched_at >= ?")
        params.append(cutoff)

    sql = f"""SELECT id, title, url, source FROM news_articles
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

    print(f"📡 需要存档 {total} 篇文章（{MAX_WORKERS} 线程并行下载）")

    # 构建任务参数
    tasks = [
        (aid, title, url, src, content_dir, db_path)
        for aid, title, url, src in rows
        if url and url.startswith('http')
    ]

    ok = err = skip = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_single, t): t for t in tasks}
        for idx, future in enumerate(as_completed(futures), 1):
            r = future.result()
            if r['status'] == 'ok':
                img_info = f" 🖼{r['imgs']}张" if r.get('imgs', 0) > 0 else ''
                print(f"  [{idx}/{total}] ✅ {r['src']:20s} {r['title']:40s} {r['size']//1024}KB [{r['lang']}]{img_info}")
                ok += 1
            elif r['status'] == 'error':
                print(f"  [{idx}/{total}] ❌ #{r['aid']} {r['msg']}")
                err += 1
            else:
                skip += 1

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
