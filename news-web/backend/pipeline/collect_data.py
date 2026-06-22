#!/usr/bin/env python3
"""
数据采集整理器 — 只做数据收集和基础去重，不做分析聚类
输出原始数据供 AI 后续分析
"""
import sys, os, json, re, time
from datetime import datetime
from collections import defaultdict

# 确保 Windows 控制台输出 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(SCRIPT_DIR, 'hot_reports')

sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))  # backend/ — news_db 需要导入 utils
sys.path.insert(0, os.path.join(os.path.dirname(SCRIPT_DIR), 'db'))  # 从 db/ 目录导入 news_db
from news_db import NewsDB

# ─── 排除关键词 ──────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    '天气', '气象', '台风', '暴雨', '地震', '预警',
    '明星', '八卦', '塌房', '绯闻', '综艺', '选秀',
    '房价', '楼市', '买房', '清明', '祭祀',
    '补给', '装备补给', '龙威燎天', '抽卡', '晒卡', '十连',
    '个人喜', '公个喜',
    'off', 'deal', 'sale', 'discount', 'coupon', 'promo',
    'buy', 'snag', 'shopping', 'save ',
    '降价', '打折', '优惠', '促销', '秒杀',
    '(PR)', '(pr)',
    '为什么同样是', '如何评价', '什么体验', '怎么看',
    '什么感觉', '算不算',
]

# 已知中文媒体（用于过滤中文媒体的英文文章）
CHINESE_MEDIA = ['钛媒体', '36Kr', '36氪', 'IT之家', '爱范儿', '少数派',
    'Solidot', '机器之心', '雷锋网', '虎嗅', '极客公园',
    '澎湃新闻', '腾讯新闻', '新浪', '网易', '百度',
    '知乎', '微博', '头条', '数字尾巴', '果壳']

def is_garbage(title):
    t = title.lower()
    return any(k.lower() in t for k in EXCLUDE_KEYWORDS)

def is_chinese_media_english(title, source):
    if not any(c in source for c in CHINESE_MEDIA):
        return False
    cjk = sum(1 for c in title if '\u4e00' <= c <= '\u9fff')
    ascii_chars = sum(1 for c in title if c.isascii() and c.isalpha())
    total = cjk + ascii_chars
    if total == 0: return False
    return ascii_chars / total > 0.6

def load_json(pattern):
    """加载匹配前缀的最新 JSON 文件（按修改时间，避免文件名排序导致的竞态）。

    fetch 脚本输出文件名格式: {pattern}_{date}_{pid}.json（如 daily_report_2026-06-17_12345.json）
    本函数按 mtime 取最新匹配文件，确保读到最近一次管道运行的输出。
    """
    candidates = [
        f for f in os.listdir(REPORTS_DIR)
        if f.startswith(pattern) and f.endswith('.json')
    ]
    if not candidates:
        return {}
    # 按修改时间降序，取最新
    full_paths = [os.path.join(REPORTS_DIR, f) for f in candidates]
    latest = max(full_paths, key=os.path.getmtime)
    with open(latest, encoding='utf-8') as f:
        return json.load(f)

