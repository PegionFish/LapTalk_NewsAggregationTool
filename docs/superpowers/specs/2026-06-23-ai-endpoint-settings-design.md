---
name: ai-endpoint-settings-design
description: 将设置页 AI 面板重构为入口级 OpenAI 兼容端点配置，支持独立配置与从其他入口导入配置。
metadata:
  type: project
---

# AI 入口级配置设置页设计

## 1. 目标

本次重构的目标是把设置页的 AI 配置从“扁平模型字段”升级为“AI 入口级配置”。每个 AI 调用入口都可以独立配置自己的 OpenAI 兼容端点，包括 API 地址、API Key、模型和高级参数。

设计边界：

- 前端只负责配置 AI 入口，不设计任务链条或流程编排。
- 后端仍通过代码固定 AI 入口的调用路径和自动化流程。
- 每个入口已经是当前规划粒度中最细的 AI 配置单元，后续不应再在设置页中继续拆分流程。
- 支持从其他入口导入配置，减少重复填写。
- thinking、JSON 输出、目标语言等能力通过入口级勾选或参数配置启用。

## 2. 当前问题

当前设置页和后端配置存在以下问题：

1. 前端只暴露部分 AI 配置，无法良好优化清洗、提取、分析等入口。
2. 配置字段语义偏实现化，例如 `openai_model`、`simple_model`、`clean_model`，用户难以理解对应功能。
3. 不同 AI 入口使用不同模型是明确设计意图，但现有前端表达不清晰。
4. 设置页状态分散，保存时容易漏字段。
5. API Key 掩码、导入配置、连通性测试等行为没有统一抽象。
6. `pipeline_model` 等历史字段容易造成误解，实际代码调用关系需要梳理清楚。

## 3. 目标架构

### 3.1 配置模型

后端新增入口级 AI 配置结构：

```json
{
  "ai_endpoints": {
    "rss_prefilter": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "deepseek-ai/DeepSeek-V3.2",
      "enable_thinking": false,
      "thinking_budget": 32768,
      "json_response_format": true
    },
    "html_clean": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "nex-agi/Nex-N2-Pro",
      "enable_thinking": true,
      "thinking_budget": 32768,
      "max_tokens": 65536
    },
    "translation": {
      "enabled": false,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "deepseek-ai/DeepSeek-V3.2",
      "target_lang": "zh-CN"
    },
    "article_analysis": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "deepseek-ai/DeepSeek-V3.2",
      "enable_thinking": true,
      "thinking_budget": 32768,
      "deep_thinking_max_tokens": 8192
    },
    "event_summary": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "deepseek-ai/DeepSeek-V3.2",
      "enable_thinking": true,
      "thinking_budget": 32768
    },
    "event_ranking": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "deepseek-ai/DeepSeek-V3.2",
      "enable_thinking": true,
      "thinking_budget": 32768,
      "json_response_format": true
    },
    "chain_building": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "deepseek-ai/DeepSeek-V3.2",
      "enable_thinking": true,
      "thinking_budget": 32768,
      "json_response_format": true
    },
    "keyword_extraction": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "Qwen/Qwen3.5-35B-A3B",
      "json_response_format": true
    },
    "article_classification": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "Qwen/Qwen3.5-35B-A3B",
      "json_response_format": true
    },
    "priority_scoring": {
      "enabled": true,
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "***",
      "model": "Qwen/Qwen3.5-35B-A3B",
      "json_response_format": true
    }
  }
}
```

### 3.2 入口列表

当前入口列表按现有 AI 函数入口拆分：

| 入口 key | 中文名称 | 用途 | 当前对应代码/字段 |
|---|---|---|---|
| `rss_prefilter` | RSS 预筛选 | RSS 新闻源或新闻条目的预筛选 | 后续接入，当前需保留入口定义 |
| `html_clean` | HTML 正文清洗 | 从缓存 HTML 提取正文并清理非正文内容 | `ai_client.clean_article_content()` / `config.clean_model` |
| `translation` | 翻译 | 英文科技新闻翻译为中文 | `translation_client.translate_to_chinese()` / `config.translation_model` |
| `article_analysis` | 文章分析 | 单篇文章摘要和分析 | `ai_client.analyze_article()` / `config.openai_model` |
| `event_summary` | 事件摘要 | 事件文章摘要和事件命名 | `ai_client.summarize_events()` / `config.openai_model` |
| `event_ranking` | 全景事件排序 | 全局事件优先级排序 | `ai_client.rank_events_panoramic()` / `config.openai_model` |
| `chain_building` | 逻辑链构建 | 识别事件分组并构建逻辑链 | `ai_client.build_chains_panoramic()` / `config.openai_model` |
| `keyword_extraction` | 关键词提取 | 从标题和正文提取技术关键词 | `ai_client.extract_keywords_ai()` / `config.simple_model` |
| `article_classification` | 文章分类 | 文章主题分类和标签提取 | `ai_client.classify_article_ai()` / `config.simple_model` |
| `priority_scoring` | 优先级评分 | 文章优先级评分 | `ai_client.score_priority_ai()` / `config.openai_model` 或后续改为 `simple_model` |

