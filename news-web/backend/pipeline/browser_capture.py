#!/usr/bin/env python3
"""
浏览器级页面捕获 — Playwright 渲染 JS 页面。
当 HTTP 请求被反爬/验证码拦截时自动降级到 headless Chromium，
使用客户端真实浏览器指纹隐身，并检测 CAPTCHA/挑战页。

用法:
  python3 browser_capture.py --article-id 42
  python3 browser_capture.py --limit 10
"""

import os, sys, sqlite3, re, json, logging
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config

logger = logging.getLogger(__name__)

TIMEOUT = 60000
STEALTH_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-infobars',
    '--disable-dev-shm-usage',       # 容器/低内存环境兼容
    '--disable-features=TranslateUI,BackForwardCache',
    '--disable-component-extensions-with-background-pages',
]
# 注意：移除了 --disable-web-security（反爬红旗）和 --disable-automation（由 playwright-stealth 接管）

# ── 人机验证/反爬检测关键词 ─────────────────────────────
CHALLENGE_PATTERNS = [
    'verify you are human',
    'please verify',
    'verify your identity',
    'captcha',
    'cf-challenge',
    'cf-browser-verification',
    'challenge-platform',
    'unable to load',
    'access denied',
    'please enable javascript',
    'cookies are required',
    'just a moment',
    'checking your browser',
    'DDoS protection',
    '_cf_chl_opt',
    'Turnstile',
    'hCaptcha',
    'recaptcha',
    'g-recaptcha',
    'cf-turnstile',
    'robot',
    'are you a human',
]


def _sanitize_html(html: str) -> str:
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<noscript[\s\S]*?</noscript>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*'[^']*'", '', html, flags=re.IGNORECASE)
    html = re.sub(r'<iframe[\s\S]*?</iframe>', '', html, flags=re.IGNORECASE)
    return html


def detect_challenge(html: str, url: str = '') -> dict:
    """检测页面是否为反爬/验证码挑战页。

    Returns:
        {'is_challenge': bool, 'type': str|None, 'reason': str|None}
        type: 'cloudflare' | 'captcha' | 'access_denied' | 'jstest' | None
    """
    if not html or len(html) < 200:
        return {'is_challenge': False, 'type': None, 'reason': 'empty_or_too_small'}

    html_lower = html.lower()
    text = re.sub(r'<[^>]+>', ' ', html_lower)
    text = re.sub(r'\s+', ' ', text).strip()

    matched = []
    for pattern in CHALLENGE_PATTERNS:
        if pattern in text or pattern in html_lower:
            matched.append(pattern)

    if not matched:
        return {'is_challenge': False, 'type': None, 'reason': None}

    # 按类型归类
    if any(k in html_lower for k in ['cf-challenge', 'cf-browser-verification', '_cf_chl_opt', 'cf-turnstile']):
        return {'is_challenge': True, 'type': 'cloudflare', 'reason': 'Cloudflare 挑战页'}
    if any(k in text for k in ['captcha', 'recaptcha', 'hcaptcha', 'g-recaptcha', 'turnstile']):
        return {'is_challenge': True, 'type': 'captcha', 'reason': '人机验证 (CAPTCHA)'}
    if any(k in text for k in ['access denied', 'unable to load', 'please enable javascript']):
        return {'is_challenge': True, 'type': 'access_denied', 'reason': '访问被拒绝'}
    if any(k in text for k in ['just a moment', 'checking your browser', 'ddos protection']):
        return {'is_challenge': True, 'type': 'jstest', 'reason': 'JS 浏览器检查'}

    return {'is_challenge': True, 'type': 'unknown', 'reason': f'检测到挑战关键词: {matched[:3]}'}


def _get_proxy_config() -> dict | None:
    """从全局配置读取代理设置，返回 Playwright 兼容格式。"""
    if not config.proxy_enabled or not config.proxy_url:
        return None
    url = config.proxy_url.strip()
    if url.startswith('socks'):
        url = url.replace('socks5://', 'http://').replace('socks5h://', 'http://')
    return {'server': url}


