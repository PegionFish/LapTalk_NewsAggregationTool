#!/usr/bin/env python3
"""
AI 预筛选 — 用 DeepSeek V3.2 判断文章是否值得缓存。
先筛标题，再下载，避免浪费时间缓存不需要的内容。

流程：
  1. 查询 DB 中 local_path='' 且 ai_filtered=0 的文章
  2. 每批 30 个标题发给 DeepSeek
  3. DeepSeek 返回保留/拒绝列表
  4. 更新 DB 的 ai_filtered 字段
"""
import sys, os, json, sqlite3, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from ai_client import chat
from db.news_db import NewsDB

BATCH_SIZE = 30

FILTER_PROMPT = """你是新闻筛选助手。根据以下标题列表，判断哪些文章值得下载全文阅读。

筛选标准（保留）：
- AI/大模型/LLM 相关（发布、评测、技术突破、行业影响）
- 芯片/半导体/GPU/CPU 硬件新闻
- 科技公司重大动态（收购、财报、战略、产品线变化）
- 软件/操作系统重大更新
- 科技监管/政策/贸易制裁
- 网络安全重大事件
- 重要产品发布（手机、电脑、芯片等）

筛选标准（拒绝）：
- 航天/机器人/自动驾驶/智驾（优先级不高，跳过）
- 游戏具体玩法攻略/评测/通关指南
- 游戏 DLC/赛季/活动公告
- 个别游戏的社区讨论/玩家反应
- 体育/娱乐/政治一般报道
- 促销/优惠/购物推荐
- 纯观点/评论文章（无事实增量）

输入格式：
每行一个 [ID] 标题

输出格式：
只输出保留的 ID 列表，用逗号分隔，不要任何解释。
例如：1,3,5,8"""


def filter_batch(articles: list) -> set | None:
    """对一批文章标题调用 AI 筛选，返回保留的 ID 集合。

    Returns:
        set: AI 判定应保留的文章 ID
        None: API 调用失败（调用方应保持原有 ai_filtered 状态，等待重试）
    """
    lines = []
    for aid, title, source in articles:
        lines.append(f"[{aid}] [{source}] {title}")
    prompt = FILTER_PROMPT + "\n\n" + "\n".join(lines)

    try:
        result = chat(prompt, system_prompt="你是精准的新闻筛选器。只输出ID列表。", max_tokens=200)
        ids = set()
        for part in result.replace('，', ',').split(','):
            part = part.strip().strip('[]').strip()
            if part.isdigit():
                ids.add(int(part))
        return ids
    except Exception as e:
        print(f"  ⚠️ AI 筛选 API 调用失败（{type(e).__name__}: {e}），跳过本批，保持待筛选状态")
        return None


def run_ai_filter(db_path: str = None):
    """执行 AI 预筛选。"""
    if not db_path:
        db_path = config.db_path

    if not config.openai_api_key:
        print("⚠️ 未配置 AI API Key，跳过筛选")
        return

    # 用 NewsDB 触发迁移（确保 ai_filtered 列存在）
    db = NewsDB(db_path)
    conn = db._conn()

    # 查询待筛选文章
    rows = conn.execute("""
        SELECT id, title, source FROM articles
        WHERE (local_path = '' OR local_path IS NULL)
          AND (ai_filtered = 0)
          AND category NOT IN ('platform_hotlists', 'bilibili_videos')
        ORDER BY fetched_at DESC
    """).fetchall()

    if not rows:
        print("✅ 没有待筛选的文章")
        conn.close()
        return

    print(f"📋 待筛选文章: {len(rows)} 篇")
    approved = 0
    rejected = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_ids = filter_batch(batch)

        if batch_ids is None:
            # API 调用失败 — 保持 ai_filtered=0，等待下次重试，不标记为拒绝
            print(f"  ⚠️ 批次 {i // BATCH_SIZE + 1} API 失败，跳过，保持待筛选状态")
            continue

        for aid, title, source in batch:
            if aid in batch_ids:
                conn.execute("UPDATE articles SET ai_filtered=1 WHERE id=?", (aid,))
                approved += 1
            else:
                conn.execute("UPDATE articles SET ai_filtered=-1 WHERE id=?", (aid,))
                rejected += 1

        conn.commit()
        done = min(i + BATCH_SIZE, len(rows))
        print(f"  [{done}/{len(rows)}] 通过={approved} 拒绝={rejected}")
        time.sleep(0.5)

    conn.close()
    print(f"\n📊 筛选完成: {approved} 篇通过, {rejected} 篇拒绝")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description="AI 预筛选文章")
    p.add_argument('--db', default=None)
    args = p.parse_args()
    run_ai_filter(args.db)
