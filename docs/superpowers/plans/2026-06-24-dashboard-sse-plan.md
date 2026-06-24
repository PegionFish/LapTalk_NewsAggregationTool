# Dashboard SSE + Frontend Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** Replace polling with SSE streaming, add audit logging, redesign Dashboard cards, and clean up frontend dead code.

**Architecture:** New `api/dashboard.py` with SSE endpoint + `DashboardStream` singleton. Pipeline functions publish events via the singleton. Frontend uses single `EventSource` connection instead of multiple `setInterval` pollers.

**Tech Stack:** Python 3.14, FastAPI (StreamingResponse), React 18 + EventSource API

## Global Constraints

- Code comments must not reference specific model names or vendors
- All user-facing text in Chinese
- Audit log as JSONL with timestamp
- SSE events use standard `text/event-stream` format
- Commit + push + restart backend + rebuild frontend after each task

---

### Task 1: Create `api/dashboard.py` — SSE Endpoint + Audit Log

**Files:** Create `news-web/backend/api/dashboard.py`

```python
"""仪表盘 SSE 端点 + 审计日志 — 替代所有独立轮询。"""
import asyncio, json, logging, os
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from config import config
from utils.db import get_db_connection

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)

_AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
_AUDIT_PATH = os.path.join(_AUDIT_DIR, 'dashboard_audit.log')


def _audit_log(event: str, data: dict):
    """写入审计日志（JSONL 格式）。"""
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        entry = {"ts": datetime.now().isoformat(timespec='seconds'), "event": event, "data": data}
        with open(_AUDIT_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.warning(f"审计日志写入失败: {e}")


def rotate_audit_log():
    """轮转审计日志：当前文件重命名为带日期后缀，保留 7 天。"""
    try:
        if not os.path.exists(_AUDIT_PATH):
            return
        today = datetime.now().strftime('%Y-%m-%d')
        rotated = f"{_AUDIT_PATH}.{today}"
        os.rename(_AUDIT_PATH, rotated)
        # 清理超过 7 天的日志
        import glob, time
        cutoff = time.time() - 7 * 86400
        for old in glob.glob(f"{_AUDIT_PATH}.*"):
            if os.path.getmtime(old) < cutoff:
                os.remove(old)
    except Exception as e:
        logger.warning(f"审计日志轮转失败: {e}")


class DashboardStream:
    """SSE 广播单例。管线函数通过 publish() 推送事件到所有连接的客户端。"""
    _queues: list[asyncio.Queue] = []

    @classmethod
    def publish(cls, event: str, data: dict):
        payload = (event, data)
        for q in cls._queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        _audit_log(event, data)

    @classmethod
    def subscribe(cls) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=256)
        cls._queues.append(q)
        return q

    @classmethod
    def unsubscribe(cls, q: asyncio.Queue):
        try:
            cls._queues.remove(q)
        except ValueError:
            pass


def _get_stats_snapshot() -> dict:
    """获取当前统计快照。"""
    try:
        db = get_db_connection(config.db_path)
        articles = db.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0]
        events = db.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0]
        chains = db.execute("SELECT COUNT(*) FROM logic_chains").fetchone()[0]
        cached = db.execute("SELECT COUNT(*) FROM news_articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'").fetchone()[0]
        pending = db.execute("SELECT COUNT(*) FROM news_articles WHERE content_status='pending'").fetchone()[0]
        failed = db.execute("SELECT COUNT(*) FROM news_articles WHERE local_path LIKE '[ERR:%'").fetchone()[0]
        db.close()
        return {"articles": articles, "events": events, "chains": chains,
                "cached": cached, "pending": pending, "failed": failed}
    except Exception:
        return {"articles": 0, "events": 0, "chains": 0, "cached": 0, "pending": 0, "failed": 0}


@router.get("/stream")
async def dashboard_stream(request: Request):
    """SSE 端点 — 推送仪表盘所有状态事件。"""
    async def event_generator():
        q = DashboardStream.subscribe()
        try:
            # 初始 stats 快照
            stats = _get_stats_snapshot()
            yield f"event: stats\ndata: {json.dumps(stats, ensure_ascii=False)}\n\n"
            # 定时 stats 推送（每 10s）
            last_stats = datetime.now()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=5)
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    now = datetime.now()
                    if (now - last_stats).total_seconds() >= 10:
                        stats = _get_stats_snapshot()
                        yield f"event: stats\ndata: {json.dumps(stats, ensure_ascii=False)}\n\n"
                        last_stats = now
        finally:
            DashboardStream.unsubscribe(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] Write file, verify import, commit

---

### Task 2: Integrate DashboardStream.publish() into Pipelines

**Files:** Modify `api/pipeline_article.py`, `api/pipeline_event.py`

In `_run_batch()` (pipeline_article.py), add:

```python
from api.dashboard import DashboardStream

def _run_batch():
    global _article_state
    _reset_state()
    DashboardStream.publish("article_batch_start", {"total": _article_state["total"]})
    try:
        from pipeline.process_article import process_all_pending
        result = process_all_pending()
        ...
    finally:
        ...
        DashboardStream.publish("article_batch_done", {"done": _article_state["done"], "failed": _article_state["failed"]})
```

In `process_article()` (process_article.py), at each step completion:

```python
from api.dashboard import DashboardStream