def capture_page_playwright(url: str, article_id: int = 0) -> dict:
    """Playwright 渲染页面 — 使用客户端真实指纹隐身。

    Returns:
        {'html': str, 'pdf_path': str|None, 'error': str|None, 'challenge': dict}
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'html': '', 'pdf_path': None, 'error': 'Playwright not installed', 'challenge': {}}

    # 加载客户端指纹
    from fingerprint_store import load_fingerprint, build_playwright_config
    fp = load_fingerprint()
    pw_config = build_playwright_config(fp)

    html = ''
    pdf_path = None
    error = None
    challenge = {}

    try:
        with sync_playwright() as p:
            launch_kwargs = {'headless': True, 'args': STEALTH_ARGS}
            proxy_cfg = _get_proxy_config()
            if proxy_cfg:
                launch_kwargs['proxy'] = proxy_cfg
                logger.info(f"[browser_capture] Playwright 使用代理: {proxy_cfg['server']}")

            browser = p.chromium.launch(**launch_kwargs)

            context_kwargs = {
                'user_agent': pw_config.get('user_agent') or (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/150.0.0.0 Safari/537.36'
                ),
                'viewport': pw_config.get('viewport', {'width': 1920, 'height': 1080}),
                'locale': pw_config.get('locale', 'zh-CN'),
                'timezone_id': pw_config.get('timezone_id', 'Asia/Shanghai'),
            }
            context = browser.new_context(**context_kwargs)

            # 集成 playwright-stealth（自动 patch webdriver/plugins/WebGL/navigator 等）
            page = context.new_page()
            try:
                from playwright_stealth import Stealth
                stealth = Stealth(
                    navigator_webdriver=True,
                    navigator_plugins=True,
                    navigator_languages=True,
                    navigator_platform=True,
                    webgl_vendor=True,
                    chrome_runtime=True,
                    navigator_permissions=True,
                    sec_ch_ua=True,
                )
                stealth.apply_stealth_sync(page)
                logger.debug("[browser_capture] playwright-stealth 已激活")
            except ImportError:
                # 兜底隐身脚本 — 修复 plugins 为真实 Plugin 结构
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    // 真实 Plugin 对象而非假数组
                    const makePlugin = (name, desc, file) => ({
                        name, description: desc, filename: file, length: 1,
                        item: () => null, namedItem: () => null,
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => {
                            const arr = [
                                makePlugin('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer'),
                                makePlugin('Chrome PDF Viewer', '', 'mhjfbmdgcfjbbpaeojofohoefgiehjai'),
                                makePlugin('Native Client', '', 'internal-nacl-plugin'),
                            ];
                            arr.item = (i) => arr[i] || null;
                            arr.namedItem = (n) => arr.find(p => p.name === n) || null;
                            arr.refresh = () => {};
                            Object.setPrototypeOf(arr, PluginArray.prototype);
                            return arr;
                        }
                    });
                    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
                    // WebGL 伪装
                    try {
                        const getParam = WebGLRenderingContext.prototype.getParameter;
                        WebGLRenderingContext.prototype.getParameter = function(p) {
                            if (p === 37445) return 'Intel Inc.';    // UNMASKED_VENDOR_WEBGL
                            if (p === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
                            return getParam.call(this, p);
                        };
                    } catch(e) {}
                """)

            # 自定义指纹脚本（叠加在 stealth 之上）
            stealth = pw_config.get('stealth_script', '')
            if stealth:
                page.add_init_script(stealth)

            try:
                page.goto(url, wait_until='networkidle', timeout=TIMEOUT)
                page.wait_for_timeout(3000)
                html = page.content()

                # 检测是否挑战页
                challenge = detect_challenge(html, url)

                if article_id and not challenge.get('is_challenge'):
                    cache_dir = config.content_cache_path
                    os.makedirs(cache_dir, exist_ok=True)
                    pdf_path = os.path.join(cache_dir, f'{article_id}.pdf')
                    page.pdf(path=pdf_path, format='A4', print_background=True)
            except Exception as e:
                error = str(e)[:300]
                try:
                    html = page.content()
                    if not challenge:
                        challenge = detect_challenge(html, url)
                except Exception:
                    pass
            finally:
                context.close()
                browser.close()
    except Exception as e:
        error = str(e)[:300]

    return {
        'html': html,
        'pdf_path': pdf_path,
        'error': error,
        'challenge': challenge,
    }


