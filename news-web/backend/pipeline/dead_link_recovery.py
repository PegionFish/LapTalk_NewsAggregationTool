#!/usr/bin/env python3
"""
死链 URL 自动恢复 — 通过 DuckDuckGo 搜索标题+来源，查找文章的新 URL。

当文章下载返回 404/410 时，标题和来源仍然有效。通过搜索引擎查找同一篇文章
是否被移动到新 URL（网站改版/URL slug 变化）。

用法:
  python3 dead_link_recovery.py              # 处理所有 404/410 文章
  python3 dead_link_recovery.py --id 2694    # 处理指定文章
  python3 dead_link_recovery.py --limit 10   # 最多处理 10 篇
"""

import os, sys, re, time, sqlite3, logging
from datetime import datetime
from urllib.parse import urlparse, urlunparse, unquote

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from config import config
from utils.proxy import get_httpx_proxy

logger = logging.getLogger(__name__)

# ── DuckDuckGo HTML 搜索 ──────────────────────────────────
SEARCH_URL = 'https://html.duckduckgo.com/html/'
SEARCH_TIMEOUT = 15
SEARCH_DELAY = (4, 8)  # 每次搜索间隔秒数范围
HEAD_TIMEOUT = 10

# 已安装，供外部量测
try:
    import bs4
    _BS4_OK = True
except ImportError:
    _BS4_OK = False


def _get_proxy() -> dict | None:
    """获取 requests 格式的代理配置。"""
    proxy_url = get_httpx_proxy()
    if proxy_url:
        # httpx proxy URL -> requests proxies dict
        return {'http': proxy_url, 'https': proxy_url}
    # 尝试从 config 直接获取
    if config.proxy_enabled and config.proxy_url:
        return {'http': config.proxy_url, 'https': config.proxy_url}
    return None


def _source_domain(source_name: str, old_url: str = '') -> str:
    """从来源名推断搜索域名。内置常见来源映射。"""
    DOMAIN_MAP = {
        '9to5Mac': '9to5mac.com',
        '9to5Google': '9to5google.com',
        '9to5Toys': '9to5toys.com',
        'TechCrunch': 'techcrunch.com',
        'The Verge': 'theverge.com',
        'Ars Technica': 'arstechnica.com',
        'Wired': 'wired.com',
        'CNET': 'cnet.com',
        'Gizmodo': 'gizmodo.com',
        'Eurogamer': 'eurogamer.net',
        'GameSpot': 'gamespot.com',
        'PC Gamer': 'pcgamer.com',
        "Tom's Hardware": 'tomshardware.com',
        'Guru3D': 'guru3d.com',
        'TechPowerUp': 'techpowerup.com',
        'Digital Trends': 'digitaltrends.com',
        'VentureBeat': 'venturebeat.com',
        'MacRumors': 'macrumors.com',
        'The Decoder': 'the-decoder.com',
        'MarkTechPost': 'marktechpost.com',
        'Windows Central': 'windowscentral.com',
        'Android Central': 'androidcentral.com',
        'AnandTech': 'anandtech.com',
        'The Register': 'theregister.com',
        'Engadget': 'engadget.com',
        'TweakTown': 'tweaktown.com',
        'Phoronix': 'phoronix.com',
        'HPCwire': 'hpcwire.com',
        'Neowin': 'neowin.net',
    }
    if source_name in DOMAIN_MAP:
        return DOMAIN_MAP[source_name]
    # 从 old_url 提取
    if old_url:
        try:
            return urlparse(old_url).netloc.replace('www.', '')
        except Exception:
            pass
    return ''


def search_article(title: str, source: str, old_url: str = '', max_results: int = 4) -> list[dict]:
    """搜索文章的新 URL。

    Returns:
        [{'url': str, 'title': str, 'snippet': str, 'is_exact': bool}, ...]
        按相关性排序，is_exact 表示 URL slug 与原标题高度匹配。
    """
    domain = _source_domain(source, old_url)

    # 搜索词：来源名 + 标题前 10 个词（太长会降低匹配精度）
    short_title = ' '.join(title.split()[:10])
    query = f'{domain} {short_title}' if domain else f'{source} {short_title}'

    proxies = _get_proxy()
    results = []

    try:
        resp = requests.get(
            SEARCH_URL,
            params={'q': query},
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            },
            proxies=proxies,
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(f"[dead_link_recovery] 搜索返回 {resp.status_code}")
            return results

        soup = BeautifulSoup(resp.text, 'html.parser')

        for link in soup.select('a.result__a'):
            href = link.get('href', '')
            # DuckDuckGo 使用 uddg 参数包装真实 URL
            if 'uddg=' in href:
                href = unquote(href.split('uddg=')[-1].split('&')[0])

            # 跳过广告和无关链接
            if not href.startswith('http') or 'ad_domain' in href or 'y.js' in href:
                continue

            # 跳过非目标域的结果（除非无法确定域）
            if domain and domain not in href:
                continue

            title_text = link.get_text(strip=True)
            if not title_text:
                continue

            # 提取摘要
            parent = link.find_parent(class_=['result', 'web-result'])
            snippet = ''
            if parent:
                desc_el = parent.select_one('.result__snippet')
                if desc_el:
                    snippet = desc_el.get_text(strip=True)

            # 判断是否为精确匹配：URL 中包含原标题的关键词
            title_words = set(title.lower().split()[:6])
            url_words = set(href.lower().replace('-', ' ').replace('/', ' ').split())
            overlap = len(title_words & url_words)
            is_exact = overlap >= 3

            results.append({
                'url': href,
                'title': title_text[:200],
                'snippet': snippet[:200],
                'is_exact': is_exact,
                'overlap': overlap,
            })

            if len(results) >= max_results:
                break

    except requests.RequestException as e:
        logger.warning(f"[dead_link_recovery] 搜索失败: {e}")
    except Exception as e:
        logger.error(f"[dead_link_recovery] 搜索解析异常: {e}")

    # 排序：精确匹配在前
    results.sort(key=lambda r: (r['is_exact'], r['overlap']), reverse=True)
    return results


