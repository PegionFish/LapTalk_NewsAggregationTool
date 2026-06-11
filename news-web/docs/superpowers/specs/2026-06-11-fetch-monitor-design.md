# 数据采集状态监控 — 设计规格

**日期:** 2026-06-11  
**状态:** 已批准  
**范围:** 后端 API + 前端页面 + 数据库迁移

---

## 1. 目标

为新闻抓取与缓存系统提供详细的状态展示和控制能力，包括：
- 每个 RSS 源 / 平台热榜的抓取状态、成功率、历史趋势
- 文章缓存生命周期管理（待下载 → 已缓存 → 已提取文本 → 已翻译）
- 源级别和单篇级别的失败重试能力
- 抓取历史持久化到 DB，支持趋势追溯

## 2. 数据模型

### 2.1 新建表 `fetch_logs`

```sql
CREATE TABLE IF NOT EXISTS fetch_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name     TEXT    NOT NULL,
    source_type     TEXT    NOT NULL,   -- 'rss' | 'hotlist' | 'bilibili'
    articles_fetched INTEGER DEFAULT 0,
    articles_new    INTEGER DEFAULT 0,
    status          TEXT    DEFAULT 'ok',  -- 'ok' | 'partial' | 'failed'
    error_msg       TEXT,
    duration_ms     INTEGER,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    run_type        TEXT    DEFAULT 'scheduled'  -- 'scheduled' | 'manual'
);

CREATE INDEX IF NOT EXISTS idx_fetch_logs_source ON fetch_logs(source_name, started_at);
CREATE INDEX IF NOT EXISTS idx_fetch_logs_type ON fetch_logs(source_type, started_at);
```

### 2.2 复用现有字段

articles 表已有缓存相关字段，无需改表：
- `content_status` — 'pending' | 'fetched' | 'translated' | 'failed'
- `local_path` — 空=未下载, `[ERR:...]`=下载失败, 其他=文件路径
- `content_fetched_at` — 下载时间
- `text_content` / `translated_content` — 文本/译文

## 3. 后端 API

### 3.1 模块：`api/fetch.py`（新建）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/fetch/overview` | GET | 总览统计 |
| `/api/fetch/sources` | GET | 所有源的详情列表 |
| `/api/fetch/sources/{name}/history` | GET | 单源历史（支持 `?days=7`） |
| `/api/fetch/sources/{name}/retry` | POST | 单源重抓 |
| `/api/fetch/sources/{name}/articles` | GET | 该源文章列表（分页+状态筛选） |
| `/api/fetch/articles/{id}/retry-cache` | POST | 单篇缓存重试 |
| `/api/fetch/articles/batch-retry` | POST | 批量缓存重试（body: `{ids: [...]}`, max 50） |
| `/api/fetch/articles/failed` | GET | 失败文章分页列表 |

### 3.2 关键端点响应

**`GET /api/fetch/overview`**
```json
{
  "rss": {
    "total_sources": 40,
    "healthy": 35, "degraded": 3, "failing": 2,
    "last_run": "2026-06-11T10:00:00",
    "articles_today": 287
  },
  "hotlist": {
    "total_sources": 4,
    "healthy": 4,
    "last_run": "...",
    "items_today": 200
  },
  "cache": {
    "total_articles": 15000,
    "cached": 12000,
    "pending": 2500,
    "failed": 500,
    "cached_pct": 80.0
  }
}
```

**`GET /api/fetch/sources`**
```json
{
  "sources": [
    {
      "name": "Ars Technica",
      "type": "rss",
      "health": "healthy",
      "last_fetch": "2026-06-11T10:00:05",
      "last_status": "ok",
      "total_articles": 1234,
      "cached_articles": 1100,
      "failed_articles": 12,
      "success_rate_5": 1.0
    }
  ]
}
```

### 3.3 源健康评分规则

基于最近 5 次 fetch_logs 记录：
- **healthy**: success_rate = 100%
- **degraded**: success_rate ≥ 60%
- **failing**: success_rate < 60%，或连续 3 次 `status='failed'`

新源（无历史记录）默认为 `healthy`。

## 4. 前端页面

### 4.1 路由与入口

- 路由: `/fetch`
- NavSidebar 新增入口: 📡 数据采集 (`fa-satellite-dish`)
- 页面组件: `pages/FetchMonitor.tsx`

### 4.2 页面布局（4 个区块，自上而下）

**区块 1 — 总览栏**
- 4-6 个统计卡片横向排列
- RSS 健康度（healthy/degraded/failing 数字）
- 缓存覆盖率（进度条 + 百分比）
- 今日新增文章数
- 待处理/失败缓存数

