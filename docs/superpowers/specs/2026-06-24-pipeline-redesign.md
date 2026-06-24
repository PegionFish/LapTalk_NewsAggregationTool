# 内容抓取-处理管线重构设计

## 1. 管线总览

### 日夜分工

```
白天（10:00 / 17:00）— 轻量采集
  RSS 抓取 → AI 标题快速筛选 → 主流源立即缓存 HTML / 反爬源仅入库元数据
  缓存完成后即时触发: 清洗 → 翻译 → 分析+KCS

凌晨（1:00）— 事件级批量处理
  事件聚类 → 事件摘要 → 逻辑链构建
```

### 核心原则

- **文章级任务即时执行**：缓存完成后立即清洗→翻译→分析+KCS，不等定时窗口
- **事件级任务定时批量**：依赖全局数据，凌晨统一跑
- **线性阶段串行**：简化架构，无需并行锁和 `_run_seq` 循环
- **管理员可在仪表盘随时手动触发任意阶段**

---

## 2. 数据模型

### 层级关系

```
逻辑链 (Logic Chain)
  └── 事件 (Event) — 同一话题的一簇文章，含摘要和优先级
        └── 文章 (Article) — 单篇新闻报道
              ├── 标题、来源、发布日期
              ├── 优先级评分 (priority_score / priority_label)
              ├── AI 关键词 (ai_keywords)
              ├── AI 分类 (ai_category / ai_tags)
              ├── AI 摘要 (ai_summary)
              ├── 原始 HTML (local_path → 磁盘文件)
              ├── 清洗后正文 (ai_cleaned_content)
              └── 翻译后正文 (translated_content)
```

- 事件可属于多个逻辑链（`chain_events` 的 UNIQUE(chain_id, event_id) 已支持）
- 每篇文章只属于一个事件
- HTML 内容存磁盘文件，DB 只存 `local_path` 路径；前端通过 iframe 加载本地文件
- AI 管线从磁盘读取 HTML 进行处理

### 表结构（不变，仅梳理）

```
articles                        events
──────                          ──────
id (PK)                         id (PK)
title                           title
source                          article_count
url                             first_seen / last_seen
published_date                  status (active)
fetched_at                      ai_summary
local_path (磁盘路径)            priority_label
text_content (原始HTML, 过渡期)
translated_content              chain_events
ai_cleaned_content              ──────────
ai_summary                      chain_id (FK → logic_chains)
ai_keywords                     event_id (FK → events)
ai_category / ai_tags           position (时间顺序)
priority_score / priority_label note (AI 关联理由)
content_status                  UNIQUE(chain_id, event_id)
ai_filtered (1=通过, -1=拒绝)
human_processed                 logic_chains
                                ───────────
news_article_events             id (PK)
──────────────                  title
article_id (FK)                 description
event_id (FK)                   created_at / updated_at
                                created_by (auto|human)

                                chain_relations
                                ──────────────
                                parent_chain_id (FK)
                                child_chain_id (FK)
                                position
```

---

## 3. 管线阶段定义

### 文章级（即时执行）

| 阶段 | 输入 | 输出 | 模型分组 |
|------|------|------|---------|
| 标题初筛 | RSS 标题列表 | ai_filtered=1/-1 | 标题初筛 |
| 内容缓存 | URL | local_path (磁盘HTML) | — |
| 内容清洗 | HTML (磁盘文件) | ai_cleaned_content | 文章处理 |
| 翻译 | HTML (磁盘文件) | translated_content | 文章处理 |
| 分析+KCS | 清洗后正文 | ai_summary + ai_keywords + ai_category + ai_tags + priority_score/label | 文章处理 |

分析+KCS 为单次 API 调用，合并原有的三个独立步骤。

### 事件级（凌晨 1:00 / 手动触发）

| 阶段 | 输入 | 输出 | 模型分组 |
|------|------|------|---------|
| 事件聚类 | 文章标题+摘要 | news_article_events 关联 | 事件管线 |
| 事件摘要 | 事件下所有文章标题 | events.ai_summary | 事件管线 |
| 逻辑链构建 | 全景图（全部事件+文章+评分+关键词） | logic_chains + chain_events | 事件管线 |

逻辑链构建输入包含每篇文章的标题、发布日期、优先级评分，AI 按时间线和主题关联度分组。

---

## 4. API 设计

### 文章管线 (`api/pipeline_article.py`)

```
POST /api/pipeline/article/{id}/process      单篇完整处理
POST /api/pipeline/article/batch-process     批量处理全部待处理文章
GET  /api/pipeline/article/status            处理进度
```

### 事件管线 (`api/pipeline_event.py`)