> 注意：当前代码中 `score_priority_ai()` 未显式传入 `model=config.simple_model`，实际会回落到 `config.openai_model`。实现阶段需要确认是否将评分明确归入提取-分类轨道并使用 `simple_model`，或保留为分析轨道。设计建议是：若评分属于轻量结构化判断，应明确使用 `simple_model`，避免与高质量分析模型混用。

### 3.3 后端职责

新增后端模块：

```text
news-web/backend/ai_config.py
```

职责：

1. 定义入口注册表 `AI_ENDPOINTS`。
2. 将旧扁平配置转换为入口级配置。
3. 将入口级配置写回旧扁平配置。
4. 对 API Key 进行掩码处理。
5. 提供入口级连通性测试能力。

保留旧 `/api/settings` 接口，新增结构化接口：

```text
GET  /api/settings/ai
PUT  /api/settings/ai
POST /api/settings/ai/test
```

`POST /api/settings/ai/test` 请求体：

```json
{
  "endpoint_key": "keyword_extraction",
  "prompt": "返回 JSON：{\"ok\":true}",
  "expected_json": true
}
```

返回：

```json
{
  "ok": true,
  "endpoint_key": "keyword_extraction",
  "model": "Qwen/Qwen3.5-35B-A3B",
  "response": "{\"ok\":true}",
  "elapsed_ms": 1234
}
```

如果入口未启用或 API Key 为空，应返回明确的不可测试原因，而不是调用空端点。

### 3.4 前端职责

重构设置页 AI 面板，不再按“链条”展示，而按“AI 入口”展示。

建议文件结构：

```text
news-web/frontend/src/pages/settings/
├── AISettings.tsx
├── AIEndpointSettings.tsx
├── AIEndpointCard.tsx
├── AIEndpointImportDialog.tsx
├── AIConnectionTest.tsx
└── settings.css
```

入口卡片字段：

- 启用开关
- API 地址
- API Key
- 模型
- 高级参数折叠区
  - 启用 thinking
  - thinking budget
  - 深度输出上限 token
  - 强制 JSON 输出
  - 目标语言
- 测试连接按钮
- 从其他入口导入配置按钮

导入配置行为：

- 源入口和目标入口不能相同。
- 用户可选择导入字段。
- API Key 导入后仍遵循掩码规则。
- 导入只改变当前编辑态，不会立即保存。

## 4. 数据流

### 4.1 加载配置

1. 前端进入设置页。
2. 调用 `GET /api/settings/ai`。
3. 后端读取 `config.json`。
4. 后端通过 `ai_config.py` 转换为入口级配置。
5. API Key 以 `***` 返回。
6. 前端按入口注册表渲染卡片。

### 4.2 保存配置

1. 用户修改入口配置。
2. 前端调用 `PUT /api/settings/ai`。
3. 后端校验入口 key、字段类型和 API Key 掩码。
4. 后端将入口级配置映射回旧扁平字段。
5. 后端保存 `config.json`。
6. 后端返回掩码后的完整入口级配置。
7. 前端刷新本地状态。

### 4.3 测试连接

1. 用户点击某个入口的“测试连接”。
2. 前端调用 `POST /api/settings/ai/test`，传入入口 key。
3. 后端读取该入口当前编辑态或已保存配置。
4. 后端调用对应 OpenAI 兼容接口。
5. 返回成功、响应摘要和耗时。
6. 前端展示成功或失败原因。

### 4.4 导入配置

1. 用户点击目标入口的“从其他入口导入”。
2. 前端弹出导入对话框。
3. 用户选择源入口和导入字段。
4. 前端把源入口字段复制到目标入口编辑态。
5. 用户仍需点击“保存设置”才会持久化。

## 5. 兼容性策略

### 5.1 旧接口保留

保留现有：

```text
GET  /api/settings
PUT  /api/settings
POST /api/settings/test-ai
POST /api/settings/test-translation
```

旧接口继续工作，避免其他页面或外部脚本中断。

### 5.2 旧字段映射

新增入口级配置后，旧字段作为兼容层存在：

