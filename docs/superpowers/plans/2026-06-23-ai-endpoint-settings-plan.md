# AI 入口级配置设置页实现计划

> 基于已批准设计文档：`docs/superpowers/specs/2026-06-23-ai-endpoint-settings-design.md`。

## Goal

将当前设置页 AI 配置从扁平字段重构为入口级配置：每个 AI 调用入口独立配置 OpenAI 兼容 endpoint、API Key、model 和高级参数；前端支持从其他入口导入配置；统一测试入口测试所有启用模块并反馈每个入口的问题；后端保持旧 `/api/settings` 接口兼容。

## Architecture

- 后端新增 `news-web/backend/ai_config.py`，负责入口注册表、旧字段兼容映射、掩码、校验和统一测试。
- 后端新增 `/api/settings/ai` 读写接口和 `/api/settings/ai/test` 统一测试接口。
- 前端新增入口级 AI 设置组件，替换当前以 `openai_model` / `translation_model` 为主的展示方式。
- 前端保留全局“保存设置”行为，导入配置只改变编辑态，不直接保存。
- 旧 `/api/settings`、`/api/settings/test-ai`、`/api/settings/test-translation` 保持可用。

## Tech Stack

- 后端：Python 3.14, FastAPI, Pydantic, SQLite-backed `config.json`, OpenAI compatible client
- 前端：React 18, TypeScript, Vite, existing settings CSS
- 测试：pytest, Vitest/build smoke

---

## File Structure

### Backend

```text
news-web/backend/
├── ai_config.py                 # 新增：AI 入口注册表、映射、掩码、测试
├── api/
│   └── settings.py              # 修改：新增 /api/settings/ai 与统一测试接口
└── config.py                    # 小改：补 clean_api_key / simple_model 掩码，必要时补属性
```

### Frontend

```text
news-web/frontend/src/pages/settings/
├── AISettings.tsx               # 修改：入口级 AI 设置总览
├── AIEndpointSettings.tsx       # 新增：渲染入口列表和统一测试
├── AIEndpointCard.tsx           # 新增：单个入口编辑卡片
├── AIEndpointImportDialog.tsx   # 新增：从其他入口导入配置
└── settings.css                 # 修改：补充入口卡片、导入弹窗、测试结果样式
```

### API Client

```text
news-web/frontend/src/api/client.ts
```

新增：

- `getAiSettings`
- `updateAiSettings`
- `testAiEndpoints`

---

## Implementation Phases

### Phase 1: 后端入口注册表与映射层

**Files:**

- `news-web/backend/ai_config.py`
- `news-web/backend/config.py`

**Steps:**

- [ ] 定义 `AI_ENDPOINTS` 注册表，包含以下入口：
  - `rss_prefilter`
  - `html_clean`
  - `translation`
  - `article_analysis`
  - `event_summary`
  - `event_ranking`
  - `chain_building`
  - `keyword_extraction`
  - `article_classification`
  - `priority_scoring`

- [ ] 为每个入口定义：
  - 中文名称
  - 用途说明
  - 默认 `base_url`
  - 默认 `model`
  - 默认 `enabled`
  - 支持的参数集合
  - 对应旧 config 字段

- [ ] 实现 `mask_api_keys()`：
  - `openai_api_key`
  - `translation_api_key`
  - `clean_api_key`
  - 后续入口级 API Key 均通过该逻辑掩码

- [ ] 实现 `to_ai_endpoint_config()`：
  - 从 `config._data` 读取旧字段
  - 推导每个入口的 endpoint 配置
  - 返回掩码后的入口级结构

- [ ] 实现 `apply_ai_endpoint_config(body)`：
  - 校验入口 key
  - 处理 `***` 不覆盖真实 Key
  - 处理空字符串明确清空 Key
  - 写回 `config` 旧字段

