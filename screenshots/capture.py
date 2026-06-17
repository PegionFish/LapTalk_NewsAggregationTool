# -*- coding: utf-8 -*-
"""
无头浏览器截图审查 — 捕获所有关键页面的视觉状态。
"""
import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.async_api import async_playwright

BASE = "http://localhost:8081"
SCREENSHOT_DIR = "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool/screenshots"

async def main():
    import os
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
        )
        page = await ctx.new_page()

        # 1. 登录页
        await page.goto(f"{BASE}/login", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(1)
        await page.screenshot(path=f"{SCREENSHOT_DIR}/01_login.png", full_page=False)
        print("[OK] 01_login.png")

        # 自动登录 (localhost 免密)
        await page.goto(f"{BASE}/", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(1)

        # 2. Dashboard
        await page.screenshot(path=f"{SCREENSHOT_DIR}/02_dashboard.png", full_page=False)
        print("[OK] 02_dashboard.png")

        # 滚动到低分清理卡片
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=f"{SCREENSHOT_DIR}/03_dashboard_bottom.png", full_page=False)
        print("[OK] 03_dashboard_bottom.png")

        # 3. 文章检索页
        await page.goto(f"{BASE}/articles", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(1)
        await page.screenshot(path=f"{SCREENSHOT_DIR}/04_articles.png", full_page=False)
        print("[OK] 04_articles.png")

        # 4. 点击第一篇文章，打开右侧面板
        first_row = page.locator("table tbody tr").first
        if await first_row.count() > 0:
            await first_row.click()
            await asyncio.sleep(1)
            await page.screenshot(path=f"{SCREENSHOT_DIR}/05_article_detail.png", full_page=False)
            print("[OK] 05_article_detail.png")

            # 滚动右侧面板到底部看评语区
            panel = page.locator("div").filter(has_text="AI 分析解读").last
            if await panel.count() > 0:
                await panel.evaluate("el => el.closest('div[style]')?.scrollTo(0, 9999)")
                await asyncio.sleep(0.5)
            await page.screenshot(path=f"{SCREENSHOT_DIR}/06_article_panel_bottom.png", full_page=False)
            print("[OK] 06_article_panel_bottom.png")

        # 5. 热点趋势页
        await page.goto(f"{BASE}/hotlists", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(1)
        await page.screenshot(path=f"{SCREENSHOT_DIR}/07_hotlists.png", full_page=False)
        print("[OK] 07_hotlists.png")

        # 6. 设置页
        await page.goto(f"{BASE}/settings", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(1)
        await page.screenshot(path=f"{SCREENSHOT_DIR}/08_settings.png", full_page=False)
        print("[OK] 08_settings.png")

        await browser.close()
        print(f"\n全部截图保存到 {SCREENSHOT_DIR}/")

asyncio.run(main())
