# 前端状态系统 SSE 增强 + 清理设计

## 1. SSE 端点

### `GET /api/dashboard/stream`

单一 SSE 端点，替代所有独立轮询。

**事件类型：**

| event | 频率 | data |
|-------|------|------|
| `stats` | 每 10s | `{"articles":4250,"events":161,"chains":12,"cached":3800,"pending":200,"failed":50}` |
| `article_progress` | 每篇文章每步完成时 | `{"id":42,"title":"...","step":"cleaning","current":"清洗中","done":15,"total":200}` |
| `article_done` | 单篇完成时 | `{"id":42,"title":"...","ok":true,"steps":{"cached":true,"cleaned":"12K","translated":"8K","kcs":"HW high(85)"}}` |
| `article_failed` | 单篇失败时 | `{"id":97,"title":"...","error":"GameSpot 403","step":"cached"}` |
| `article_batch_start` | 批量开始 | `{"total":200}` |
| `article_batch_done` | 批量结束 | `{"done":195,"failed":5}` |
| `event_step` | 事件管线子步骤状态变化 | `{"step":"summarize","status":"running","done":42,"total":161,"current":"事件#213"}` |
| `event_done` | 事件管线完成 | `{"steps":[{"name":"聚类","status":"done","done":0,"total":0},...]}` |
| `log` | 通用日志 | `{"message":"...","level":"info"}` |

### 后端实现

新建 `api/dashboard.py`：

```python
class DashboardStream:
    """SSE 广播单例。管线函数通过 publish() 推送事件。"""
    _queues: list[asyncio.Queue] = []

    @classmethod
    def publish(cls, event: str, data: dict):
        for q in cls._queues:
            q.put_nowait((event, data))
        # 写入审计日志
        _audit_log(event, data)

    @classmethod
    def subscribe(cls) -> asyncio.Queue:
        q = asyncio.Queue()
        cls._queues.append(q)
        return q

    @classmethod
    def unsubscribe(cls, q):
        cls._queues.remove(q)


@router.get("/dashboard/stream")
async def dashboard_stream(request: Request):
    """SSE 端点 — 推送所有仪表盘状态事件。"""
    async def event_generator():
        q = DashboardStream.subscribe()
        try:
            # 初始 stats 快照
            yield f"event: stats\ndata: {json.dumps(_get_stats_snapshot())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            DashboardStream.unsubscribe(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 管线函数集成

`process_article()` 和 `_nightly()` 在关键节点调用 `DashboardStream.publish()`。不需要改造原有返回值——publish 是旁路广播。

---

## 2. 审计日志

### 路径与格式

```
logs/dashboard_audit.log     # 当前
logs/dashboard_audit.YYYY-MM-DD.log  # 历史（保留 7 天）
```

### 写入逻辑

```python
def _audit_log(event: str, data: dict):
    from datetime import datetime
    entry = {"ts": datetime.now().isoformat(timespec='seconds'), "event": event, "data": data}
    with open(audit_path, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
```

### 轮转

在 `scheduler.py` 的 `_backup_db()` 中追加日志轮转逻辑（凌晨 3:00 触发）。

---

## 3. 仪表盘卡片重设计

### 文章处理卡片

```
┌─ 📰 文章处理 ─────────────────────────────────────────────┐
│ [一键处理全部] [暂停]               ⏳ 45/200  ETA: ~8min  │
│ ██████████░░░░░░░░░░  22%                                │
│                                                           │
│ 当前: #142 Intel Nova Lake leaks — 清洗中                  │
│ 步骤: ✅缓存 ⏳清洗 ⬜翻译 ⬜KCS                             │
│                                                           │
│ 最近完成:                                                  │
│  ✅ #140 AMD Zen6 rumor    ✅12K 🌐8K 📝HW(82)             │
│  ✅ #139 TSMC 2nm update   ✅8K  🌐5K  📝Semi(90)          │
│                                                           │
│ 失败: #97 GameSpot 403 — 反爬拦截                           │
│                                                           │
│ 📋 审计日志: logs/dashboard_audit.log                       │
└───────────────────────────────────────────────────────────┘
```

### 事件管线卡片

```
┌─ 🔗 事件管线 ─────────────────────────────────────────────┐
│ [启动] [仅重聚类] [仅摘要] [仅构建链]     ⏳ 运行中          │
│                                                           │
│ ✅ 事件聚类    —                                           │
│ ⏳ 事件摘要    42/161  当前: 事件#213    ETA: ~12min        │
│    ████████░░░░░░░░░░  26%                                │
│ ⬜ 逻辑链构建                                               │
└───────────────────────────────────────────────────────────┘
```

---

## 4. 前端清理

### `client.ts`
- 修复 6 个 fetch 端点路径（`/articles/` → `/news_articles/`）
- 删除 4 个 KCS 函数

### `Dashboard.tsx`
- 删除 KCS 状态/定时器/轮询/handler/卡片
- 删除所有旧 `setInterval` 轮询
- 改为单一 `EventSource('/api/dashboard/stream')` 连接
- 根据 event 类型分发到对应 state

```tsx
useEffect(() => {
  const es = new EventSource('/api/dashboard/stream');
  es.addEventListener('stats', (e) => setStats(JSON.parse(e.data)));
  es.addEventListener('article_progress', (e) => updateArticleProgress(JSON.parse(e.data)));
  es.addEventListener('article_done', (e) => appendArticleDone(JSON.parse(e.data)));
  es.addEventListener('article_failed', (e) => appendArticleFailed(JSON.parse(e.data)));
  es.addEventListener('article_batch_start', (e) => startArticleBatch(JSON.parse(e.data)));
  es.addEventListener('article_batch_done', (e) => finishArticleBatch(JSON.parse(e.data)));
  es.addEventListener('event_step', (e) => updateEventStep(JSON.parse(e.data)));
  es.addEventListener('event_done', (e) => finishEvent(JSON.parse(e.data)));
  es.addEventListener('log', (e) => appendLog(JSON.parse(e.data)));
  es.onerror = () => { /* reconnect handled by browser */ };
  return () => es.close();
}, []);
```

### `Settings.tsx`
- 删除所有 AI 相关 state 和表单控件
- 删除传给 AISettings 的无用 props
- 移除旧 AI 配置字段的 save 逻辑

### `AISettings.tsx`
- Props 接口精简为 `{}`

### `ArticleSearch.tsx`
- 选中文章后的详情面板增加"管线处理"按钮
- 调用 `api.processArticle(id)`，内联显示结果

---

## 5. 后端改动

| 文件 | 改动 |
|------|------|
| `api/dashboard.py` | **新建** — SSE 端点 + DashboardStream 单例 + 审计日志 |
| `api/pipeline_article.py` | `_run_batch()` 和 `_run_single()` 中调用 `DashboardStream.publish()` |
| `api/pipeline_event.py` | `_nightly()` 和子步骤函数中调用 `DashboardStream.publish()` |
| `scheduler.py` | `_backup_db()` 追加上审计日志轮转 |
| `main.py` | 注册 dashboard router |

---

## 6. 验证

1. `curl -N http://localhost:8081/api/dashboard/stream` — 确认 SSE 流输出
2. `cat logs/dashboard_audit.log` — 确认事件写入
3. `npm run build` — 前端编译无错误
4. Dashboard 页面 — 确认 EventSource 连接、卡片实时更新
5. 触发文章批量处理 — 确认进度实时推送
6. 触发事件管线 — 确认步骤状态实时推送
