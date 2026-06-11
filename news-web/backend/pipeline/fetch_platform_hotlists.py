#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
平台热搜 / 热门视频采集 — 直连各平台官方 API，不依赖第三方聚合服务。

采集平台：
  微博热搜  — https://weibo.com/ajax/side/hotSearch       (免登录, ~50 条)
  知乎热榜  — https://www.zhihu.com/api/v3/feed/topstory/hot-list-web  (~30 条)
  抖音热榜  — https://www.douyin.com/aweme/v1/web/hot/search/list/     (~30 条)
  头条热榜  — https://www.toutiao.com/hot-event/hot-board/             (~50 条)
  B站热门   — https://api.bilibili.com/x/web-interface/popular        (可翻页)

输出：
  hot_reports/daily_report_{date}.json   — 全平台数据
  hot_reports/dailyhot_api_{date}.json   — 兼容子集（无头条，匹配 collect_data.py 解析逻辑）
"""
import sys, os, json, time, urllib.request, urllib.error, re
from datetime import datetime

# 确保 Windows 控制台输出 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(SCRIPT_DIR, 'hot_reports')

TIMEOUT = 10  # 单次请求超时秒数
DELAY = 0.5   # 请求间延迟（礼貌间隔）

HEADERS = {
    'User-Agent': os.environ.get(
        'USER_AGENT',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

BILIBILI_MAX_PAGES = int(os.environ.get('BILIBILI_MAX_PAGES', '7'))


def _fetch_json(url: str, extra_headers: dict = None, timeout: int = TIMEOUT) -> dict:
    """通用 JSON 请求。返回解析后的 dict，失败返回 {}。"""
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════
# 微博热搜
# ══════════════════════════════════════════════════════════════

def fetch_weibo() -> list:
    """获取微博热搜榜。免登录即可获取 ~50 条。"""
    data = _fetch_json('https://weibo.com/ajax/side/hotSearch',
                       extra_headers={'Referer': 'https://weibo.com/hot'})
    items = data.get('data', {}).get('realtime', [])
    results = []
    for item in items:
        word = item.get('word', '') or item.get('note', '')
        if not word:
            continue
        # word_scheme 是带 # 的话题链接路径，优先用它构造 URL
        scheme = item.get('word_scheme', '')
        url = ''
        if scheme:
            # word_scheme 通常形如 "#话题#" 或直接是路径片段
            clean = scheme.strip('#')
            url = f'https://s.weibo.com/weibo?q=%23{clean}%23'
        results.append({
            'title': word.strip('#'),
            'url': url,
            'rank': item.get('rank', item.get('realpos', 0)),
            'value_text': str(item.get('num', '')),
            'metadata': {
                'category': item.get('category', ''),
                'onboard_time': item.get('onboard_time', ''),
            }
        })
    return results


# ══════════════════════════════════════════════════════════════
# 知乎热榜
# ══════════════════════════════════════════════════════════════

def fetch_zhihu() -> list:
    """获取知乎热榜。limit=50 获取当前全量热榜。"""
    data = _fetch_json(
        'https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=50&desktop=true',
        extra_headers={'Referer': 'https://www.zhihu.com/hot'}
    )
    items = data.get('data', [])
    results = []
    for rank, item in enumerate(items, 1):
        target = item.get('target', {})
        title = (target.get('title_area', {}).get('text', '') or
                 target.get('title', ''))
        if not title:
            continue
        url = target.get('link', {}).get('url', '')
        if url and not url.startswith('http'):
            url = 'https://www.zhihu.com' + url
        # 热度用回答数表示（zhihu 热榜无直接热度值）
        answer_count = item.get('feed_specific', {}).get('answer_count', 0)
        metrics = target.get('metrics_area', {}).get('text', '')
        # 提取摘要文本（知乎 API 返回的 excerpt 含丰富正文内容）
        excerpt = target.get('excerpt_area', {}).get('text', '')
        results.append({
            'title': title,
            'url': url,
            'rank': rank,
            'value_text': str(answer_count) if answer_count else metrics,
            'metadata': {
                'answer_count': answer_count,
                'excerpt': excerpt[:500] if excerpt else '',
            }
        })
    return results


# ══════════════════════════════════════════════════════════════
# 抖音热榜
# ══════════════════════════════════════════════════════════════

def fetch_douyin() -> list:
    """获取抖音热榜。trending_list 返回实时上升热点。"""
    data = _fetch_json(
        'https://www.douyin.com/aweme/v1/web/hot/search/list/?detail_list=1&count=50',
        extra_headers={
            'Referer': 'https://www.douyin.com/hot',
            'Cookie': 'msToken=placeholder',  # 抖音要求有 cookie 占位
        }
    )
    items = data.get('data', {}).get('trending_list', [])
    results = []
    for rank, item in enumerate(items, 1):
        word = item.get('word', '')
        if not word:
            continue
        group_id = item.get('group_id', '')
        url = f'https://www.douyin.com/search/{word}' if word else ''
        results.append({
            'title': word,
            'url': url,
            'rank': rank,
            'value_text': str(item.get('hot_value', '')),
            'metadata': {
                'video_count': item.get('video_count', 0),
                'group_id': group_id,
            }
        })
    return results


# ══════════════════════════════════════════════════════════════
# 今日头条热榜
# ══════════════════════════════════════════════════════════════

def fetch_toutiao() -> list:
    """获取今日头条热榜。免登录直接返回 JSON。"""
    data = _fetch_json(
        'https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc',
        extra_headers={'Referer': 'https://www.toutiao.com/hotnews/'}
    )
    items = data.get('data', [])
    results = []
    for rank, item in enumerate(items, 1):
        title = item.get('Title', '')
        if not title:
            continue
        url = item.get('Url', '')
        results.append({
            'title': title,
            'url': url,
            'rank': rank,
            'value_text': str(item.get('HotValue', '')),
        })
    return results


# ══════════════════════════════════════════════════════════════
# B站热门视频
# ══════════════════════════════════════════════════════════════

def fetch_bilibili(max_pages: int = BILIBILI_MAX_PAGES) -> list:
    """获取 B站 热门视频。分页拉取，每页最多 50 条。"""
    results = []
    rank_offset = 0

    for pn in range(1, max_pages + 1):
        data = _fetch_json(
            f'https://api.bilibili.com/x/web-interface/popular?pn={pn}&ps=50',
            extra_headers={'Referer': 'https://www.bilibili.com/'}
        )
        if data.get('code') != 0:
            # code=-352 风控: 等待后重试，最多 3 次
            if data.get('code') == -352:
                for retry in range(3):
                    time.sleep(5)
                    data = _fetch_json(
                        f'https://api.bilibili.com/x/web-interface/popular?pn={pn}&ps=50',
                        extra_headers={'Referer': 'https://www.bilibili.com/'}
                    )
                    if data.get('code') == 0:
                        break
                else:
                    break  # 重试耗尽
            else:
                break

        videos = data.get('data', {}).get('list', [])
        for video in videos:
            rank_offset += 1
            bvid = video.get('bvid', '')
            title = video.get('title', '')
            if not title:
                continue
            url = f'https://www.bilibili.com/video/{bvid}' if bvid else ''
            stat = video.get('stat', {})
            owner = video.get('owner', {})
            results.append({
                'title': title,
                'url': url,
                'rank': rank_offset,
                'value_text': str(stat.get('view', '')),
                'author': owner.get('name', ''),
                'metadata': {
                    'bvid': bvid,
                    'danmaku': stat.get('danmaku', 0),
                    'like': stat.get('like', 0),
                    'favorite': stat.get('favorite', 0),
                    'pubdate': video.get('pubdate', ''),
                }
            })

        if data.get('data', {}).get('no_more', False):
            break

        time.sleep(DELAY)

    return results


# ══════════════════════════════════════════════════════════════
# 主逻辑
# ══════════════════════════════════════════════════════════════

PLATFORMS = [
    ('微博热搜', 'weibo', fetch_weibo),
    ('知乎热榜', 'zhihu', fetch_zhihu),
    ('抖音热榜', 'douyin', fetch_douyin),
    ('头条热榜', 'toutiao', fetch_toutiao),
    ('B站热门', 'bilibili', fetch_bilibili),
]


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    date_tag = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    all_data = {}
    sources_summary = {}

    for label, pid, fetcher in PLATFORMS:
        print(f"📡 采集 {label}...", end=" ", flush=True)
        try:
            items = fetcher()
            all_data[pid] = items
            sources_summary[pid] = len(items)
            print(f"✅ {len(items)} 条")
        except Exception as e:
            all_data[pid] = []
            sources_summary[pid] = 0
            print(f"❌ 失败: {e}")
        time.sleep(DELAY)

    # ── 输出 daily_report_{date}.json (全平台) ──
    report_file = os.path.join(REPORTS_DIR, f'daily_report_{date_tag}.json')
    report = {
        'date': timestamp,
        'sources': sources_summary,
        'data': all_data,
    }
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 全平台报告: {report_file}")

    # ── 输出 dailyhot_api_{date}.json (兼容子集，不含 toutiao) ──
    # collect_data.py 的 dailyhot_api_ 解析器只检查 zhihu / weibo / douyin / bilibili
    dailyhot_data = {
        k: v for k, v in all_data.items()
        if k in ('zhihu', 'weibo', 'douyin', 'bilibili')
    }
    api_file = os.path.join(REPORTS_DIR, f'dailyhot_api_{date_tag}.json')
    api_report = {
        'date': timestamp,
        'data': dailyhot_data,
    }
    with open(api_file, 'w', encoding='utf-8') as f:
        json.dump(api_report, f, ensure_ascii=False, indent=2)
    print(f"📄 兼容报告: {api_file}")

    # ── 摘要 ──
    total = sum(sources_summary.values())
    print(f"\n🏷️  总计 {total} 条:")
    for pid, count in sources_summary.items():
        print(f"   {pid}: {count} 条")
    return all_data


if __name__ == '__main__':
    main()