# After each step:
DashboardStream.publish("article_progress", {
    "id": aid, "title": title, "step": "cleaning",
    "done": _article_state.get("done", 0), "total": _article_state.get("total", 0)
})
# On completion:
DashboardStream.publish("article_done", {"id": aid, "title": title, "ok": True, "steps": result["steps"]})
# On failure:
DashboardStream.publish("article_failed", {"id": aid, "title": title, "error": str(e), "step": "..."})
```

In `_nightly()` (pipeline_event.py), in the step loop:

```python
from api.dashboard import DashboardStream

# In the while st.get("running") loop:
DashboardStream.publish("event_step", {
    "step": name, "status": "running",
    "done": st.get("done", 0), "total": st.get("total", 0),
    "current": st.get("current", "")
})
# On completion:
DashboardStream.publish("event_done", {"steps": _event_state["steps"]})
```

- [ ] Integrate publish calls, verify imports, commit

---

### Task 3: Audit Log Rotation + Register Router

**Files:** Modify `scheduler.py`, `main.py`

In `scheduler.py` `_backup_db()`, add:

```python
from api.dashboard import rotate_audit_log
rotate_audit_log()
```

In `main.py`, register the new router:

```python
from api.dashboard import router as dashboard_router
app.include_router(dashboard_router)
```

- [ ] Modify files, verify startup, commit

---

### Task 4: Frontend — Fix client.ts + Rewrite Dashboard

**Files:** Modify `client.ts`, `Dashboard.tsx`

### client.ts fixes:
- Fix 6 fetch paths: `/articles/` → `/news_articles/`
- Delete 4 KCS functions

### Dashboard.tsx rewrite:
- Remove ALL `useRef<setInterval>` timers and `setInterval` polling
- Remove KCS state
- Add single `EventSource` connection in useEffect
- Add state for recent completions and failures
- Rewrite Article Processing card with progress bar + ETA + recent items
- Rewrite Event Pipeline card with per-step progress + ETA

```tsx
const [recentDone, setRecentDone] = useState<Array<{id:number,title:string,steps:Record<string,unknown>}>>([]);
const [recentFailed, setRecentFailed] = useState<Array<{id:number,title:string,error:string}>>([]);
const [batchETA, setBatchETA] = useState('');

useEffect(() => {
  const es = new EventSource('/api/dashboard/stream');
  es.addEventListener('stats', (e) => setStats(JSON.parse(e.data)));
  es.addEventListener('article_progress', (e) => {
    const d = JSON.parse(e.data);
    setArticleState(prev => ({...prev, current: `${d.title} — ${d.step}`, done: d.done, total: d.total}));
    if (d.total && d.done) {
      setBatchETA(`~${Math.round((d.total - d.done) * 4 / 60)}min`);
    }
  });
  es.addEventListener('article_done', (e) => {
    const d = JSON.parse(e.data);
    setRecentDone(prev => [d, ...prev].slice(0, 5));
  });
  es.addEventListener('article_failed', (e) => {
    const d = JSON.parse(e.data);
    setRecentFailed(prev => [d, ...prev].slice(0, 10));
  });
  es.addEventListener('article_batch_start', (e) => {
    const d = JSON.parse(e.data);
    setArticleRunning(true);
    setArticleState({running:true, total:d.total, done:0, failed:0, current:'启动中...', log:[]});
    setRecentDone([]); setRecentFailed([]);
  });
  es.addEventListener('article_batch_done', (e) => {
    setArticleRunning(false);
    setBatchETA('');
  });
  es.addEventListener('event_step', (e) => {
    const d = JSON.parse(e.data);
    setEventState(prev => {
      const steps = [...(prev.steps || [])];
      const idx = steps.findIndex(s => s.name === d.step);
      if (idx >= 0) steps[idx] = {...steps[idx], ...d};
      return {...prev, steps, running: true};
    });
  });
  es.addEventListener('event_done', (e) => {
    const d = JSON.parse(e.data);
    setEventRunning(false);
    setEventState(prev => ({...prev, running: false, steps: d.steps}));
  });
  es.onerror = () => {}; // browser auto-reconnects
  return () => es.close();
}, []);
```

- [ ] Fix client.ts, rewrite Dashboard, build verify, commit

---

### Task 5: Frontend — Settings Cleanup + ArticleSearch Button

**Files:** Modify `Settings.tsx`, `AISettings.tsx`, `ArticleSearch.tsx`

### Settings.tsx:
- Remove AI-related state fields
- Remove AI-related form JSX
- Remove unused props passed to AISettings

### AISettings.tsx:
- Props → `{}`

### ArticleSearch.tsx:
- Add "管线处理" button in detail panel:

```tsx
const [processing, setProcessing] = useState(false);
const [processResult, setProcessResult] = useState<{ok:boolean,steps:Record<string,unknown>,error:string}|null>(null);

const handleProcess = async () => {
  if (!selected) return;
  setProcessing(true); setProcessResult(null);
  try {
    const r = await api.processArticle(selected.id);
    setProcessResult(r);
  } catch(e) { setProcessResult({ok:false,steps:{},error:String(e)}); }
  setProcessing(false);
};

// JSX:
<Button onClick={handleProcess} disabled={processing} icon="fa-rocket">
  {processing ? '处理中...' : '管线处理'}
</Button>
{processResult && (
  <div>{processResult.ok ? '✅ ' + JSON.stringify(processResult.steps) : '❌ ' + processResult.error}</div>
)}
```

- [ ] Modify 3 files, build verify, commit

---

### Task 6: Tests + Deploy

- [ ] Run full test suite
- [ ] Build frontend
- [ ] Restart backend
- [ ] Verify SSE: `curl -N http://localhost:8081/api/dashboard/stream`
- [ ] Verify audit log: `cat logs/dashboard_audit.log`
- [ ] Commit final
