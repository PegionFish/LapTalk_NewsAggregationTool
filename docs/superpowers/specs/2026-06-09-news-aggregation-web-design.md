# News Aggregation Web — 知识聚合中心设计文档

## Overview

基于 `claw_skill_news_aggregation` 新闻搜集 Skill 的知识聚合中心 Web 应用。Web 端直接集成新闻抓取 Pipeline（无需 Hermes/OpenClaw），通过 APScheduler 定时执行（每天 10:00/17:00），让局域网用户搜索、审查、关联新闻事件，构建逻辑链。

**目标用户：** 局域网内多名成员（基于 QNAP NAS 账户体系的认证将在后续版本接入）
**部署目标：** Mac / Linux 主机
**架构变更：** 不再依赖 Hermes/OpenClaw 节点 — Pipeline 作为后台任务集成在 FastAPI 进程中

---

## 1. 四层数据模型

```
新闻块 (Article)          ← 搜索的最小单元，从 Skill 数据库读取
  │ 属于
事件 (Event)              ← AI 聚类，同一主题的新闻集合
  │ 属于
逻辑链 (Logic Chain)      ← 事件按时间线排列的叙事线索
  │ 拼接
上级逻辑链 (Parent Chain) ← 多条子链汇聚为完整生命周期
```

### 1.1 新增表：logic_chains

```sql
CREATE TABLE logic_chains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    created_by  TEXT DEFAULT 'human'
);

CREATE TABLE chain_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER NOT NULL REFERENCES logic_chains(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id),
    position INTEGER NOT NULL,
    note     TEXT DEFAULT '',
    UNIQUE(chain_id, event_id)
);

CREATE TABLE chain_relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_chain_id INTEGER NOT NULL REFERENCES logic_chains(id) ON DELETE CASCADE,
    child_chain_id  INTEGER NOT NULL REFERENCES logic_chains(id),
    position        INTEGER NOT NULL,
    UNIQUE(parent_chain_id, child_chain_id)
);
```

`chain_relations` 实现链拼接。例如父链"RTX 5090 全生命周期"包含子链"禁售风波"（position=0）和"缺ROPS缺陷"（position=1）。应用层遍历 chain_relations 获取子链顺序，再合并子链的 chain_events 得到完整事件序列。数据库层面不存冗余的层级路径。

`chain_events` 的 ON DELETE CASCADE 确保删除链时自动清理关联记录。`chain_relations` 同理。

### 1.2 现有 Schema（Skill 侧，Web 端只读 + 写入 feedback 相关表）

- `articles` — 新闻条目（含 keywords, priority_score, priority_label, human_verified, human_tags）
- `events` — 聚类事件（含 title, first_seen, last_seen, article_count）
- `article_events` — 多对多关联
- `human_feedback` — 人工反馈记录
- `event_relations` — 事件间关系（before/after/update/spawn/related, created_by=human|auto）

---

## 2. 技术架构

### 2.1 方案选择：前后端分离

| 层 | 技术 | 理由 |
|----|------|------|
| 后端 | Python FastAPI | 直接复用 news_db.py ORM，零改动数据层 |
| 前端 | React + Vite + React Flow | React Flow 原生支持拖拽节点、连线、缩放平移 |
| 数据库 | SQLite (WAL 模式) | Skill 写入与 Web 读取并发安全 |
| 配置 | JSON 文件 | 与 Web 应用同级目录 |

### 2.2 目录结构

```
news-web/
├── backend/
│   ├── main.py              # FastAPI 入口 + CORS + 生命周期 + 调度启动
│   ├── config.py            # 动态 DB/UA/OpenAI 配置管理
│   ├── scheduler.py         # APScheduler 定时任务 (10:00 / 17:00)
│   ├── ai_client.py         # OpenAI 兼容 API 客户端
│   ├── api/
│   │   ├── articles.py      # 文章列表/搜索/审核
│   │   ├── events.py        # 事件 CRUD/合并/拆分
│   │   ├── chains.py        # 逻辑链 CRUD/拼接/拆分
│   │   ├── relations.py     # 事件关系（含 AI 推荐确认/拒绝）
│   │   ├── stats.py         # 仪表盘统计
│   │   └── settings.py      # 设置面板
│   ├── db/
│   │   ├── news_db.py       # 从 Skill 仓库同步的 ORM 层
│   │   └── migrations.py    # 新增表（logic_chains 等）迁移
│   ├── pipeline/            # 从 Skill 仓库同步的抓取分析脚本
│   │   ├── run_all.py       # 编排整个流程
│   │   ├── fetch_english_news.py
│   │   ├── collect_data.py
│   │   ├── fetch_content.py
│   │   └── analyze.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Workspace.tsx       # 逻辑链工作台（核心页面）
│   │   │   ├── ArticleSearch.tsx   # 文章检索
│   │   │   ├── ChainList.tsx       # 逻辑链列表
│   │   │   └── Settings.tsx        # 含 DB/AI/抓取调度配置
│   │   ├── components/
│   │   │   ├── SearchPanel.tsx     # 左栏搜索面板
│   │   │   ├── EventCard.tsx       # 事件容器块
│   │   │   ├── ArticleBlock.tsx    # 新闻块
│   │   │   ├── ChainCanvas.tsx     # React Flow 画布
│   │   │   ├── RelationDialog.tsx  # 连线时弹出关系选择
│   │   │   ├── NavSidebar.tsx
│   │   │   └── DashboardCards.tsx
│   │   ├── api/
│   │   │   └── client.ts
│   │   ├── types/
│   │   │   └── index.ts           # TypeScript 类型定义
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
└── config.json                # 运行时配置（DB路径、UA、OpenAI、调度开关）
```

