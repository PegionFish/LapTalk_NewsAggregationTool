import { test, expect } from '@playwright/test';

test.describe('News Aggregation Web — E2E', () => {
  test('health endpoint responds', async ({ request }) => {
    const resp = await request.get('/api/health');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.status).toBe('ok');
  });

  test('frontend serves HTML', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=新闻知识聚合')).toBeVisible();
  });

  test('sidebar navigation loads all pages', async ({ page }) => {
    await page.goto('/');

    // Dashboard
    await page.click('text=仪表盘');
    await expect(page.locator('text=📊 仪表盘')).toBeVisible();

    // Article search
    await page.click('text=文章检索');
    await expect(page.locator('text=📄 文章检索')).toBeVisible();

    // Chain list
    await page.click('text=逻辑链列表');
    await expect(page.locator('text=📋 逻辑链列表')).toBeVisible();

    // Settings
    await page.click('text=设置');
    await expect(page.locator('text=⚙ 设置')).toBeVisible();

    // Workspace
    await page.click('text=逻辑链工作台');
    await expect(page.locator('text=🔍 搜索')).toBeVisible();
  });

  test('settings page shows config form', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.locator('input[placeholder="/path/to/news.db"]')).toBeVisible();
    await expect(page.locator('text=AI 配置')).toBeVisible();
    await expect(page.locator('text=抓取调度')).toBeVisible();
  });

  test('workspace has search panel and canvas', async ({ page }) => {
    await page.goto('/workspace');
    await expect(page.locator('text=🔍 搜索')).toBeVisible();
    // React Flow canvas should be present
    await expect(page.locator('.react-flow')).toBeVisible();
  });
});