def main():
    date_tag = datetime.now().strftime('%Y-%m-%d')
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # 各数据源按分类整理
    sources = {
        'platform_hotlists': [],  # 微博/抖音/头条/知乎 热搜
        'rss_news': [],           # IT之家/36Kr/英文科技媒体
        'bilibili_videos': [],    # B站热门视频
    }

    # ── 1. 4平台热榜（微博/抖音/头条） ──
    data = load_json('daily_report_')
    if data:
        for pid, items in data.get('data', {}).items():
            if pid == 'bilibili':
                for item in items:
                    if not is_garbage(item.get('title', '')):
                        sources['bilibili_videos'].append({
                            'source': f'{pid}_hotlist',
                            'title': item.get('title', ''),
                            'url': item.get('url', ''),
                            'metadata': {
                                'rank': item.get('rank'),
                                'views': item.get('value_text', ''),
                                'author': item.get('author', ''),
                            }
                        })
            else:
                for item in items:
                    title = item.get('title', '')
                    if title and not is_garbage(title):
                        sources['platform_hotlists'].append({
                            'source': f'{pid}_hotlist',
                            'title': title,
                            'url': item.get('url', ''),
                            'metadata': {
                                'rank': item.get('rank'),
                                'heat': item.get('value_text', ''),
                            }
                        })

    # ── 2. DailyHotApi（知乎/微博/抖音） ──
    data = load_json('dailyhot_api_')
    if data:
        for pid, items in data.get('data', {}).items():
            if pid in ('bilibili'):
                for item in items:
                    if not is_garbage(item.get('title', '')):
                        sources['bilibili_videos'].append({
                            'source': f'{pid}_dailyhot',
                            'title': item.get('title', ''),
                            'url': item.get('url', ''),
                            'metadata': {'rank': item.get('rank')}
                        })
            elif pid in ('zhihu', 'weibo', 'douyin'):
                for item in items:
                    title = item.get('title', '')
                    if title and not is_garbage(title):
                        sources['platform_hotlists'].append({
                            'source': f'{pid}_dailyhot',
                            'title': title,
                            'url': item.get('url', ''),
                            'metadata': {
                                'rank': item.get('rank'),
                                'heat': item.get('value_text', ''),
                            }
                        })

    # ── 3. RSS/英文追溯 ──
    # 按 mtime 加载最新的 english_news 文件（PID 命名防竞态）
    # 如果 traced 文件存在且有更多条目，则优先使用 traced 版本
    data = load_json('english_news_')
    traced_data = load_json('english_news_traced')
    if traced_data and len(traced_data.get('items', [])) > len(data.get('items', [])):
        data = traced_data
    if not data or not data.get('items'):
        data = {}
    if data:
        for item in data.get('items', []):
            title = item.get('title', '')
            if not title or is_garbage(title):
                continue
            source = item.get('source', '')
            if source in ('Not found', 'Other', 'Unknown'):
                url = item.get('url', item.get('original_rss_url', ''))
                m = re.search(r'https?://([^/]+)', url)
                source = m.group(1).replace('www.', '').split('.')[0].title() if m else source
            if is_chinese_media_english(title, source):
                continue
            sources['rss_news'].append({
                'source': source,
                'title': title,
                'url': item.get('url', item.get('original_rss_url', item.get('link', ''))),
                'metadata': {
                    'published': item.get('published', item.get('pub_date', ''))[:10],
                    'rating': item.get('rating', ''),
                }
            })

    # ── 4. 基础去重（完全相同的标题合并） ──
    for category in sources:
        seen = {}
        deduped = []
        for item in sources[category]:
            key = item['title'].lower().strip()
            if key in seen:
                seen[key]['sources'].append(item['source'])
                seen[key]['urls'].append(item['url'])
            else:
                item['sources'] = [item['source']]
                item['urls'] = [item['url']]
                deduped.append(item)
                seen[key] = item
        # ── 4.5 RSS 相似标题聚类（不同标题的同一事件合并，仅 RSS） ──
        if category == 'rss_news' and len(deduped) > 1:
            clustered = []
            used = set()
            for i in range(len(deduped)):
                if i in used:
                    continue
                cluster = [deduped[i]]
                used.add(i)
                for j in range(i + 1, len(deduped)):
                    if j in used:
                        continue
                    t1 = re.sub(r'[^\w\u4e00-\u9fff]', '', deduped[i]['title'].lower())
                    t2 = re.sub(r'[^\w\u4e00-\u9fff]', '', deduped[j]['title'].lower())
                    bigrams1 = set(t1[k:k+2] for k in range(len(t1)-1))
                    bigrams2 = set(t2[k:k+2] for k in range(len(t2)-1))
                    if bigrams1 and bigrams2:
                        sim = len(bigrams1 & bigrams2) / len(bigrams1 | bigrams2)
                        if sim > 0.35:
                            cluster.append(deduped[j])
                            used.add(j)
                if len(cluster) > 1:
                    merged = dict(cluster[0])
                    merged['sources'] = [c['source'] for c in cluster]
                    merged['urls'] = [c['url'] for c in cluster if c.get('url')]
                    # 确保 merged['url'] 取第一个有效 URL，避免聚类合并后 url 为空
                    valid_urls = [u for u in merged['urls'] if u]
                    merged['url'] = valid_urls[0] if valid_urls else merged.get('url', '')
                    merged['title'] = min([c['title'] for c in cluster], key=lambda x: len(x))
                    clustered.append(merged)
                else:
                    clustered.append(deduped[i])
            deduped = clustered

        sources[category] = deduped

    # ── 输出 ──
    print(f"   平台热榜: {len(sources['platform_hotlists'])} 条")
    print(f"   RSS 新闻: {len(sources['rss_news'])} 条")
    print(f"   B站视频:  {len(sources['bilibili_videos'])} 条")

    output = {
        'date': f"{date_tag} {datetime.now().strftime('%H:%M')}",
        'sources': {k: len(v) for k, v in sources.items()},
        'data': sources,
    }

    out_path = os.path.join(REPORTS_DIR, f'raw_data_{date_tag}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ 原始数据已保存: {out_path}")

    # ── 5. 写入数据库 + 事件关联 ──
    try:
        db_path = os.environ.get('NEWS_DB_PATH', os.path.join(os.path.dirname(SCRIPT_DIR), 'data', 'news.db'))
        db = NewsDB(db_path)
        total = 0
        for cat in ('platform_hotlists', 'rss_news', 'bilibili_videos'):
            n, skipped = db.save_news_articles(cat, sources[cat])
            total += n
            msg = f"   DB ↑ {cat}: {n} 条新增"
            if skipped:
                msg += f", ⏭️ {skipped} 条跳过（已存在）"
            print(msg)
        # 热榜/B站视频直接填充 text_content — 无需走 fetch_content 下载 HTML
        trend_filled = db.fill_trend_text()
        if trend_filled:
            print(f"   DB 📝 趋势文本回填: {trend_filled} 条")
        new_events = db.link_articles_to_events()
        print(f"   DB 🏷️ 事件关联: {new_events} 个新事件")
        stats = db.get_stats()
        print(f"   DB 📊 总计: {stats['articles']} 篇文章, {stats['events']} 个事件")
    except Exception as e:
        print(f"   DB ⚠️ 写入失败: {e}")

    # AI 预筛选（静默嵌入，不暴露独立步骤）
    try:
        from ai_filter import run_ai_filter  # noqa: F811
        run_ai_filter(db_path)
    except Exception as e:
        print(f"   AI ⚠️ 预筛选异常: {e}")

    return sources

if __name__ == '__main__':
    main()