| 旧字段 | 映射入口 |
|---|---|
| `openai_base_url` | `article_analysis.base_url`，也可作为分析轨道默认值 |
| `openai_api_key` | `article_analysis.api_key` |
| `openai_model` | `article_analysis.model` |
| `simple_model` | `keyword_extraction.model`、`article_classification.model`，必要时同步 `priority_scoring.model` |
| `clean_base_url` | `html_clean.base_url` |
| `clean_api_key` | `html_clean.api_key` |
| `clean_model` | `html_clean.model` |
| `translation_base_url` | `translation.base_url` |
| `translation_api_key` | `translation.api_key` |
| `translation_model` | `translation.model` |
| `translation_target_lang` | `translation.target_lang` |
| `ai_enable_thinking` | `article_analysis.enable_thinking`，并作为高质量入口默认值 |
| `ai_thinking_budget` | `article_analysis.thinking_budget` |
| `ai_deep_thinking_max_tokens` | `article_analysis.deep_thinking_max_tokens` |
| `ai_json_response_format` | `article_analysis.json_response_format`，结构化入口默认继承 |

### 5.3 默认值规则

- 如果入口级配置不存在，从旧字段推导。
- 如果旧字段也不存在，从入口注册表默认值推导。
- API Key 为空时，入口可显示为未配置，但不应阻断其他入口保存。
- 掩码值 `***` 保存时必须被忽略，不能覆盖真实 Key。

## 6. 错误处理

### 6.1 配置校验

后端需要校验：

- 入口 key 必须存在于注册表。
- `base_url` 必须是字符串，允许为空但保存时写入空字符串。
- `model` 必须是非空字符串。
- `enabled` 必须是布尔值。
- `thinking_budget` 必须在 128 到 32768 之间。
- `deep_thinking_max_tokens` 必须大于等于 1024。
- `json_response_format`、`enable_thinking` 必须是布尔值。

### 6.2 API Key 处理

- 读取配置时返回 `***`。
- 保存时如果收到 `***`，保持原值不变。
- 保存时如果收到空字符串，明确清空 Key。
- 保存时如果收到新值，写入新 Key。

### 6.3 连通性测试

- 入口未启用：返回 `ok=false`，提示入口未启用。
- API Key 为空：返回 `ok=false`，提示 API Key 未配置。
- 请求失败：返回 `ok=false` 和简短错误。
- 请求成功：返回 `ok=true`、模型名、响应摘要和耗时。

## 7. 测试计划

### 7.1 后端测试

新增或扩展 `news-web/tests/backend/test_api.py`：

1. `GET /api/settings/ai` 返回入口级配置。
2. `PUT /api/settings/ai` 能保存入口级配置。
3. API Key 保存后返回掩码。
4. 保存 `***` 不覆盖真实 Key。
5. 保存空字符串会清空 Key。
6. 旧 `/api/settings` 仍可用。
7. 入口注册表包含当前所有入口。
8. 无效入口 key 返回 400 或明确错误。

### 7.2 前端验证

至少执行：

```bash
cd news-web/frontend && npm run build
```

验证：

- 设置页能正常加载 AI 入口配置。
- 每个入口卡片可编辑。
- 高级参数可展开/收起。
- 从其他入口导入配置不会立即保存。
- 保存后状态刷新。
- API Key 显示为 `***`。

### 7.3 后端测试

执行：

```bash
cd news-web && python -m pytest tests/backend/test_api.py -v
```

如实现中新增独立测试文件，应优先补充到后端测试套件。

## 8. 非目标

本次设计不包含：

- 前端配置 AI 调用路径或流程编排。
- 前端配置入口之间的依赖关系。
- 前端配置失败重试策略。
- 新增新的 AI 功能入口。
- 修改现有 AI 调用质量策略。
- 将 RSS 预筛选立即实现为完整功能；本次只保留入口配置基础。

## 9. 实施建议顺序

1. 新增 `news-web/backend/ai_config.py`。
2. 新增 `/api/settings/ai` 读写接口和测试接口。
3. 保持旧 `/api/settings` 兼容。
4. 扩展后端测试。
5. 新增前端入口配置组件。
6. 将 `Settings.tsx` 中 AI 状态迁移到入口级状态。
7. 执行后端测试和前端 build。

## 10. 验收标准

- 设置页 AI 面板以入口为单位展示，而不是以链条为单位展示。
- 每个入口可独立配置 OpenAI 兼容 endpoint、API Key、model。
- thinking、JSON 输出、目标语言等参数按入口显示和保存。
- 可以从其他入口导入配置。
- API Key 掩码规则正确。
- 旧设置接口仍可用。
- 后端配置映射有测试覆盖。
- 前端 build 通过。