### 2.3 数据流

```
Pipeline 定时抓取 (APScheduler 10:00/17:00)
  → fetch_english_news.py → RSS 40源
  → collect_data.py → 去重聚类 → SQLite
  → AI 分析 (通过 OpenAI 兼容 API 调用)
       ↓
Web 后端 (FastAPI) ← import news_db.py → 读取/写入 DB
       ↓  REST API
Web 前端 (React + React Flow)
```

- `news_db.py` 作为 ORM 层直接包含在 Web 项目中，随包分发
- 后端通过 config.py 动态设置 DB 路径，通过 `PRAGMA journal_mode=WAL` 打开连接
- AI 分析可通过任何 OpenAI 兼容端点（OpenAI、DeepSeek、Ollama 等）
- Pipeline 运行在独立的子进程中，不阻塞 API 响应

---

## 3. 页面设计

### 3.1 侧边栏导航

| 导航项 | 页面 | 说明 |
|--------|------|------|
| 📊 仪表盘 | Dashboard | 统计概览 |
| 🖱 逻辑链工作台 | Workspace | 核心页面：搜索 → 拖拽 → 关联 |
| 📄 文章检索 | ArticleSearch | 精确查询新闻 |
| 📋 逻辑链列表 | ChainList | 浏览已有链 |
| ⚙ 设置 | Settings | 配置管理 |

### 3.2 逻辑链工作台（核心页面）

两栏布局：

**左栏 — 搜索面板：**
- 搜索框支持关键词、来源、日期范围筛选
- 搜索结果以 **新闻块** 展示，每条新闻标注所属事件名称
- 每个新闻块可拖拽（HTML5 Drag API / 触摸事件）
- 筛选预设：今天 / 最近 3 天 / 最近 7 天

**主区域 — React Flow 画布：**
- 自由拖拽、缩放、平移
- 新闻块拖入画布后自动按事件聚合（算法层在后端完成）
- **事件容器**可视化——显示事件标题、优先级、旗下新闻列表
- 事件容器之间可拖出连线，连线时弹出关系类型选择（before/after/update/spawn/related）
- AI 自动推荐的关系显示为虚线，点击确认变为实线

### 3.3 逻辑链操作

- **搜索创建链**：搜索关键词 → 点击"创建逻辑链" → 自动收集相关事件按时间排列
- **链拼接**：两条链在画布上选中 → 点击"拼接" → 选择顺序 → 形成上级逻辑链
- **链拆分**：从某事件处拆分 → 一分为二
- **链内编排**：拖拽事件容器调整顺序

### 3.4 仪表盘

- 统计卡片：总文章数、活跃事件数、待审核数、今日新增
- 来源分布图、优先级分布图
- 最近反馈列表

### 3.5 文章检索

- 关键词 / 来源 / 日期范围 / 优先级 / 审核状态多维筛选
- 结果以表格形式展示
- 点击某行 → 跳转到该文章所属事件 → 在逻辑链工作台中定位

### 3.6 设置面板

- 数据库路径（本地路径或 NAS 共享挂载点）
- AI 配置：API 地址（OpenAI 兼容）、API Key、模型名称
- 默认 User-Agent（Pipeline 抓取时模拟浏览器 + 打开原文时携带）
- Pipeline 调度开关（启用/禁用定时抓取）
- 配置保存到 `config.json`（与 Web 应用同级）

---

## 4. API 端点

### 4.1 统计
```
GET /api/stats → { articles, events, active_events, human_verified, by_category }
```