- [ ] 实现 `validate_ai_endpoint_payload()`：
  - 校验布尔、字符串、数值范围
  - 校验 `thinking_budget` 范围：128-32768
  - 校验 `deep_thinking_max_tokens` 最小值：1024

- [ ] 在 `config.py` 中补充或确认属性：
  - `clean_api_key`
  - `clean_base_url`
  - `simple_model`
  - `translation_target_lang`

**Validation:**

- 不依赖真实 API Key 也能通过映射测试。
- 旧字段可以正确映射到入口级结构。
- 入口级保存可以正确写回旧字段。

---

### Phase 2: 后端 API 接口

**Files:**

- `news-web/backend/api/settings.py`

**Steps:**

- [ ] 新增 Pydantic 模型或保留 `dict` 接收，用于 `/api/settings/ai`。

- [ ] 新增：

```text
GET /api/settings/ai
```

行为：

- 返回 `{ ai_endpoints: { ... } }`
- API Key 全部掩码

- [ ] 新增：

```text
PUT /api/settings/ai
```

行为：

- 接收入口级配置
- 调用 `apply_ai_endpoint_config()`
- 返回掩码后的入口级配置

- [ ] 新增：

```text
POST /api/settings/ai/test
```

行为：

- 不区分 `test-ai` / `test-translation`
- 测试所有启用入口
- 返回总体统计：
  - `total`
  - `passed`
  - `failed`
  - `skipped`
- 返回每个入口独立结果：
  - `endpoint_key`
  - `ok`
  - `model`
  - `error` 或 `response`
  - `elapsed_ms`
  - `skipped` / `reason`

- [ ] 保留旧接口：
  - `GET /api/settings`
  - `PUT /api/settings`
  - `POST /api/settings/test-ai`
  - `POST /api/settings/test-translation`

- [ ] 统一测试实现建议：
  - `translation` 入口调用 `translate_to_chinese()`
  - `html_clean` 入口调用 `clean_article_content()`，使用极短 HTML 片段
  - `article_analysis` 入口调用 `analyze_article()` 或轻量 `chat()`
  - 结构化入口使用 `chat()` + `response_format={"type": "json_object"}` 或 `_ai_json()`
  - `rss_prefilter` 若尚无真实函数，先返回 skipped：`reason="入口尚未接入"`

**Validation:**

- 测试接口不因为单个入口失败而整体崩溃。
- 单个入口失败只标记该入口失败。
- 未启用入口被跳过。
- API Key 为空入口被跳过或失败，并返回明确原因。

---

### Phase 3: 后端测试

**Files:**

- `news-web/tests/backend/test_api.py`

**Steps:**

- [ ] 添加 `test_ai_endpoint_settings_get`：
  - `GET /api/settings/ai`
  - 包含所有入口
  - API Key 为 `***`

- [ ] 添加 `test_ai_endpoint_settings_put_masks_key`：
  - 保存入口级配置
  - 返回掩码
  - 真实 config 中保留新 Key

- [ ] 添加 `test_ai_endpoint_settings_put_preserves_masked_key`：
  - 先设置真实 Key
  - 再保存 `***`
  - 确认真实 Key 未被覆盖

- [ ] 添加 `test_ai_endpoint_settings_put_clears_empty_key`：
  - 保存空字符串
  - 确认 config 中 Key 为空

- [ ] 添加 `test_ai_endpoint_settings_validation`：
  - 无效入口 key 返回错误
  - 非法 thinking budget 返回错误

- [ ] 添加 `test_legacy_settings_still_works`：
  - 旧 `GET /api/settings`
  - 旧 `PUT /api/settings`

- [ ] 添加 `test_ai_endpoint_test_skips_disabled`：
  - 禁用某入口
  - 调用统一测试接口
  - 确认该入口 skipped

**Validation:**

```bash
cd news-web && python -m pytest tests/backend/test_api.py -v
```

---

### Phase 4: API Client 类型与封装

**Files:**

