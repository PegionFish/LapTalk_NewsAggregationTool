# 新闻知识聚合中心 — LapTalk News Aggregation

基于 `claw_skill_news_aggregation` 新闻抓取 Skill 的知识聚合中心 Web 应用。自动从 40+ RSS 源抓取英文科技新闻，AI 聚类分析后构建事件逻辑链，提供拖拽式可视化工作台供人工审查、关联和编排。

## 快速开始

```bash
# 1. 安装依赖
cd news-web/backend && pip install -r requirements.txt
cd ../frontend && npm install

# 2. 配置
# 编辑 news-web/config.json，填写 db_path 和 openai_api_key

# 3. 启动（开发模式）
cd ../backend && python main.py          # 后端 → :8080
cd ../frontend && npm run dev            # 前端 → :3000 (代理到 :8080)

# 4. 生产部署
chmod +x run_prod.sh && ./run_prod.sh   # 构建前端 + 启动后端 → :8080
```

## 技术架构

```
浏览器 (React + React Flow)
  ↕ REST API
FastAPI (:8080)
  ├── APScheduler → 定时抓取 (10:00 / 17:00)
  ├── SQLite (WAL 模式) → 读写分离
  └── OpenAI 兼容 API → AI 事件分析

Pipeline 子进程:
  RSS 抓取 → 去重聚类 → 页面归档 → AI 分析
```

| 层 | 技术栈 |
|----|--------|
| 后端 | Python 3.11+, FastAPI, SQLite, APScheduler, bcrypt, PyJWT, openai |
| 前端 | React 18, Vite 5, TypeScript, React Router 6, React Flow (xyflow 12) |
| 测试 | pytest (后端 29 用例), Vitest + Testing Library (前端 16 用例), Playwright (E2E 5 用例) |
| 部署 | systemd (Linux), launchd (macOS), run_prod.sh |

## 项目结构

```
news-web/
├── backend/
│   ├── main.py              # FastAPI 入口 + CORS + 路由注册 + 静态文件挂载
│   ├── config.py            # 动态配置管理 (config.json)
│   ├── scheduler.py         # APScheduler 定时任务 (抓取 + 备份)
│   ├── ai_client.py         # OpenAI 兼容 API 客户端封装
│   ├── auth/                # 用户认证 (bcrypt + JWT)
│   │   ├── auth.py          # 密码哈希、Token 签发/验证、Depends 注入
│   │   └── models.py        # users 表定义与迁移
│   ├── api/
│   │   ├── settings.py      # GET/PUT /api/settings
│   │   ├── stats.py         # GET /api/stats (仪表盘统计)
│   │   ├── articles.py      # 文章搜索/详情/更新/原文代理 + 分类筛选/排序/低分清理
│   │   ├── comments.py      # 文章多级评语 (CRUD + 点赞)
│   │   ├── events.py        # 事件 CRUD/合并/拆分
│   │   ├── chains.py        # 逻辑链 CRUD/拼接/拆分/重排/递归时间线
│   │   ├── relations.py     # 事件关系 (推荐/确认/拒绝/批量查询)
│   │   ├── auth.py          # POST 登录/注册, GET 当前用户
│   │   ├── audit.py         # GET 审计日志
│   │   └── notifications.py # 通知偏好/列表/已读标记
│   ├── db/
│   │   ├── news_db.py       # Skill 仓库 ORM 层 (含评语/清理/分类方法)
│   │   ├── migrations.py    # logic_chains + users + audit + 评语/点赞 表迁移
│   │   └── audit.py         # 审计日志写入/查询
│   └── pipeline/
│       ├── run_all.py       # 编排器 (fetch → cluster → archive → AI)
│       ├── fetch_english_news.py  # RSS 40 源抓取
│       ├── collect_data.py        # 去重 + 聚类 + 写入 DB
│       ├── fetch_content.py       # 页面归档
│       └── analyze.py            # AI 事件摘要 + 关系发现
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # 路由 + 鉴权门控 + ErrorBoundary
│   │   ├── contexts/
│   │   │   └── AuthContext.tsx  # JWT 持久化 + 登录/注册/登出
│   │   ├── hooks/
│   │   │   └── useUndoRedo.ts  # 50 步历史栈 (Ctrl+Z / Ctrl+Shift+Z)
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx     # 📊 统计卡片 + 来源分布
│   │   │   ├── Workspace.tsx     # 核心工作台 (搜索栏 + 画布)
│   │   │   ├── ArticleSearch.tsx # 📄 多维度文章检索 + 分类Tab + 排序 + 评语面板
│   │   │   ├── ChainList.tsx     # 📋 逻辑链列表
│   │   │   ├── Settings.tsx      # ⚙ 数据库/AI/调度配置
│   │   │   └── Login.tsx         # 登录/注册
│   │   ├── components/
│   │   │   ├── ChainCanvas.tsx   # React Flow 画布 (拖放/连线/撤销)
│   │   │   ├── EventCard.tsx     # 事件容器节点
│   │   │   ├── ArticleBlock.tsx  # 可拖拽新闻块
│   │   │   ├── SearchPanel.tsx   # 左栏搜索面板
│   │   │   ├── RelationDialog.tsx # 连线关系选择弹窗
│   │   │   ├── NavSidebar.tsx    # 侧边栏导航 + 用户信息
│   │   │   ├── DashboardCards.tsx # 仪表盘统计卡片
│   │   │   └── CommentPanel.tsx   # 文章审核评语 (树形/回复/点赞)
│   │   ├── api/client.ts     # 全量 API 客户端 (40+ 端点)
│   │   └── types/index.ts    # TypeScript 类型定义
│   ├── e2e/                   # Playwright E2E 测试
│   └── vite.config.ts         # Vite + 代理 + Vitest 配置
├── tests/backend/             # pytest 集成测试 (29 用例)
├── config.json                # 运行时配置
├── run_prod.sh                # 一键生产部署脚本
└── deploy/                    # systemd / launchd 服务模板
```