### 4.2 文章
```
GET    /api/articles?q=&source=&date_from=&date_to=&priority=&verified=&page=&limit=
GET    /api/articles/:id
PATCH  /api/articles/:id  → { priority_label?, human_tags?, human_verified? }
GET    /api/articles/:id/content  → 代理获取原文（携带配置的 UA）
```

### 4.3 事件
```
GET    /api/events?status=&min_articles=&page=&limit=
GET    /api/events/:id  → 包括旗下文章列表 + 关联事件
PATCH  /api/events/:id  → { title?, priority_label? }
POST   /api/events/:id/merge → { target_event_id }
POST   /api/events/:id/split → { article_ids[] }
```

### 4.4 逻辑链
```
GET    /api/chains
POST   /api/chains  → { title, event_ids[]? }
GET    /api/chains/:id  → 链详情（含事件树、子链）
PATCH  /api/chains/:id  → { title?, description? }
DELETE /api/chains/:id
POST   /api/chains/:id/splice → { child_chain_ids[] }  # 拼接子链
POST   /api/chains/:id/split  → { at_event_id }        # 从某事件处拆分
POST   /api/chains/:id/reorder → { event_ids[] }       # 重排事件顺序
```

### 4.5 事件关系
```
GET    /api/relations/suggested → AI 推荐的关系列表
POST   /api/relations/:id/confirm
DELETE /api/relations/:id
POST   /api/relations  → { from_event_id, to_event_id, relation }
```

### 4.6 设置
```
GET  /api/settings
PUT  /api/settings  → { db_path?, user_agent?, openai_base_url?, openai_api_key?, openai_model?, pipeline_schedule_enabled? }
```

### 4.7 Pipeline
```
POST /api/pipeline/run  → 手动触发一次完整抓取
```

---

## 5. 工作流

### 5.1 每日使用场景

1. 用户打开 Web 应用 → 仪表盘看到今日新增数量
2. 进入逻辑链工作台 → 搜索关键词 → 浏览最新新闻块
3. 将相关新闻块拖入画布 → 自动按事件聚合
4. 审查 AI 聚类结果：确认事件、拆分/合并事件、调整优先级
5. 在事件之间拖出连线 → 选择关系类型 → 构建逻辑链
6. AI 推荐的关系以虚线显示 → 点击确认或忽略
7. 通过链拼接将多条子链汇聚为完整生命周期叙事

### 5.2 人工 vs AI 分工

| 工作 | 执行者 | 说明 |
|------|--------|------|
| 新闻抓取 | Skill | 定时 RSS + 平台热榜 |
| 聚类成事件 | AI | 标题相似度 + 实体重叠 |
| 优先级评分 | AI | 5维评分（可人工覆盖） |
| 事件关系推荐 | AI | 关键字 + 时间计算 |
| **确认聚类** | **人工** | 一键确认 / 拆分 / 合并 |
| **调优先级** | **人工** | 覆盖 AI 评分 |
| **打标签** | **人工** | 添加自定义标签 |
| **确认关系** | **人工** | 确认或拒绝 AI 推荐 |
| **创建逻辑链** | **人工** | 搜索 → 创建 → 拖拽编排 |

---

## 6. 错误处理与边界情况

### 6.1 数据库不可用
- 后端启动时检查 DB 路径是否存在，不存在时返回友好错误
- 设置面板可随时切换 DB 路径，切换后自动重连
- API 返回统一的 `{"error": "database_not_found", "message": "..."}` 格式

### 6.2 并发读写
- WAL 模式确保 Skill 写入不阻塞 Web 读取
- 如检测到数据库被锁定，自动重试（最多 3 次，间隔 100ms）

### 6.3 搜索边界
- 搜索词为空时返回最近文章
- 搜索结果超过 500 条时分页
- 日期范围无效时忽略该筛选项

### 6.4 事件操作安全
- 拆分事件时，如果目标文章少于 2 篇，拒绝拆分
- 合并事件时，合并后的事件覆盖两个事件的日期范围
- 删除逻辑链时，其包含的事件和新闻不受影响（CASCADE 只删关联记录）

---

## 7. 测试策略

- **后端单元测试**：pytest，mock news_db.py 的数据库操作
- **API 集成测试**：使用测试 SQLite 数据库，覆盖所有端点
- **前端组件测试**：Vitest + React Testing Library，覆盖核心交互组件
- **端到端测试**：Playwright，覆盖核心工作流（搜索 → 拖拽 → 连线）

---

## 8. 后续规划

1. **Phase 1**（当前设计）：基础架构 + 核心工作流
2. **Phase 2**：用户认证集成（QNAP NAS LDAP / SSO）
3. **Phase 3**：多用户操作日志与协作
4. **Phase 4**：通知推送（事件更新提醒、待审查提醒）