- `news-web/frontend/src/api/client.ts`

**Steps:**

- [ ] 在 `api` 对象中新增：

```ts
getAiSettings: () => fetchJSON<{ ai_endpoints: Record<string, AiEndpointConfig> }>('/settings/ai'),
updateAiSettings: (data: { ai_endpoints: Record<string, AiEndpointConfig> }) =>
  fetchJSON<{ ai_endpoints: Record<string, AiEndpointConfig> }>('/settings/ai', {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
testAiEndpoints: () =>
  fetchJSON<AiEndpointTestResponse>('/settings/ai/test', { method: 'POST' }),
```

- [ ] 在 `types/index.ts` 或就近位置新增类型：

```ts
export type AiEndpointConfig = {
  enabled: boolean;
  base_url?: string;
  api_key?: string;
  model?: string;
  enable_thinking?: boolean;
  thinking_budget?: number;
  deep_thinking_max_tokens?: number;
  json_response_format?: boolean;
  target_lang?: string;
  max_tokens?: number;
};

export type AiEndpointTestResult = {
  endpoint_key: string;
  ok: boolean | null;
  model?: string;
  response?: string;
  error?: string;
  reason?: string;
  skipped?: boolean;
  elapsed_ms?: number;
};

export type AiEndpointTestResponse = {
  ok: boolean;
  summary: {
    total: number;
    passed: number;
    failed: number;
    skipped: number;
  };
  results: AiEndpointTestResult[];
};
```

**Validation:**

- TypeScript 不报错。
- API 返回结构与前端类型匹配。

---

### Phase 5: 前端入口级设置组件

**Files:**

- `news-web/frontend/src/pages/settings/AISettings.tsx`
- `news-web/frontend/src/pages/settings/AIEndpointSettings.tsx`
- `news-web/frontend/src/pages/settings/AIEndpointCard.tsx`
- `news-web/frontend/src/pages/settings/AIEndpointImportDialog.tsx`
- `news-web/frontend/src/pages/settings/settings.css`

**Steps:**

- [ ] 将 `AISettings.tsx` 改为入口级总览：
  - 调用 `api.getAiSettings()`
  - 渲染 `AIEndpointSettings`
  - 提供统一“测试所有 AI 入口”按钮
  - 保留原有测试逻辑但改为统一测试入口

- [ ] 新增 `AIEndpointSettings.tsx`：
  - 接收 `endpoints`
  - 渲染入口卡片列表
  - 汇总显示 passed / failed / skipped
  - 管理导入弹窗状态
  - 管理测试结果状态

- [ ] 新增 `AIEndpointCard.tsx`：
  - 启用开关
  - API 地址输入
  - API Key 输入，显示 `***`
  - 模型输入
  - 高级参数折叠区：
    - 启用 thinking
    - thinking budget
    - 深度输出上限 token
    - 强制 JSON 输出
    - 目标语言
  - 当前入口测试结果展示
  - “从其他入口导入”按钮

- [ ] 新增 `AIEndpointImportDialog.tsx`：
  - 选择源入口
  - 选择导入字段：
    - API 地址
    - API Key
    - 模型
    - 高级参数
  - 源入口和目标入口不能相同
  - 点击确认后只更新编辑态，不保存

- [ ] 更新 `Settings.tsx`：
  - 保留全局 `handleSave()`
  - 将 AI 状态改为从 `api.getAiSettings()` 加载
  - 保存时将入口级配置传给 `api.updateAiSettings()`
  - 旧通用设置字段仍通过 `/api/settings` 保存

- [ ] 更新 `settings.css`：
  - 入口卡片样式
  - 测试结果状态样式
  - 导入弹窗样式
  - 高级参数折叠区样式

**Validation:**

- 设置页 AI 面板按入口展示。
- 每个入口可独立编辑。
- 可从其他入口导入配置。
- API Key 显示为 `***`。
- 导入不立即保存。
- 统一测试按钮显示总体统计和每个入口结果。