def verify_url(url: str) -> tuple[bool, str]:
    """HEAD 请求验证 URL 是否可用。

    Returns:
        (is_valid, error_msg)
    """
    proxies = _get_proxy()
    try:
        resp = requests.head(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 Chrome/150.0.0.0',
                'Accept': 'text/html,application/xhtml+xml',
            },
            proxies=proxies,
            timeout=HEAD_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code < 400:
            return True, ''
        return False, f'HTTP {resp.status_code}'
    except requests.RequestException as e:
        return False, str(e)[:100]


def recover_article(article_id: int, db_path: str = None) -> dict:
    """尝试恢复一篇死链文章。

    Returns:
        {'status': 'recovered'|'not_found'|'error', 'new_url': str|None, 'message': str}
    """
    if not db_path:
        db_path = config.db_path

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id, title, source, url, local_path FROM news_articles WHERE id=?",
        (article_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {'status': 'error', 'new_url': None, 'message': '文章不存在'}

    aid, title, source, old_url, local_path = row

    # 检查是否为死链
    err = (local_path or '').replace('[ERR:', '').rstrip(']')
    if 'HTTP 404' not in err and 'HTTP 410' not in err:
        conn.close()
        return {'status': 'error', 'new_url': None, 'message': f'非死链文章: {err}'}

    # 搜索候选 URL
    candidates = search_article(title, source, old_url)

    if not candidates:
        conn.close()
        return {'status': 'not_found', 'new_url': None, 'message': '搜索无结果'}

    # 验证候选 URL
    for c in candidates:
        if c['url'] == old_url:
            continue  # 跳过原 URL

        valid, err_msg = verify_url(c['url'])
        if valid:
            # 更新文章 URL，重置缓存状态
            now = datetime.now().isoformat(timespec='seconds')
            conn.execute("""
                UPDATE news_articles SET
                    url=?, local_path=NULL, content_fetched_at=NULL,
                    retry_count=0, content_status='pending'
                WHERE id=?
            """, (c['url'][:500], aid))
            conn.commit()
            conn.close()
            logger.info(f"[dead_link_recovery] #{aid} URL 恢复成功: {c['url'][:100]}")
            return {
                'status': 'recovered',
                'new_url': c['url'],
                'old_url': old_url,
                'message': f'通过搜索找到新 URL: {c["url"][:120]}',
            }

    conn.close()
    return {
        'status': 'not_found',
        'new_url': None,
        'message': f'搜索到 {len(candidates)} 个候选但均不可用',
        'candidates': [c['url'] for c in candidates[:3]],
    }


def batch_recover(article_ids: list[int], progress_callback=None) -> dict:
    """批量恢复死链文章。

    Args:
        article_ids: 文章 ID 列表
        progress_callback: 可选回调 func(current, total, article_id, status, message)

    Returns:
        {'total': int, 'recovered': int, 'not_found': int, 'error': int, 'results': list}
    """
    total = len(article_ids)
    recovered = 0
    not_found = 0
    errors = 0
    results = []

    for i, aid in enumerate(article_ids):
        if progress_callback:
            progress_callback(i + 1, total, aid, 'searching', '')

        r = recover_article(aid)
        results.append({'id': aid, **r})

        if r['status'] == 'recovered':
            recovered += 1
        elif r['status'] == 'not_found':
            not_found += 1
        else:
            errors += 1

        if progress_callback:
            progress_callback(i + 1, total, aid, r['status'], r.get('message', ''))

        # 速率限制
        import random
        time.sleep(random.uniform(*SEARCH_DELAY))

    return {
        'total': total,
        'recovered': recovered,
        'not_found': not_found,
        'error': errors,
        'results': results,
    }


# ── 命令行入口 ──────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='死链 URL 恢复')
    p.add_argument('--id', type=int, help='处理指定文章 ID')
    p.add_argument('--limit', type=int, default=0, help='最多处理篇数')
    p.add_argument('--dry-run', action='store_true', help='只搜索不更新数据库')
    args = p.parse_args()

    db_path = config.db_path
    conn = sqlite3.connect(db_path)

    if args.id:
        rows = conn.execute(
            "SELECT id FROM news_articles WHERE id=?", (args.id,)
        ).fetchall()
    else:
        rows = conn.execute("""
            SELECT id FROM news_articles
            WHERE (local_path LIKE '[ERR:HTTP 404%' OR local_path LIKE '[ERR:HTTP 410%')
            AND content_status != 'dead'
            ORDER BY id
            LIMIT ?
        """, (args.limit or 100,)).fetchall()
    conn.close()

    ids = [r[0] for r in rows]
    print(f"待恢复: {len(ids)} 篇")

    if args.dry_run:
        for aid in ids:
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT title, source, url FROM news_articles WHERE id=?", (aid,)).fetchone()
            conn.close()
            if row:
                candidates = search_article(row[0], row[1], row[2])
                print(f"\n#{aid} {row[0][:60]}")
                for c in candidates:
                    print(f"  {'✅' if c['is_exact'] else '  '} {c['url'][:120]}")
    else:
        def progress(cur, tot, aid, status, msg):
            tag = '✅' if status == 'recovered' else '❌' if status == 'not_found' else '⚠️'
            print(f"  [{cur}/{tot}] #{aid} {tag} {msg[:80]}")

        result = batch_recover(ids, progress_callback=progress)
        print(f"\n完成: 恢复 {result['recovered']}, 未找到 {result['not_found']}, 错误 {result['error']}")
