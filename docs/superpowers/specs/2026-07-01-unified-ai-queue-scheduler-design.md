# 统一 AI 入口 + 队列调度器设计

> 日期: 2026-07-01 | 状态: 待实现

## 目标

1. **统一 AI 入口**：删除三段式配置（标题初筛/文章处理/事件管线），统一接入 DeepSeek 开放平台
2. **DB Writer 线程**：从处理线程中拆出 DB 写入，单线程串行 safe_commit，彻底消除 SQLite 写锁竞争
3. **统一任务队列**：FIFO 队列调度替代 task_lock.py 的分组互斥逻辑
4. **余额探针**：接入 DeepSeek `/user/balance` API，前端仪表盘展示余额 + 低于阈值自动降并发

## 约束

- 每个 AI 步骤完成后 **立即落库**（不入内存堆积），由 Writer 线程确认落库后才继续下一步
- 数据完整性优先：中途崩溃不丢已完成的步骤结果
- 前端刷新后可恢复进度（task_state 保留）
- 改动量控制在 400-500 行净变更

## 架构

```
                      ┌─────────────────────────────────┐
                      │        统一任务队列 (FIFO)        │
                      │  article_batch / event_nightly /  │
                      │  summarize / build_chains / ...   │
                      └──────────┬──────────────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │                             │
          ┌───────▼────────┐          ┌────────▼────────┐
          │ AI Worker × N  │  ──入队──▶│  DB Writer × 1   │
          │ (只做 HTTP IO) │  ←──确认──│ (串行 safe_commit)│
          └────────────────┘          └──────────────────┘
                  │                             │
                  ▼                             ▼
           DeepSeek API                  SQLite (零竞争)
           统一入口
```

**核心变化**：
1. 删除 `task_lock.py` 的分组互斥逻辑 → 队列本身就是互斥
2. 新增 `db_writer.py` — 单线程消费写请求，一个 DB 连接串行执行 safe_commit
3. `process_article` 不再直接碰 DB，每步完成后入队写请求等 Writer 确认
4. AI 配置统一为单套 DeepSeek 参数
5. 翻译复用统一 AI 入口

## 关键参数

| 项 | 值 |
|----|-----|
| 默认并发数 | 10 |
| 可调范围 | 1-50（前端滑块） |
| AI 入口 | 单一 DeepSeek base_url + api_key + model |
| DB Writer | 1 线程，1 连接 |
| 余额探针 | `GET https://api.deepseek.com/user/balance` |
| 余额阈值 | 前端可配，默认 < ¥5 自动降并发到 1 |

## 模块变更清单

### 新增
- `backend/queue/__init__.py`
- `backend/queue/db_writer.py` — DB Writer 单线程，含 ack 回调机制
- `backend/queue/task_scheduler.py` — 统一任务队列 + worker 池

### 重写
- `backend/api/pipeline_article.py` — worker 不再碰 DB，入队写请求；MAX_WORKERS 回升到可配值
- `backend/api/pipeline_event.py` — 接入统一队列

### 修改
- `backend/pipeline/process_article.py` — 接收 writer 回调，每步完成入队等待确认
- `backend/ai_client.py` — 去除三段式，统一 DeepSeek 入口 + 余额查询函数
- `backend/config.py` — 简化 AI 配置结构（删除三段式字段，保留向后兼容迁移逻辑）
- `backend/main.py` — 启动 DB Writer + 调度器生命周期
- `frontend/src/pages/settings/AISettings.tsx` — 三段式 → 单套配置 + 并发滑块
- `frontend/src/pages/Dashboard.tsx` — 余额卡片展示
- `frontend/src/api/client.ts` — 新增余额查询/并发调整 API

### 简化
- `backend/translation_client.py` — 复用统一 AI 入口的 client 实例，保留翻译专用 system prompt 和 HTML 处理逻辑

### 删除
- `backend/utils/task_lock.py` — 队列调度器替代

### 保留
- `backend/utils/task_state.py` — 进度持久化（刷新恢复），与调度无关

## 余额探针

```
GET https://api.deepseek.com/user/balance
Authorization: Bearer <api_key>

→ {
    "is_available": true,
    "balance_infos": [{
      "currency": "CNY",
      "total_balance": "110.00",
      "granted_balance": "10.00",
      "topped_up_balance": "100.00"
    }]
  }
```

- 所有金额字段为 **字符串类型**
- `is_available=false` 时暂停管线
- 前端仪表盘展示余额卡片（货币 + 总额 + 赠金 + 充值余额）
- 低于阈值自动降并发：**每 5 分钟轮询一次余额**
- 剩余 API 调用次数估算（基于 token 消耗统计）

## DB Writer 线程接口

```python
class DbWriter:
    """单线程串行 DB 写入器。"""

    def submit(self, sql: str, params: tuple) -> threading.Event:
        """提交写请求，返回 Event 对象。调用方 await event.wait() 等待确认。"""

    def start(self): ...
    def stop(self): ...
```

Worker 方调用模式：

```python
writer = get_db_writer()
# AI 调用完成后
event = writer.submit("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (c, aid))
event.wait(timeout=30)  # 等待 Writer 确认落库
# 继续下一步
```

## 统一任务调度器接口

```python
class TaskScheduler:
    """统一 FIFO 任务队列 + worker 池。"""

    def __init__(self, max_workers: int = 10): ...

    def submit(self, task_type: str, fn: callable, *args) -> str:
        """提交任务，返回 task_id。同类型任务仅互斥自身。"""

    def cancel(self, task_id: str) -> bool: ...

    def set_workers(self, n: int): ...  # 动态调整并发数

    @property
    def status(self) -> dict: ...  # 当前队列状态
```

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| Writer 线程崩溃 | Writer 内部 try/except + 重试，崩溃后回写 event.set() 通知 worker |
| Worker 等 Writer 确认超时 | 30s 超时后记录日志 + 降级为直接 db.commit() |
| 余额探针失败 | 不影响管线运行，静默降级，上次成功数据继续展示 |
| 并发调整过于激进 | 前端提示 >20 并发时的余额消耗预估 |

## AI 配置迁移

脚本自动将旧三段式配置迁移到统一结构：

```python
# 旧 config.json 结构
"ai_endpoints": {
  "rss_prefilter": {"base_url": "...", "api_key": "...", "model": "..."},
  "article_processing": {"base_url": "...", "api_key": "...", "model": "..."},
  "event_pipeline": {"base_url": "...", "api_key": "...", "model": "..."}
}

# 新 config.json 结构
"ai": {
  "base_url": "https://api.deepseek.com",
  "api_key": "...",
  "model": "deepseek-chat"
}
# 翻译配置字段 "translation_*" 废弃，复用 ai 配置
```

迁移策略：取 article_processing 的配置作为新统一配置（最常用），rss_prefilter 和 event_pipeline 的旧字段保留但不读取。