def fetch_with_fallback(url: str, article_id: int = 0) -> dict:
    """三级回退抓取：HTTP → Playwright（含指纹隐身）→ 等待用户验证。

    Returns:
        {'html': str, 'source': str, 'pdf_path': str|None,
         'error': str|None, 'challenge': dict}
        source: 'http' | 'playwright' | 'challenge' | 'failed'
        当检测到挑战页时，html 仍为挑战页内容（供上层判断），source='challenge'
    """
    from pipeline.fetch_content import download_page, sanitize_html

    # 1. HTTP 下载
    result = download_page(url, retries=2)
    if result.get('html') and not result.get('error'):
        html = sanitize_html(result['html'])
        chal = detect_challenge(html, url)
        if chal.get('is_challenge'):
            return {
                'html': html,
                'source': 'challenge',
                'pdf_path': None,
                'error': chal.get('reason', 'HTTP returned challenge page'),
                'challenge': chal,
            }
        return {
            'html': html,
            'source': 'http',
            'pdf_path': None,
            'error': None,
            'challenge': {},
        }

    # 2. Playwright 渲染（带客户端真实指纹）
    pw_result = capture_page_playwright(url, article_id)
    if pw_result.get('html'):
        html = _sanitize_html(pw_result['html'])
        challenge = pw_result.get('challenge', {})
        if challenge.get('is_challenge'):
            return {
                'html': html,
                'source': 'challenge',
                'pdf_path': pw_result.get('pdf_path'),
                'error': challenge.get('reason', 'Playwright hit challenge'),
                'challenge': challenge,
            }
        return {
            'html': html,
            'source': 'playwright',
            'pdf_path': pw_result.get('pdf_path'),
            'error': None,
            'challenge': {},
        }

    # 3. 只有 PDF（备用）
    if pw_result.get('pdf_path') and os.path.isfile(pw_result['pdf_path']):
        return {
            'html': '',
            'source': 'pdf_only',
            'pdf_path': pw_result['pdf_path'],
            'error': 'Only PDF captured',
            'challenge': {},
        }

    # 4. 全部失败
    return {
        'html': '',
        'source': 'failed',
        'pdf_path': None,
        'error': pw_result.get('error') or result.get('error') or 'All capture methods failed',
        'challenge': pw_result.get('challenge', {}),
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


def retry_playwright(article_id: int, url: str) -> dict:
    """用户标记已通过验证后，重新用 Playwright 获取。"""
    result = capture_page_playwright(url, article_id)
    if result.get('html') and not result.get('challenge', {}).get('is_challenge'):
        cache_article_html(article_id, _sanitize_html(result['html']))
        return {'ok': True, 'source': result.get('source', 'playwright'), 'error': None}
    if result.get('challenge', {}).get('is_challenge'):
        return {'ok': False, 'error': result['challenge'].get('reason', 'Still challenged'), 'challenge': result['challenge']}
    return {'ok': False, 'error': result.get('error', 'Unknown error')}


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
    challenged = 0
    for aid, url in rows:
        print(f'[{aid}] {url[:60]}...', end=' ', flush=True)
        result = fetch_with_fallback(url, aid)
        if result['html'] and result['source'] != 'challenge':
            cache_article_html(aid, result['html'])
            print(f'✓ {result["source"]}')
            success += 1
        elif result['source'] == 'challenge':
            print(f'⚠ {result["error"]}')
            challenged += 1
        else:
            extra = f' (PDF: {result["pdf_path"]})' if result['pdf_path'] else ''
            print(f'✗ {result["error"]}{extra}')

    print(f'\n完成: {success}/{len(rows)}, 需验证: {challenged}')
