#!/usr/bin/env python3
"""
浏览器级页面捕获 — Playwright 渲染 JS 页面 + PDF 兜底。
当 fetch_content.py 的 HTTP 请求无法获取内容时自动降级到此模块。

用法:
  python3 browser_capture.py --article-id 42
  python3 browser_capture.py --limit 10
"""

import os, sys, sqlite3, re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config

TIMEOUT = 60000
BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/125.0.0.0 Safari/537.36'
)
STEALTH_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--disable-automation',
    '--disable-web-security',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-popup-blocking',
    '--disable-infobars',
]


def _stealth_page(page) -> None:
    """注入隐身脚本，降低被反爬虫检测的风险。"""
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    """)


def _sanitize_html(html: str) -> str:
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<noscript[\s\S]*?</noscript>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    html = re.sub(r'<iframe[\s\S]*?</iframe>', '', html, flags=re.IGNORECASE)
    return html


def capture_page_playwright(url: str, article_id: int = 0) -> dict:
    """Playwright 渲染页面，返回 HTML + PDF。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'html': '', 'pdf_path': None, 'error': 'Playwright not installed'}

    html = ''
    pdf_path = None
    error = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=STEALTH_ARGS,
            )
            context = browser.new_context(
                user_agent=BROWSER_UA,
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
            )
            page = context.new_page()
            _stealth_page(page)
            try:
                page.goto(url, wait_until='networkidle', timeout=TIMEOUT)
                page.wait_for_timeout(3000)
                html = page.content()

                if article_id:
                    cache_dir = config.content_cache_path
                    os.makedirs(cache_dir, exist_ok=True)
                    pdf_path = os.path.join(cache_dir, f'{article_id}.pdf')
                    page.pdf(path=pdf_path, format='A4', print_background=True)
            except Exception as e:
                error = str(e)[:300]
                try:
                    html = page.content()
                except Exception:
                    pass
            finally:
                context.close()
                browser.close()
    except Exception as e:
        error = str(e)[:300]

    return {'html': html, 'pdf_path': pdf_path, 'error': error}


def fetch_with_fallback(url: str, article_id: int = 0) -> dict:
    """三级回退抓取：HTTP → Playwright HTML → Playwright PDF。

    Returns:
        {'html': str, 'source': str, 'pdf_path': str|None, 'error': str|None}
        source: 'http' | 'playwright' | 'pdf_only' | 'failed'
    """
    from pipeline.fetch_content import download_page, sanitize_html

    result = download_page(url, retries=2)
    if result.get('html') and not result.get('error'):
        return {
            'html': sanitize_html(result['html']),
            'source': 'http',
            'pdf_path': None,
            'error': None,
        }

    pw_result = capture_page_playwright(url, article_id)
    if pw_result.get('html'):
        return {
            'html': _sanitize_html(pw_result['html']),
            'source': 'playwright',
            'pdf_path': pw_result.get('pdf_path'),
            'error': None,
        }

    if pw_result.get('pdf_path') and os.path.isfile(pw_result['pdf_path']):
        return {
            'html': '',
            'source': 'pdf_only',
            'pdf_path': pw_result['pdf_path'],
            'error': 'Only PDF captured',
        }

    return {
        'html': '',
        'source': 'failed',
        'pdf_path': None,
        'error': pw_result.get('error') or result.get('error') or 'All capture methods failed',
    }


def cache_article_html(article_id: int, html: str) -> dict:
    """缓存 HTML 到磁盘 + 更新 DB，与 fetch_content 一致的写入逻辑。"""
    from utils.text import extract_text_from_html, detect_language
    import sqlite3 as _sqlite3

    html = _sanitize_html(html)

    content_dir = config.content_cache_path
    os.makedirs(content_dir, exist_ok=True)
    file_path = os.path.join(content_dir, f'{article_id}.html')
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html)

    text = extract_text_from_html(html)
    lang = detect_language(text)
    now = datetime.now().isoformat(timespec='seconds')
    rel_path = f'{os.path.basename(content_dir)}/{article_id}.html'

    conn = _sqlite3.connect(config.db_path)
    conn.execute("""
        UPDATE articles SET local_path=?, content_fetched_at=?,
            text_content=?, content_lang=?, content_status='fetched'
        WHERE id=?
    """, (rel_path, now, text, lang, article_id))
    conn.commit()
    conn.close()

    return {'ok': True, 'local_path': rel_path}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='浏览器级页面捕获')
    parser.add_argument('--article-id', type=int, help='单篇文章 ID')
    parser.add_argument('--limit', type=int, default=10, help='批量抓取上限')
    args = parser.parse_args()

    conn = sqlite3.connect(config.db_path)

    if args.article_id:
        rows = conn.execute(
            "SELECT id, url FROM articles WHERE id=?", (args.article_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, url FROM articles WHERE (local_path IS NULL OR local_path = '') AND url LIKE 'http%' LIMIT ?",
            (args.limit,)
        ).fetchall()
    conn.close()

    success = 0
    for aid, url in rows:
        print(f'[{aid}] {url[:60]}...', end=' ', flush=True)
        result = fetch_with_fallback(url, aid)
        if result['html']:
            cache_article_html(aid, result['html'])
            print(f'✓ {result["source"]}')
            success += 1
        else:
            extra = f' (PDF: {result["pdf_path"]})' if result['pdf_path'] else ''
            print(f'✗ {result["error"]}{extra}')

    print(f'\n完成: {success}/{len(rows)}')