---

### Phase 6: 前端验证

**Commands:**

```bash
cd news-web/frontend && npm run build
```

**Steps:**

- [ ] 修复 TypeScript 类型错误。
- [ ] 修复 React key / state 更新问题。
- [ ] 验证 CSS 在小屏和常规宽度下可用。
- [ ] 验证保存后页面状态刷新。
- [ ] 验证 API Key 掩码显示。
- [ ] 验证导入配置不直接触发保存。

---

### Phase 7: 端到端验证

**Commands:**

```bash
cd news-web && python -m pytest tests/backend/test_api.py -v
cd news-web/frontend && npm run build
```

**Manual Checks:**

- [ ] 打开设置页，进入 AI 设置。
- [ ] 确认所有入口卡片加载。
- [ ] 修改一个入口 model。
- [ ] 点击保存，确认页面刷新后仍显示新 model。
- [ ] 修改 API Key，确认保存后显示 `***`。
- [ ] 再次保存 `***`，确认不覆盖真实 Key。
- [ ] 清空 API Key，保存后确认 Key 为空。
- [ ] 点击“测试所有 AI 入口”，确认显示通过、失败、跳过统计。
- [ ] 旧 `/api/settings` 仍返回旧字段。

---

## Risks and Mitigations

### Risk 1: 统一测试接口耗时过长

**Mitigation:**

- 每个入口设置短超时或限制测试 prompt 长度。
- 可先串行测试，后续再考虑并发。
- 对尚未接入入口返回 skipped，不阻塞其他入口。

### Risk 2: API Key 掩码误覆盖

**Mitigation:**

- 后端明确处理 `***`。
- 后端测试覆盖 `***` 不覆盖真实 Key。
- 前端保存时保留当前掩码值。

### Risk 3: 评分入口归属不清

**Mitigation:**

- 当前设计将 `priority_scoring` 作为独立入口。
- 实现阶段确认其默认模型：
  - 若归入轻量结构化判断，默认使用 `simple_model`
  - 若保留高质量判断，默认使用 `openai_model`
- 无论默认模型如何，前端必须能独立配置该入口。

### Risk 4: 旧接口和新接口行为不一致

**Mitigation:**

- 新旧接口共享 `ai_config.py` 映射逻辑。
- 旧接口保存后，新接口能读到更新。
- 新接口保存后，旧接口能读到更新。

### Risk 5: 前端状态复杂

**Mitigation:**

- 入口编辑态集中放在 `AISettings.tsx`。
- 卡片组件只负责展示和触发局部修改。
- 导入弹窗只返回字段变更，不负责保存。

---

## Acceptance Criteria

- [ ] 后端新增 `ai_config.py`。
- [ ] 后端新增 `GET /api/settings/ai`。
- [ ] 后端新增 `PUT /api/settings/ai`。
- [ ] 后端新增 `POST /api/settings/ai/test`。
- [ ] 统一测试接口测试所有启用入口，并返回每个入口结果。
- [ ] 旧 `/api/settings` 仍可用。
- [ ] API Key 掩码规则正确。
- [ ] 保存 `***` 不覆盖真实 Key。
- [ ] 保存空字符串会清空 Key。
- [ ] 前端 AI 设置按入口展示。
- [ ] 每个入口可独立配置 endpoint / API Key / model / 高级参数。
- [ ] 前端支持从其他入口导入配置。
- [ ] 导入配置不立即保存。
- [ ] 前端 build 通过。
- [ ] 后端 pytest 通过。

---

## Suggested Commit Strategy

1. `feat: 新增 AI 入口配置映射与 API`
2. `test: 覆盖 AI 入口配置映射与统一测试`
3. `feat: 重构 AI 设置页为入口级配置`
4. `test: 验证 AI 设置页构建与类型`

每个提交后按项目规则 push 到 `origin main`。
