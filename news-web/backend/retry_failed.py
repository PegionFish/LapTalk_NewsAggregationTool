#!/usr/bin/env python3
"""
Fast recovery: self-contained HTTP retry with 15s timeout + Playwright fallback.
"""
import os, sys, sqlite3, time, urllib.request, urllib.error, re, json, socket
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from datetime import datetime

# Force short socket/DNS timeouts to prevent worker hangs
socket.setdefaulttimeout(15)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from config import config

HTTP_TIMEOUT = 15  # fast timeout per article
WORKERS = 6

UA = config.user_agent


def fast_download(url):
    """Download with short timeout, no retries. Returns (html, error)."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
            ct = resp.headers.get('Content-Type', '')
            cs = 'utf-8'
            if 'charset=' in ct:
                cs = ct.split('charset=')[-1].split(';')[0].strip()
            try:
                html = raw.decode(cs, errors='replace')
            except Exception:
                html = raw.decode('utf-8', errors='replace')
        return html, None
    except urllib.error.HTTPError as e:
        return '', f'HTTP {e.code}'
    except Exception as e:
        return '', str(e)[:200]


def sanitize(html):
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<noscript[\s\S]*?</noscript>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<iframe[\s\S]*?</iframe>', '', html, flags=re.IGNORECASE)
    return html


def save_success(aid, html):
    from utils.text import extract_text_from_html, detect_language
    cache_dir = config.content_cache_path
    os.makedirs(cache_dir, exist_ok=True)
    file_path = os.path.join(cache_dir, f'{aid}.html')
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html)
    text = extract_text_from_html(html)
    lang = detect_language(text)
    now = datetime.now().isoformat(timespec='seconds')
    rel = f'{os.path.basename(cache_dir)}/{aid}.html'
    conn = sqlite3.connect(config.db_path)
    conn.execute("""UPDATE articles SET local_path=?,content_fetched_at=?,text_content=?,content_lang=?,content_status='fetched' WHERE id=?""",
                 (rel, now, text, lang, aid))
    conn.commit()
    conn.close()
    return lang, len(html)


def save_error(aid, err):
    conn = sqlite3.connect(config.db_path)
    conn.execute("UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                 (f'[ERR:{err}]', datetime.now().isoformat(timespec='seconds'), aid))
    conn.commit()
    conn.close()


def http_retry_one(art):
    aid, url = art['id'], art['url']
    if not url or not url.startswith('http'):
        return {'id': aid, 'status': 'nourl'}
    html, err = fast_download(url)
    if err:
        save_error(aid, err)
        return {'id': aid, 'status': 'fail', 'err': err}
    html = sanitize(html)
    if len(html) < 200:
        save_error(aid, 'empty')
        return {'id': aid, 'status': 'fail', 'err': 'empty'}
    try:
        lang, size = save_success(aid, html)
        return {'id': aid, 'status': 'ok', 'lang': lang, 'size': size}
    except Exception as e:
        save_error(aid, str(e)[:200])
        return {'id': aid, 'status': 'fail', 'err': str(e)[:80]}


# ══════════════════════════════════════════════════════════════

def main():
    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("""
        SELECT id, title, url, source, local_path
        FROM articles
        WHERE local_path LIKE '[ERR:%'
          AND category NOT IN ('platform_hotlists', 'bilibili_videos')
        ORDER BY local_path, id
    """).fetchall()
    conn.close()

    articles = [
        {'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
         'error': r[4].replace('[ERR:', '').rstrip(']')}
        for r in rows
    ]

    n404 = [a for a in articles if '404' in a['error']]
    retry = [a for a in articles if '404' not in a['error']]

    total = len(articles)
    print(f"Total failed: {total}")
    print(f"  404 dead links (skip): {len(n404)}")
    print(f"  To retry: {len(retry)} (403={sum(1 for a in retry if '403' in a['error'])}, "
          f"405={sum(1 for a in retry if '405' in a['error'])}, "
          f"timeout={sum(1 for a in retry if 'timed out' in a['error'].lower())}, "
          f"incomplete={sum(1 for a in retry if 'Incomplete' in a['error'])}, "
          f"ssl={sum(1 for a in retry if 'SSL' in a['error'])}, "
          f"other={sum(1 for a in retry if all(k not in a['error'] for k in ['403','405','404','timed out','Incomplete','SSL']))})")
    print(f"  Workers: {WORKERS}, timeout: {HTTP_TIMEOUT}s")
    print()

    if not retry:
        print("Nothing to retry.")
        return

    ok = fail = 0
    print(f"Starting HTTP retry...")
    sys.stdout.flush()

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(http_retry_one, a): a for a in retry}
        for idx, future in enumerate(as_completed(futures), 1):
            try:
                r = future.result(timeout=HTTP_TIMEOUT + 5)
            except FutureTimeout:
                art = futures[future]
                r = {'id': art['id'], 'status': 'fail', 'err': 'worker_timeout'}
            if r['status'] == 'ok':
                ok += 1
                print(f"  [{idx:3d}/{len(retry)}] #{r['id']} OK {r['size']//1024}KB [{r['lang']}]")
            else:
                fail += 1
            if idx % 20 == 0:
                print(f"  [{idx:3d}/{len(retry)}] progress: {ok} ok, {fail} fail")
            sys.stdout.flush()

    print(f"\nHTTP retry done: {ok} ok, {fail} still failed\n")
    sys.stdout.flush()

    # ── Remaining: try Playwright one at a time ──
    conn = sqlite3.connect(config.db_path)
    remaining = conn.execute(
        "SELECT id, title, url, source, local_path FROM articles "
        "WHERE local_path LIKE '[ERR:%' AND category NOT IN ('platform_hotlists', 'bilibili_videos') "
        "AND local_path NOT LIKE '[ERR:HTTP 404%'"
    ).fetchall()
    conn.close()

    if not remaining:
        print("All recovered!")
        return

    rem_arts = [
        {'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
         'error': r[4].replace('[ERR:', '').rstrip(']')}
        for r in remaining
    ]
    print(f"Phase 2: Playwright for {len(rem_arts)} stubborn articles...")
    sys.stdout.flush()

    try:
        from pipeline.browser_capture import capture_page_playwright, _sanitize_html as _pw_san
        PW_OK = True
    except Exception:
        PW_OK = False
        print("Playwright not available, skipping Phase 2")

    pw_ok = 0
    if PW_OK:
        for idx, art in enumerate(rem_arts, 1):
            aid, url = art['id'], art['url']
            print(f"  [{idx:3d}/{len(rem_arts)}] #{aid} [{art['source']}] {art['title'][:45]} ",
                  end="", flush=True)
            try:
                pw = capture_page_playwright(url, aid)
                if pw.get('html') and not pw.get('challenge', {}).get('is_challenge') and len(pw['html']) > 200:
                    html = _pw_san(pw['html'])
                    lang, size = save_success(aid, html)
                    print(f"OK {size//1024}KB [{lang}]")
                    pw_ok += 1
                else:
                    err = pw.get('error') or pw.get('challenge', {}).get('reason', 'pw_failed') or 'pw_empty'
                    save_error(aid, err)
                    print(f"FAIL: {err[:60]}")
            except Exception as e:
                save_error(aid, str(e)[:200])
                print(f"FAIL: {str(e)[:60]}")
            sys.stdout.flush()
            if idx < len(rem_arts):
                time.sleep(2)
        print(f"\nPlaywright result: {pw_ok}/{len(rem_arts)} recovered")

    # Final
    conn = sqlite3.connect(config.db_path)
    still = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%'"
    ).fetchone()[0]
    conn.close()
    print(f"\n=== DONE: {total} originally, {still} remaining ===")


if __name__ == '__main__':
    main()