## 数据模型

```
新闻块 (Article)        ← 搜索最小单元
  │ 属于
事件 (Event)            ← AI 聚类，同主题新闻集合
  │ 属于
逻辑链 (Logic Chain)    ← 事件按时间线排列的叙事线索
  │ 拼接
上级逻辑链 (Parent)     ← 多条子链汇聚为完整生命周期
```

### 14 张数据库表

| 表 | 用途 | Phase |
|----|------|-------|
| `articles` | 新闻条目 (含关键词、优先级、人工标记、主题分类) | 1 |
| `events` | 聚类事件 (含优先级标签) | 1 |
| `article_events` | 文章↔事件多对多关联 | 1 |
| `human_feedback` | 人工反馈历史 | 1 |
| `event_relations` | 事件间关系 (before/after/update/spawn/related) | 1 |
| `logic_chains` | 逻辑链 | 1 |
| `chain_events` | 链↔事件关联 (含位置) | 1 |
| `chain_relations` | 父子链拼接 | 1 |
| `schema_version` | 迁移版本追踪 | 1 |
| `users` | 用户账户 (bcrypt 哈希 + JWT) | 2 |
| `audit_log` | 操作审计日志 | 3 |
| `notifications` + `notification_prefs` | 通知与偏好 | 4 |
| `article_comments` | 文章审核评语 (树形，支持多级回复) | 5 |
| `comment_likes` | 评语点赞 (UNIQUE comment_id+user_id) | 5 |

## 核心工作流

```
1. 定时抓取 (APScheduler 10:00/17:00)
   └→ fetch_english_news.py → RSS 40 源
   └→ collect_data.py        → 去重 + 聚类 + 写入 DB
   └→ fetch_content.py       → 页面归档
   └→ analyze.py             → AI 摘要 + AI 关系发现

2. 用户登录 → 仪表盘 → 查看今日新增

3. 进入工作台 → 搜索关键词 → 拖入画布
   └→ 事件容器自动聚合 → 审查/拆分/合并

4. 事件间拖出连线 → 选择关系类型 → 构建逻辑链

5. 链拼接 → 多子链汇聚为完整叙事
   └→ AI 推荐关系虚线显示 → 确认或忽略

6. Ctrl+Z / Ctrl+Shift+Z 撤销/重做
   └→ 自动草稿保存 (localStorage 2s debounce)

7. 文章详情 → 评语审核
   └→ 发表评语/回复 → 点赞/编辑/删除

8. 仪表盘 → 低分新闻清理
   └→ 设置阈值 → 预览 → 二次确认 → 批量删除
```

## API 端点

### 统计
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/stats` | 文章/事件/审核统计 |

### 文章
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/articles` | 多维度搜索 (关键词/来源/日期/优先级/状态/分类/排序) |
| GET | `/api/articles/categories` | 主题分类统计 (各分类文章数) |
| GET | `/api/articles/cleanup/preview` | 预览低分清理 (?threshold=0.2) |
| POST | `/api/articles/cleanup` | 执行低分清理 {threshold} |
| GET | `/api/articles/:id` | 文章详情 + 所属事件 |
| PATCH | `/api/articles/:id` | 更新优先级/标签/审核状态 |
| GET | `/api/articles/:id/content` | 代理获取原文 + AI摘要 |