**区块 2 — 源列表（可展开表格）**
- 列: 源名称 | 类型(RSS/热榜/B站) | 最近抓取时间 | 抓取数 | 新增数 | 状态徽章(绿/黄/红) | 成功率 | 操作
- 展开行: 最近 5 次抓取历史 + 「查看该源文章」按钮 + 「重新抓取」按钮
- 支持按源类型筛选（全部/RSS/平台热榜/B站）

**区块 3 — 缓存文章列表**
- 顶部筛选: 按源下拉框 + 状态筛选（全部/待下载/已缓存/下载失败/已翻译）
- 表格列: ID | 标题(可点击跳转) | 来源 | 缓存状态徽章 | 下载时间 | 操作按钮
- 行操作: 「重试下载」「重新翻译」
- 多选 checkbox + 顶部「批量重试」按钮（限制 50 篇）
- 分页加载

**区块 4 — 最近抓取日志**
- 终端风格日志窗（复用 Dashboard LogPanel 样式）
- 显示最近 50 条 fetch_logs 记录
- 格式: `[10:00:05] BBC Technology ✅ 23 条, +5 新增 · 1.2s`
- 失败标记为红色

## 5. 实现路线

### 5.1 Pipeline 日志记录

在 `run_all.py` 的每个 subprocess 步骤执行后：
1. 解析 stdout 提取统计数字（`总条目:` / `科技相关:` 等）
2. 写入 `fetch_logs` 表记录每次抓取结果
3. 失败时记录 error_msg

### 5.2 源重试

`POST /api/fetch/sources/{name}/retry`:
- 在后台线程中针对单个 RSS 源调用 `fetch_feed()` → `db.save_articles()`
- 写入 `fetch_logs` (run_type='manual')
- 如果已有手动任务在运行则拒绝

### 5.3 缓存重试

`POST /api/fetch/articles/{id}/retry-cache`:
- 抽取 `fetch_content.py` 中的下载+清洗+提取流程为可单篇调用的函数
- 后台执行，清除旧 `[ERR:...]` 标记，更新 `content_status`

### 5.4 批量重试限制

单次最多 50 篇，返回 `{"ok": true, "total": 50}`，并启动后台任务逐一处理。

## 6. 变更文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/db/news_db.py` | 修改 | 新增 fetch_logs CRUD 方法 |
| `backend/db/migrations.py` | 修改 | 幂等迁移：建 fetch_logs 表 |
| `backend/api/fetch.py` | 新建 | 8 个 API 端点 + 后台任务 |
| `backend/main.py` | 修改 | 注册 fetch_router |
| `backend/pipeline/run_all.py` | 修改 | step 后写 fetch_logs |
| `backend/scheduler.py` | 修改 | 为 fetch_logs 提供 run_type |
| `frontend/src/pages/FetchMonitor.tsx` | 新建 | 主页面 (4 区块) |
| `frontend/src/api/client.ts` | 修改 | 新增 fetch API 封装 |
| `frontend/src/App.tsx` | 修改 | /fetch 路由 |
| `frontend/src/components/NavSidebar.tsx` | 修改 | 导航入口 |
| `tests/backend/test_api.py` | 修改 | 8 个新测试用例 |

## 7. 错误处理

| 场景 | 处理策略 |
|------|---------|
| fetch_logs 表为空（新系统首次启动） | overview 返回全 0 统计，源列表从 RSS_FEEDS 配置派生 |
| 源 URL 已失效（连续 7 天失败） | 前端标记 failing + 红色，hover 提示 |
| 重试后仍失败 | 保留 `[ERR:...]` 标记，更新 content_fetched_at 为重试时间 |
| 源正在重试中 | 返回 `{"ok": false, "message": "该源正在抓取中"}` |
| 批量重试超过 50 篇 | 返回 400 `{"error": "batch_limit_exceeded", "max": 50}` |
| 数据库未配置 | 返回 `{"error": "database_not_configured"}` |

## 8. 测试计划

### 后端 (pytest, +8 用例)
1. overview 返回正确四级统计结构
2. sources 列表返回所有源及健康状态
3. 单源历史按 days 参数正确筛选
4. 重试不存在的源返回 404
5. 源文章列表筛选 + 分页正确
6. 单篇缓存重试成功触发后台任务
7. 批量重试超过 50 篇返回错误
8. 失败文章列表分页正确

### 前端 (Vitest, +3 用例)
1. 页面加载后总览卡片正确渲染
2. 源列表行展开/收起交互
3. 批量选择 + 重试按钮启用/禁用逻辑
