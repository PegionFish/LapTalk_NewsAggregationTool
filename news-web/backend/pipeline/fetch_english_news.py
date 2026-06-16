#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英文热点新闻获取脚本
通过 RSS 解析 BBC Tech / Reuters / NPR 等英文媒体的科技/世界热点
结果保存为 JSON，供最终报告整合使用
"""

import sys
import os
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import time
import re
from datetime import datetime, timedelta

# 确保 Windows 控制台输出 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 境外代理 — 如已配置代理则启用 ──────────────────────
try:
    from utils.proxy import setup_urllib_proxy
    setup_urllib_proxy()
except Exception:
    pass

# ─── RSS 源配置 ────────────────────────────────────────
RSS_FEEDS = [
    # ══════════════════════════════════════════════════
    # 中文 IT / 数码垂类（中文标题，原站直出）
    # ══════════════════════════════════════════════════
    {
        'name': 'IT之家',
        'url': 'https://www.ithome.com/rss/',
        'tag': 'IT之家',
        'lang': 'zh',
        'credible': True,
    },
    {
        'name': '36Kr',
        'url': 'https://36kr.com/feed',
        'tag': '36Kr',
        'lang': 'zh',
        'credible': True,
    },
    {
        'name': '钛媒体',
        'url': 'https://www.tmtpost.com/rss',
        'tag': '钛媒体',
        'lang': 'zh',
        'credible': True,
    },
    {
        'name': '爱范儿',
        'url': 'https://www.ifanr.com/feed',
        'tag': '爱范儿',
        'lang': 'zh',
        'credible': True,
    },
    {
        'name': '少数派',
        'url': 'https://sspai.com/feed',
        'tag': '少数派',
        'lang': 'zh',
        'credible': True,
    },
    {
        'name': 'Solidot',
        'url': 'https://www.solidot.org/index.rss',
        'tag': 'Solidot',
        'lang': 'zh',
        'credible': True,
    },
    # ══════════════════════════════════════════════════
    # AI 专属媒体（来自 daily-hot-ai-news skill）
    # ══════════════════════════════════════════════════
    {
        'name': '机器之心',
        'url': 'https://www.jiqizhixin.com/rss',
        'tag': '机器之心',
        'lang': 'zh',
        'credible': True,
    },
    {
        'name': '雷锋网',
        'url': 'https://www.leiphone.com/feed',
        'tag': '雷锋网',
        'lang': 'zh',
        'credible': True,
    },
    # ══════════════════════════════════════════════════
    # 英文 AI 专属媒体
    # ══════════════════════════════════════════════════
    {
        'name': 'MIT Tech Review',
        'url': 'https://www.technologyreview.com/feed/',
        'tag': 'MIT科技评论',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'The Decoder',
        'url': 'https://the-decoder.com/feed/',
        'tag': 'The Decoder',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'AI News',
        'url': 'https://www.artificialintelligence-news.com/feed/',
        'tag': 'AI News',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'MarkTechPost',
        'url': 'https://www.marktechpost.com/feed/',
        'tag': 'MarkTechPost',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'VentureBeat AI',
        'url': 'https://venturebeat.com/category/ai/feed/',
        'tag': 'VentureBeat AI',
        'lang': 'en',
        'credible': True,
    },
    # ══════════════════════════════════════════════════
    # 英文科技媒体
    # ══════════════════════════════════════════════════
    # 主流综合
    {
        'name': 'Ars Technica',
        'url': 'https://feeds.arstechnica.com/arstechnica/index',
        'tag': 'Ars Technica',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'TechCrunch',
        'url': 'https://techcrunch.com/feed/',
        'tag': 'TechCrunch',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Engadget',
        'url': 'https://www.engadget.com/rss.xml',
        'tag': 'Engadget',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Gizmodo',
        'url': 'https://gizmodo.com/rss',
        'tag': 'Gizmodo',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Digital Trends',
        'url': 'https://www.digitaltrends.com/feed/',
        'tag': 'Digital Trends',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'CNET',
        'url': 'https://www.cnet.com/rss/news/',
        'tag': 'CNET',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'VentureBeat',
        'url': 'https://venturebeat.com/feed/',
        'tag': 'VentureBeat',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'ZDNet',
        'url': 'https://www.zdnet.com/news/rss.xml',
        'tag': 'ZDNet',
        'lang': 'en',
        'credible': True,
    },
    # 硬件 / GPU / CPU 垂类
    {
        'name': "Tom's Hardware",
        'url': "https://www.tomshardware.com/feeds/all",
        'tag': "Tom's Hardware",
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Wccftech',
        'url': 'https://wccftech.com/feed/',
        'tag': 'Wccftech',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Guru3D',
        'url': 'https://www.guru3d.com/rss.xml',
        'tag': 'Guru3D',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Phoronix',
        'url': 'https://www.phoronix.com/rss.php',
        'tag': 'Phoronix',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Liliputing',
        'url': 'https://liliputing.com/feed/',
        'tag': 'Liliputing',
        'lang': 'en',
        'credible': True,
    },
    # 硬件/服务器专业媒体
    {
        'name': 'ServeTheHome',
        'url': 'https://www.servethehome.com/feed/',
        'tag': 'ServeTheHome',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'TechPowerUp',
        'url': 'https://www.techpowerup.com/rss/news',
        'tag': 'TechPowerUp',
        'lang': 'en',
        'credible': True,
    },
    # Apple 生态
    {
        'name': '9to5Mac',
        'url': 'https://9to5mac.com/feed/',
        'tag': '9to5Mac',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'MacRumors',
        'url': 'https://feeds.macrumors.com/MacRumors-All',
        'tag': 'MacRumors',
        'lang': 'en',
        'credible': True,
    },
    # Android / Mobile
    {
        'name': 'Android Police',
        'url': 'https://www.androidpolice.com/feed/',
        'tag': 'Android Police',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'XDA Developers',
        'url': 'https://www.xda-developers.com/feed/',
        'tag': 'XDA',
        'lang': 'en',
        'credible': True,
    },
    # ══════════════════════════════════════════════════
    # 游戏/电竞媒体（2026-06-09 新增）
    # ══════════════════════════════════════════════════
    {
        'name': 'PC Gamer',
        'url': 'https://www.pcgamer.com/rss/',
        'tag': 'PC Gamer',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Eurogamer',
        'url': 'https://www.eurogamer.net/feed',
        'tag': 'Eurogamer',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'GameSpot',
        'url': 'https://www.gamespot.com/feeds/news/',
        'tag': 'GameSpot',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Rock Paper Shotgun',
        'url': 'https://www.rockpapershotgun.com/feed',
        'tag': 'RockPaperShotgun',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'VG247',
        'url': 'https://www.vg247.com/feed',
        'tag': 'VG247',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'Nintendo Everything',
        'url': 'https://nintendoeverything.com/feed/',
        'tag': 'NintendoEverything',
        'lang': 'en',
        'credible': True,
    },
    # 传统通讯社
    {
        'name': 'BBC Technology',
        'url': 'https://feeds.bbci.co.uk/news/technology/rss.xml',
        'tag': 'BBC科技',
        'lang': 'en',
        'credible': True,
    },
    {
        'name': 'NPR Technology',
        'url': 'https://feeds.npr.org/1001/rss.xml',
        'tag': 'NPR科技',
        'lang': 'en',
        'credible': True,
    },
]

TIMEOUT = 30  # 秒
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*;q=0.1',
}


def parse_rss_regex(xml_text: str) -> list:
    """
    解析 RSS XML，兼容多种格式：
    - BBC/Reuters 风格: <title><![CDATA[Title]]></title>
    - Ars Technica 风格: <title>Title</title>
    - 36Kr 风格: <link><![CDATA[URL]]></link>
    - Atom 风格: <link rel="alternate" href="URL"/>
    """
    items = []
    item_blocks = re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL | re.IGNORECASE)

    for block in item_blocks:
        # 提取 title（兼容 CDATA 和 plain text）
        title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', block, re.DOTALL)
        if not title_match:
            title_match = re.search(r'<title>(.*?)</title>', block, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ''

        # 提取 link（兼容 CDATA / plain text / Atom href 属性）
        link = ''
        link_cdata = re.search(r'<link><!\[CDATA\[(.*?)\]\]></link>', block, re.DOTALL)
        if link_cdata and link_cdata.group(1).strip():
            link = link_cdata.group(1).strip()
        if not link:
            link_plain = re.search(r'<link>(.*?)</link>', block, re.DOTALL)
            if link_plain and link_plain.group(1).strip():
                link = re.sub(r'<[^>]+>', '', link_plain.group(1)).strip()
        if not link:
            link_attr = re.search(r'<link[^>]+href="([^"]+)"', block, re.DOTALL | re.IGNORECASE)
            if link_attr:
                link = link_attr.group(1).strip()

        # 提取 pub_date
        pub_match = re.search(r'<pubDate>(.*?)</pubDate>', block, re.DOTALL)
        pub_date = pub_match.group(1).strip() if pub_match else ''

        # 提取 description（兼容 CDATA）
        desc_match = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>', block, re.DOTALL)
        if not desc_match:
            desc_match = re.search(r'<description>(.*?)</description>', block, re.DOTALL)
        desc_raw = desc_match.group(1).strip() if desc_match else ''
        description = re.sub(r'<[^>]+>', '', desc_raw).strip()[:300]

        if title:
            items.append({
                'title': title,
                'link': link,
                'pub_date': pub_date,
                'description': description,
            })

    return items


def fetch_feed(feed: dict) -> list:
    """获取单个 RSS 源"""
    try:
        req = urllib.request.Request(feed['url'], headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            xml = resp.read().decode('utf-8', errors='ignore')

        items = parse_rss_regex(xml)
        return [{**item, 'source': feed['name'], 'tag': feed['tag'],
                 'lang': feed.get('lang', 'en'), 'credible': feed['credible']}
                for item in items]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # Reuters 等 feed 偶尔 404，静默跳过
        return []
    except Exception:
        return []


def is_tech_related(title: str, description: str = '', source: str = '') -> bool:
    """
    白名单模式：只有明确命中科技核心主题才通过。
    排除政治/社会/娱乐一般报道。

    如果 source 是已知游戏媒体，则跳过科技关键词过滤（游戏媒体文章默认全部通过）。
    """
    text = (title + ' ' + (description or '')).lower()

    # 游戏媒体来源 — 默认全部通过
    GAME_MEDIA = ['pc gamer', 'eurogamer', 'gamespot', 'rock paper shotgun', 'vg247', 'nintendo everything',
                  'ign', 'kotaku', 'polygon', 'destructoid', 'gematsu', 'gamesindustry']
    if source.lower() in GAME_MEDIA:
        return True

    # ✅ 核心科技主题（命中即通过，使用词边界避免误匹配）
    CORE_TECH_PATTERNS = [
        # AI 类
        r'\bAI\b', r'\bA\.I\.\b', r'\bartificial intelligence\b',
        r'\bmachine learning\b', r'\bdeep learning\b',
        r'\bLLM\b', r'\blarge language model\b',
        r'\bChatGPT\b', r'\bClaude\b', r'\bGemini\b', r'\bOpenAI\b',
        r'\bGPT-\d\b', r'\bGemma\b', r'\bLlama\b', r'\bMistral\b', r'\bDeepSeek\b',
        # 航天
        r'\bSpaceX\b', r'\bNASA\b', r'\bJAXA\b', r'\bESA\b',
        r'\brocket\b', r'\bsatellite\b', r'\bMars\b',
        r'\bArtemis\b', r'\bStarship\b', r'\borbital\b',
        # 半导体/芯片/GPU
        r'\bsemiconductor\b', r'\bchipmaker\b', r'\bHBM\b', r'\bEUV\b',
        r'\bTSMC\b', r'\bNVIDIA\b', r'\bAMD\b', r'\bQualcomm\b', r'\bMediaTek\b',
        r'\bIntel Core\b', r'\bCore Ultra\b', r'\bRyzen\b', r'\bGPU\b', r'\bCPU\b',
        r'\bArc \d\b', r'\bGeForce\b', r'\bRadeon\b', r'\bRTX\b', r'\bGTX\b',
        r'\bSSD\b', r'\bNVMe\b', r'\bDDR5\b', r'\bLPDDR\b',
        # Apple 生态
        r'\biPhone\b', r'\biPad\b', r'\bMacBook\b', r'\bMac \w+\b', r'\bApple Silicon\b',
        r'\bM\d\b', r'\bA\d{2}\b', r'\bmacOS\b', r'\biOS \d+\b', r'\bwatchOS\b',
        r'\bAirPods\b', r'\bVision Pro\b', r'\bWWDC\b', r'\bApple Intelligence\b',
        r'\bGoogle AI\b', r'\bMicrosoft AI\b', r'\bPixel \d\b', r'\bSamsung Galaxy\b',
        # 机器人/自动驾驶
        r'\brobotaxi\b', r'\bself-driving\b', r'\bautonomous vehicle\b',
        r'\bhumanoid robot\b', r'\bBoston Dynamics\b',
        # 网络安全
        r'\bcyber attack\b', r'\bcyber breach\b', r'\bdata breach\b',
        r'\bransomware\b', r'\bhack\b', r'\bmalware\b', r'\bzero-day\b',
        # 平台/软件
        r'\balgorithm\b', r'\bopen source\b', r'\bsoftware update\b',
        r'\bapp store\b', r'\bGoogle Play\b',
        # 航天科技
        r'\bStarlink\b', r'\bOneWeb\b', r'\bLEO satellite\b',
        # 监管/贸易
        r'\bexport control\b', r'\bchip sanction\b', r'\bAI act\b', r'\bFTC\b',
        # IT之家/国内常见科技关键词（中文标题）
        '太芯', '芯片', '光刻', '算力', '大模型', '大模型',
        # 游戏/电竞
        r'\bgam\w*\b', r'\bNintendo\b',
        r'\bPlayStation\b', r'\bPS5\b', r'\bPS6\b',
        r'\bXbox\b', r'\bSteam\b', r'\bEpic Games\b',
        r'\bValve\b', r'\bSwitch\b', r'\bSwitch 2\b',
        r'\bUnreal Engine\b', r'\bUnity\b',
        r'\bRPG\b', r'\bFPS\b', r'\bdemo\b',
        r'\bconsole\b', r'\bremake\b', r'\bremaster\b',
        r'\bDLC\b', r'\bexpansion\b', r'\bsequel\b', r'\btrailer\b',
        r'\bgametest\b', r'\bgamplay\b', r'\breview\b',
        r'\bGTA\b', r'\bElden Ring\b',
        r'\bCall of Duty\b', r'\bCoD[^a-z]\b',
        r'\bMario\b', r'\bZelda\b', r'\bFinal Fantasy\b',
        r'\bPok[eé]mon\b', r'\bMonster Hunter\b',
        r'\bAssassin[\' ]?s? Creed\b', r'\bMinecraft\b',
        r'\bSonic\b', r'\bFortnite\b',
        r'\bCyberpunk\b', r'\bWitcher\b',
        r'\bGrand Theft Auto\b', r'\bRed Dead\b',
        r'\bUbisoft\b', r'\bElectronic Arts\b', r'\bActivision\b',
        r'\bBlizzard\b', r'\bSquare Enix\b', r'\bBandai Namco\b',
        r'\bCapcom\b', r'\bFromSoftware\b', r'\bBethesda\b',
        r'\bRockstar\b', r'\bTake-Two\b', r'\bEmbracer\b',
        r'\bCD Projekt\b', r'\bSega\b', r'\bSEGA\b',
        r'\bKonami\b', r'\bKoei Tecmo\b',
        r'\bGOG\b', r'\bitch\.io\b', r'\bitchio\b',
    ]

    # ❌ 明确排除（非科技内容）
    EXCLUDE_PATTERNS = [
        r'\belection\b', r'\btrump\b', r'\bbiden\b', r'\bputin\b',
        r'\bparliament\b', r'\bcongress\b', r'\bsenate\b',
        r'\bgun control\b', r'\bimmigration\b', r'\babortion\b',
        r'\bfootball\b', r'\bsoccer\b', r'\bWorld Cup\b',
        r'\bHollywood\b', r'\bcelebrity\b', r'\bOscar\b', r'\bGrammy\b',
        r'\bmurder\b', r'\bkidnap\b', r'\bsexual assault\b',
        r'\bwar crime\b', r'\bceasefire\b',
    ]

    # 先排除
    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return False

    # 再确认核心科技主题
    for pat in CORE_TECH_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True

    return False


def parse_date(date_str: str) -> str:
    """标准化日期格式"""
    if not date_str:
        return ''
    try:
        # RFC 822: "Sat, 04 Apr 2026 12:00:00 GMT"
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return date_str[:16] if len(date_str) > 16 else date_str


def fetch_all() -> list:
    """获取所有 RSS 源，过滤科技相关内容"""
    all_items = []

    for feed in RSS_FEEDS:
        items = fetch_feed(feed)
        all_items.extend(items)
        time.sleep(0.3)  # 礼貌延迟

    return all_items


def main():
    output_file = os.path.join(SCRIPT_DIR, 'hot_reports', 'english_news.json')

    print(f"🌍 开始获取英文热点...")
    all_items = fetch_all()
    print(f"   总条目: {len(all_items)}")

    # 过滤科技相关
    tech_items = [item for item in all_items if is_tech_related(item['title'], item.get('description', ''), source=item.get('source', ''))]
    print(f"   科技相关: {len(tech_items)}")

    # 清理并标准化日期
    for item in tech_items:
        item['pub_date'] = parse_date(item['pub_date'])

    # 按日期排序（最新优先），取前 300 条
    tech_items.sort(key=lambda x: x['pub_date'] or '', reverse=True)
    tech_items = tech_items[:300]

    result = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total_fetched': len(all_items),
        'tech_filtered': len(tech_items),
        'items': tech_items,
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ 英文热点已保存: {output_file}")

    # 打印摘要
    print(f"\n🌍 英文科技热点 TOP{len(tech_items)}:")
    for i, item in enumerate(tech_items[:5], 1):
        print(f"  {i}. [{item['source']}] {item['title'][:60]}")
        if item.get('pub_date'):
            print(f"     📅 {item['pub_date']}")

    return result


if __name__ == '__main__':
    main()