### 评语
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/articles/:id/comments` | 文章评语列表 (树形，含点赞数) |
| POST | `/api/articles/:id/comments` | 添加评语/回复 {content, parent_id?} |
| PATCH | `/api/comments/:id` | 编辑评语 (仅作者) |
| DELETE | `/api/comments/:id` | 删除评语 (仅作者，级联子评语) |
| POST | `/api/comments/:id/like` | 点赞/取消点赞 |

### 事件
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events` | 列表 (支持状态/最小文章数筛选) |
| GET | `/api/events/:id` | 详情 + 文章时间线 + 关联事件 |
| PATCH | `/api/events/:id` | 更新标题/优先级 (含级联传播) |
| POST | `/api/events/:id/merge` | 合并事件 → 目标事件 |
| POST | `/api/events/:id/split` | 拆分事件 → 新事件 |

### 逻辑链
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/chains` | 列表 |
| POST | `/api/chains` | 创建 |
| GET | `/api/chains/:id` | 详情 (含事件树 + 子链) |
| PATCH | `/api/chains/:id` | 更新标题/描述 |
| DELETE | `/api/chains/:id` | 删除 (CASCADE) |
| POST | `/api/chains/:id/splice` | 拼接子链 |
| POST | `/api/chains/:id/split` | 从事件处拆分 |
| POST | `/api/chains/:id/reorder` | 重排事件顺序 |
| GET | `/api/chains/:id/timeline` | 递归展开完整时间线 |

### 事件关系
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/relations/suggested` | AI 推荐的关系 (待确认) |
| GET | `/api/relations/between` | 批量查询事件间关系 (画布边重建) |
| POST | `/api/relations/:id/confirm` | 确认 |
| DELETE | `/api/relations/:id` | 拒绝 |
| POST | `/api/relations` | 手动创建 |

### 鉴权与协作
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 (bcrypt) |
| POST | `/api/auth/login` | 登录 (JWT 72h) |
| GET | `/api/auth/me` | 当前用户 |
| GET | `/api/audit` | 操作审计日志 |
| GET | `/api/notifications` | 通知列表 (支持仅未读) |
| GET/PUT | `/api/notifications/prefs` | 通知偏好 |
| POST | `/api/notifications/:id/read` | 标记已读 |
| POST | `/api/notifications/read-all` | 全部已读 |

### 配置与调度
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/api/settings` | 数据库/AI/调度配置 |
| POST | `/api/pipeline/run` | 手动触发抓取 |
| GET | `/api/pipeline/status` | 当前任务状态 |

## 测试

```bash
# 后端 (29 用例)
python -m pytest news-web/tests/backend/test_api.py -v

# 前端单元 (16 用例)
cd news-web/frontend && npm test

# E2E (5 用例)
cd news-web/frontend && npx playwright test
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JWT_SECRET` | `news-web-dev-secret-...` | 生产环境必须覆盖 |
| `NEWS_DB_PATH` | (config.json) | Pipeline 子进程的 DB 路径 |
| `NEWS_WEB_TESTING` | 未设置 | 设置后禁用调度器 (测试用) |

## Phase 路线图

- **Phase 1** ✅ 基础架构 + 核心工作流 (28 端点)
- **Phase 1 延期项** ✅ 撤销/重做 + 边重建 + 组件测试 + E2E
- **Phase 2** ✅ 用户认证 (bcrypt + JWT, 3 端点)
- **Phase 3** ✅ 多用户审计日志 (1 端点)
- **Phase 4** ✅ 通知系统 (5 端点)
- **Phase 5** ✅ 审核评语 + 低分清理 + 分类Tab筛选 + 评分排序 (11 端点)
- **后续** QNAP NAS LDAP/SSO 集成 / WebSocket 实时协作

## 部署

```bash
# 一键部署
./run_prod.sh              # npm build + pip install + uvicorn

# Linux (systemd)
sudo cp deploy/news-web.service /etc/systemd/system/
sudo systemctl enable --now news-web

# macOS (launchd)
cp deploy/com.news-aggregation.web.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.news-aggregation.web.plist
```

详见 `deploy/CHECKLIST.md`。