```
POST /api/pipeline/event/nightly             全量事件管线（聚类→摘要→逻辑链）
GET  /api/pipeline/event/status              进度（steps 数组）

独立操作（管理员仪表盘手动触发）:
POST /api/pipeline/event/recluster           事件重聚类
POST /api/pipeline/event/summarize           事件摘要生成
POST /api/pipeline/event/build-chains        逻辑链构建
GET  /api/pipeline/event/{op}/status         各操作状态
```

### 调度

```
GET  /api/fetch/schedule                     读取定时配置
PUT  /api/fetch/schedule                     保存定时配置
POST /api/fetch/schedule/toggle              开关定时任务
```

### 旧端点

以下端点不再暴露，逻辑合并入统一管线：
`batch-translate`, `batch-analyze`, `batch-keywords`, `batch-classify`, `batch-score`, `batch-clean`, `batch-recluster`, `batch-summarize-events`, `batch-rank-events`, `batch-ai-full`, `batch-kcs`, `batch-ai-filter`

---

## 5. AI 服务配置三段式

### 设置页面结构

```
┌─ 标题初筛 ─────────────────────────────────────┐
│ 模型: [▼]   Base URL: [▼]   API Key: [●●●●]    │
│ ☑ enable_thinking   [连通性测试]                 │
├─ 文章处理 (清洗·翻译·分析+KCS) ──────────────────│
│ 模型: [▼]   Base URL: [▼]   API Key: [●●●●]    │
│ ☑ enable_thinking   thinking_budget: [32768]    │
├─ 事件管线 (聚类·摘要·逻辑链) ────────────────────│
│ 模型: [▼]   Base URL: [▼]   API Key: [●●●●]    │
│ ☑ enable_thinking   thinking_budget: [32768]    │
└─────────────────────────────────────────────────┘
```

### 后端 endpoint 映射

| 设置分组 | 用途 |
|---------|------|
| 标题初筛 | RSS 标题 AI 筛选 |
| 文章处理 | 清洗 + 翻译 + 分析+KCS（共用同一模型配置）|
| 事件管线 | 聚类 + 摘要 + 逻辑链（共用同一模型配置）|

`keyword_extraction`、`article_classification`、`priority_scoring`、`event_ranking` 等旧独立 endpoint 废弃，合并到上述三组。

### Preset 机制（后续实现）

为常用模型预置推荐参数，用户选择 Preset 后自动填入 model_id、context_limit、enable_thinking 等，只需配 Base URL 和 API Key。首个版本按 DeepSeek V4 Flash 构建。

---

## 6. 前端改造

### Dashboard 操作区

```
┌─ 📰 文章处理 ───────────────────────────────────┐
│ [一键处理全部]   进度: ████████░░  142/150       │
│ 单篇处理 · 缓存→清洗→翻译→分析+KCS               │
└─────────────────────────────────────────────────┘

┌─ 🔗 事件管线 ───────────────────────────────────┐
│ [启动事件管线]   步骤: ✅聚类 ✅摘要 ⏳逻辑链       │
│ 独立操作: [重聚类] [生成摘要] [构建逻辑链]         │
└─────────────────────────────────────────────────┘
```

- 移除当前 10+ 张独立 AICard
- ArticleSearch 增加单篇"处理"按钮

### 逻辑链面板（保持）

- ChainList + Workspace（React Flow 拖拽编辑）保持不变
- 增加时间轴视图：以 `published_date` 排序链内事件
- 事件详情面板展示"所属逻辑链"列表

---

## 7. 后端文件重构

```
api/
├── pipeline_article.py     # 新增：文章级管线端点+逻辑
├── pipeline_event.py       # 新增：事件级管线端点+逻辑
├── pipeline.py             # 删除，逻辑已迁移
├── chains.py               # 保留
└── ...

pipeline/
├── ai_filter.py            # 保留
├── process_article.py      # 新增：单篇处理编排
├── analyze.py              # 精简：仅事件级分析
└── ...

utils/
├── task_state.py           # 保留（修复 DB 连接 bug）
└── ...
```

`api/pipeline.py`（当前 1735 行）拆为 `pipeline_article.py` + `pipeline_event.py`，各约 300-400 行。

---

## 8. 测试

- 当前 `test_api.py`（31 用例）拆为：
  - `test_pipeline_article.py` — 文章处理相关
  - `test_pipeline_event.py` — 事件管线相关
  - `test_api.py` — 其余端点（auth, stats, settings 等）
- 旧独立端点测试用例逻辑适配到新端点
- 修复 4 个预先存在的失败用例

---

## 9. 验证方法

1. `python -m pytest tests/ -v` — 全部测试通过
2. `npm run build` — 前端编译无错误
3. RSS 抓取 → 标题筛选 → 缓存 → 即时处理 → 前端确认文章出现
4. 事件管线触发 → 逻辑链面板确认链自动生成
5. 逻辑链面板手动编辑/拖拽 → 确认用户编辑功能正常
