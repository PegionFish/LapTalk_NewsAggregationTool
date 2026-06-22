#!/usr/bin/env python3
"""
Final recovery: HTTP retry WITHOUT proxy (proxy is broken).
403/405 → Playwright. Timeout/SSL/Incomplete → HTTP retry. 404 → skip.
"""
import os, sys, sqlite3, time, urllib.request, urllib.error, re, socket
from datetime import datetime

try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import config
from utils.text import extract_text_from_html, detect_language

# NO proxy - it's broken for HTTPS
socket.setdefaulttimeout(15)

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
CACHE = config.content_cache_path


def dl(url):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            ct = r.headers.get('Content-Type', '')
            cs = 'utf-8'
            if 'charset=' in ct:
                cs = ct.split('charset=')[-1].split(';')[0].strip()
            try: html = raw.decode(cs, errors='replace')
            except: html = raw.decode('utf-8', errors='replace')
        return html, None
    except urllib.error.HTTPError as e:
        return '', f'HTTP {e.code}'
    except Exception as e:
        return '', str(e)[:150]


def sanitize(h):
    h = re.sub(r'<script[\s\S]*?</script>', '', h, flags=re.IGNORECASE)
    h = re.sub(r'<noscript[\s\S]*?</noscript>', '', h, flags=re.IGNORECASE)
    h = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', '', h, flags=re.IGNORECASE)
    h = re.sub(r'<iframe[\s\S]*?</iframe>', '', h, flags=re.IGNORECASE)
    return h


def save(aid, html):
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, f'{aid}.html')
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(html)
    text = extract_text_from_html(html)
    lang = detect_language(text)
    now = datetime.now().isoformat(timespec='seconds')
    rel = f'{os.path.basename(CACHE)}/{aid}.html'
    conn = sqlite3.connect(config.db_path)
    conn.execute("""UPDATE articles SET local_path=?,content_fetched_at=?,
        text_content=?,content_lang=?,content_status='fetched' WHERE id=?""",
                 (rel, now, text, lang, aid))
    conn.commit(); conn.close()
    return lang, len(html)


def fail(aid, err):
    conn = sqlite3.connect(config.db_path)
    conn.execute("UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                 (f'[ERR:{err}]', datetime.now().isoformat(timespec='seconds'), aid))
    conn.commit(); conn.close()


# ══════════════════════════════════════════════════════════════

conn = sqlite3.connect(config.db_path)
rows = conn.execute("""
    SELECT id, title, url, source, local_path FROM articles
    WHERE local_path LIKE '[ERR:%'
      AND category NOT IN ('platform_hotlists', 'bilibili_videos')
    ORDER BY local_path, id
""").fetchall()
conn.close()

arts = [{'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
         'err': r[4].replace('[ERR:', '').rstrip(']')} for r in rows]

http_retry = [a for a in arts if not ('403' in a['err'] or '405' in a['err'] or '404' in a['err'])]
pw_needed = [a for a in arts if '403' in a['err'] or '405' in a['err']]
dead = [a for a in arts if '404' in a['err']]

total = len(arts)
print(f"Total: {total} | HTTP: {len(http_retry)} | PW: {len(pw_needed)} | Dead: {len(dead)}")
sys.stdout.flush()

# ── Phase 1: HTTP retry (fast, 0.3s delay) ──
ok = 0
for idx, a in enumerate(http_retry, 1):
    print(f"  [{idx:3d}/{len(http_retry)}] #{a['id']} [{a['source'][:15]}] {a['title'][:45]} ",
          end="", flush=True)
    html, err = dl(a['url'])
    if err:
        fail(a['id'], err)
        print(f"FAIL: {err[:45]}")
    elif len(html) < 200:
        fail(a['id'], 'empty')
        print("FAIL: empty")
    else:
        html = sanitize(html)
        try:
            lang, sz = save(a['id'], html)
            print(f"OK {sz//1024}KB [{lang}]")
            ok += 1
        except Exception as e:
            fail(a['id'], str(e)[:200])
            print(f"FAIL: {str(e)[:45]}")
    sys.stdout.flush()
    time.sleep(0.3)

print(f"\nHTTP: {ok}/{len(http_retry)} recovered\n")
sys.stdout.flush()

# ── Phase 2: Playwright for 403/405 ──
if pw_needed:
    try:
        from pipeline.browser_capture import capture_page_playwright, _sanitize_html as _ps
        PW_OK = True
        print(f"Playwright ready. Processing {len(pw_needed)} articles...")
    except Exception as e:
        PW_OK = False
        print(f"Playwright not available: {e}")

    if PW_OK:
        pw_ok = 0
        for idx, a in enumerate(pw_needed, 1):
            print(f"  [{idx:3d}/{len(pw_needed)}] #{a['id']} [{a['source'][:15]}] {a['title'][:45]} ",
                  end="", flush=True)
            try:
                r = capture_page_playwright(a['url'], a['id'])
                if r.get('html') and not r.get('challenge', {}).get('is_challenge') and len(r['html']) > 200:
                    html = _ps(r['html'])
                    lang, sz = save(a['id'], html)
                    print(f"OK {sz//1024}KB [{lang}]")
                    pw_ok += 1
                else:
                    err = r.get('error') or r.get('challenge', {}).get('reason', 'pw_fail')
                    fail(a['id'], err)
                    print(f"FAIL: {err[:45]}")
            except Exception as e:
                fail(a['id'], str(e)[:200])
                print(f"CRASH: {str(e)[:45]}")
            sys.stdout.flush()
            time.sleep(2)
        print(f"\nPW: {pw_ok}/{len(pw_needed)} recovered")

# Final
conn = sqlite3.connect(config.db_path)
rem = conn.execute("SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%'").fetchone()[0]
conn.close()
print(f"\nDONE. {total} originally, {rem} remaining failed.")
