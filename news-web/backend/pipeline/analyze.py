#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热榜分析脚本 - 读取最新报告，生成格式化摘要
由 OpenClaw 在收到 QQ 请求时调用
"""

import sys
import os
import json
from datetime import datetime, timedelta
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

def get_latest_report():
    """获取最新一期报告"""
    reports_dir = os.path.join(SCRIPT_DIR, 'hot_reports')
    if not os.path.exists(reports_dir):
        return None

    files = [f for f in os.listdir(reports_dir) if f.startswith('daily_report_') and f.endswith('.json')]
    if not files:
        return None

    files.sort(reverse=True)
    latest = files[0]
    with open(os.path.join(reports_dir, latest), 'r', encoding='utf-8') as f:
        return json.load(f), latest

def get_previous_report():
    """获取前一天报告"""
    reports_dir = os.path.join(SCRIPT_DIR, 'hot_reports')
    if not os.path.exists(reports_dir):
        return None

    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    yesterday_file = os.path.join(reports_dir, f'daily_report_{yesterday}.json')

    if os.path.exists(yesterday_file):
        with open(yesterday_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def extract_keywords(data, top_n=8):
    """提取热词"""
    all_titles = []
    for platform, items in data.get('data', {}).items():
        for item in items:
            title = item.get('title', '')
            if title:
                all_titles.append(title)

    keywords = Counter()
    for title in all_titles:
        for i in range(len(title) - 1):
            for length in [2, 3, 4]:
                if i + length <= len(title):
                    word = title[i:i+length]
                    if any('\u4e00' <= c <= '\u9fff' for c in word):
                        keywords[word] += 1

    stop_words = {'的是', '什么', '这个', '那个', '怎么', '如何', '可以', '没有', '一个', '就是', '不是', '大家', '应该', '已经', '为什么'}
    filtered = [(k, v) for k, v in keywords.most_common(top_n * 2) if k not in stop_words]
    return filtered[:top_n]

def generate_summary_text(data):
    """生成格式化摘要"""
    platforms_data = data.get('data', {})
    date_str = data.get('date', '')

    platform_names = {
        'bilibili': '📺 B站热门',
        'douyin': '🎵 抖音热搜',
        'weibo': '🔍 微博热搜',
        'toutiao': '📰 今日头条'
    }

    lines = [
        f"🔥 全平台热榜日报",
        f"📅 {date_str}",
        "=" * 40
    ]

    for platform, name in platform_names.items():
        items = platforms_data.get(platform, [])
        if not items:
            continue
        lines.append(f"\n{name} Top {len(items)}:")
        for i, item in enumerate(items[:5], 1):
            label = f" [{item.get('label', '')}]" if item.get('label') else ""
            lines.append(f"  #{i} {item.get('title', '')}{label} ({item.get('value_text', '')})")

    return '\n'.join(lines)

def generate_full_analysis():
    """生成完整分析报告"""
    result = get_latest_report()
    if not result:
        return "⚠️ 暂无热榜数据，请先等待定时抓取完成。"

    data, filename = result
    prev_data = get_previous_report()

    date_str = data.get('date', '')
    platforms_data = data.get('data', {})

    platform_names = {
        'bilibili': '📺 B站热门',
        'douyin': '🎵 抖音热搜',
        'weibo': '🔍 微博热搜',
        'toutiao': '📰 今日头条'
    }

    lines = [
        f"🔥 全平台热榜日报",
        f"📅 {date_str}",
        "=" * 40,
        ""
    ]

    # 各平台热榜
    for platform, name in platform_names.items():
        items = platforms_data.get(platform, [])
        if not items:
            continue
        lines.append(f"{name} Top {len(items)}:")
        for i, item in enumerate(items[:10], 1):
            label = f" [{item.get('label', '')}]" if item.get('label') else ""
            lines.append(f"  #{i} {item.get('title', '')}{label} ({item.get('value_text', '')})")
        lines.append("")

    # 热门关键词
    keywords = extract_keywords(data, 10)
    if keywords:
        lines.append("=" * 40)
        lines.append("🔥 今日热词 TOP10:")
        kw_str = "  " + "  ".join([f"{k}({v})" for k, v in keywords])
        lines.append(kw_str)
        lines.append("")

    # 环比变化（新上榜话题）
    if prev_data:
        lines.append("=" * 40)
        lines.append("🆕 相比昨日新上榜话题:")
        prev_titles = {}
        for platform, items in prev_data.get('data', {}).items():
            prev_titles[platform] = {item.get('title', '') for item in items}

        new_count = 0
        for platform, items in platforms_data.items():
            for item in items:
                title = item.get('title', '')
                if title and title not in prev_titles.get(platform, set()):
                    new_count += 1
                    if new_count <= 10:
                        lines.append(f"  [{platform_names.get(platform, platform)}] {title}")

        if new_count == 0:
            lines.append("  （今日热榜话题与昨日基本一致）")
        else:
            lines.append(f"\n  共 {new_count} 个新上榜话题")
        lines.append("")

    lines.append("=" * 40)
    lines.append(f"📁 数据文件: {filename}")

    return '\n'.join(lines)

if __name__ == '__main__':
    print(generate_full_analysis())
