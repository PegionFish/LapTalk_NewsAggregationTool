# Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the content fetch-processing pipeline from a tangled 1735-line parallel-track monolith into two focused, linear-stage modules (article-level + event-level), simplify the frontend dashboard, and restructure AI config into three groups.

**Architecture:** Article-level tasks (cache→clean→translate→analyze+KCS) execute immediately per article. Event-level tasks (recluster→summarize→build-chains) run at 1:00 AM or on manual trigger. Both pipelines use linear stage execution — no parallel threads, no `_run_seq` loops.

**Tech Stack:** Python 3.14, FastAPI, SQLite, React 18 + TypeScript + Vite

## Global Constraints

- Code comments must not reference specific model names or vendors (AI endpoint config is frontend-controlled)
- All text descriptions in Chinese
- Backward compatible: existing DB schema unchanged
- Tests required for all new endpoints
- Commit + push + restart backend + rebuild frontend after each task

---

## File Structure Map

```
Create:
  api/pipeline_article.py      # Article-level pipeline endpoints + logic (~300 lines)
  api/pipeline_event.py        # Event-level pipeline endpoints + logic (~400 lines)
  pipeline/process_article.py  # Single-article processing orchestrator (~150 lines)
  tests/backend/test_pipeline_article.py
  tests/backend/test_pipeline_event.py

Modify:
  api/pipeline.py              # Remove: all batch functions and endpoints
  main.py                      # Register new routers, remove old pipeline router
  scheduler.py                 # Change AI cron to 1:00 AM, call event pipeline
  ai_config.py                 # Collapse 10 endpoints → 3 groups
  pipeline/ai_filter.py        # Auto-trigger after RSS fetch
  pipeline/analyze.py          # Keep only event-level recluster/relations
  pipeline/collect_data.py     # Trigger article processing after cache
  frontend/src/pages/Dashboard.tsx     # Two-card layout
  frontend/src/pages/settings/AISettings.tsx  # Three-group layout
  frontend/src/api/client.ts           # Update API functions
  tests/backend/test_api.py            # Remove old pipeline tests
```

---

### Task 1: Create `pipeline/process_article.py` — Single-Article Orchestrator

**Files:**
- Create: `news-web/backend/pipeline/process_article.py`
- Modify: `news-web/backend/pipeline/__init__.py`

**Interfaces:**
- Produces: `process_article(article_id: int) -> dict` — returns `{"ok": bool, "steps": {"cached": bool, "cleaned": str, "translated": str, "analyzed": bool}}`
- Produces: `process_all_pending(db_path: str | None = None) -> dict` — returns `{"total": int, "done": int, "failed": int, "log": list[str]}`
- Consumes: `ai_client.clean_article_content()`, `translation_client.translate_html_preserve_structure()`, `ai_client.extract_keywords_classify_score_ai()`, `ai_client.analyze_article()`
- Consumes: `pipeline/fetch_content.py` content download logic

**Implementation:**

```python
#!/usr/bin/env python3
"""单篇文章处理编排器 — 缓存→清洗→翻译→分析+KCS 线性执行。"""
import sys, os, sqlite3, time, logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

from config import config
from ai_client import clean_article_content, analyze_article, extract_keywords_classify_score_ai
from translation_client import translate_html_preserve_structure, translate_html

logger = logging.getLogger(__name__)


def _conn():
    from utils.db import get_db_connection
    return get_db_connection(config.db_path)


def process_article(article_id: int) -> dict:
    """单篇文章完整处理：缓存(如未缓存)→清洗→翻译→分析+KCS。
    每步完成后立即写入 DB，失败不阻断后续步骤。
    返回 {"ok": bool, "steps": {...}, "error": str}
    """
    result = {"ok": True, "steps": {}, "error": ""}
    db = _conn()

    try:
        row = db.execute("""
            SELECT id, title, url, local_path, text_content, source, content_status, fetched_at
            FROM news_articles WHERE id=?
        """, (article_id,)).fetchone()
        if not row:
            return {"ok": False, "error": f"文章 #{article_id} 不存在"}

        aid, title, url, local_path, text_content, source, status, fetched_at = row

        # ── Step 1: 内容缓存 ──
        if not local_path or local_path.startswith('[ERR:'):
            from pipeline.fetch_content import fetch_article_content
            ok = fetch_article_content(aid, url, config.content_cache_path)
            result["steps"]["cached"] = ok
            if not ok:
                result["steps"]["cached"] = False
                # 反爬源：跳过缓存，但后续步骤可能无内容可处理
        else:
            result["steps"]["cached"] = True

        # 重新读取以确保拿到最新的 local_path
        row = db.execute("SELECT local_path, text_content FROM news_articles WHERE id=?", (aid,)).fetchone()
        local_path, text_content = row if row else ("", "")

        # 读取 HTML 内容
        html = ""
        if local_path and not local_path.startswith('[ERR:') and os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8', errors='replace') as f:
                html = f.read()
        elif text_content:
            html = text_content

        if not html or len(html.strip()) < 100:
            db.close()
            return {"ok": False, "error": f"#{aid} 无有效 HTML 内容", "steps": result["steps"]}

        # ── Step 2: 内容清洗 ──
        try:
            cleaned = clean_article_content(html)
            if cleaned and len(cleaned.strip()) > 50:
                db.execute("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (cleaned, aid))
                db.commit()
                result["steps"]["cleaned"] = f"{len(cleaned)} chars"
            else:
                result["steps"]["cleaned"] = "empty"
        except Exception as e:
            result["steps"]["cleaned"] = f"error: {e}"
            logger.warning(f"#{aid} 清洗失败: {e}")

        # ── Step 3: 翻译 ──
        try:
            if config.translation_enabled and config.translation_api_key:
                translated = translate_html_preserve_structure(html)
            else:
                translated = translate_html(html)
            if translated:
                db.execute("UPDATE news_articles SET translated_content=? WHERE id=?", (translated, aid))
                db.commit()
                result["steps"]["translated"] = f"{len(translated)} chars"
            else:
                result["steps"]["translated"] = "empty"
        except Exception as e:
            result["steps"]["translated"] = f"error: {e}"
            logger.warning(f"#{aid} 翻译失败: {e}")

        # ── Step 4: 分析+KCS ──
        # 优先用清洗后正文
        row = db.execute("SELECT ai_cleaned_content, text_content, fetched_at FROM news_articles WHERE id=?", (aid,)).fetchone()
        content_for_ai = (row[0] or row[1]) if row else html

        # a) 分析摘要
        try:
            summary = analyze_article(title, content_for_ai)
            if summary:
                db.execute("UPDATE news_articles SET ai_summary=?, ai_analyzed=1 WHERE id=?", (summary, aid))
                db.commit()
                result["steps"]["analyzed"] = True
            else:
                result["steps"]["analyzed"] = False
        except Exception as e:
            result["steps"]["analyzed"] = f"error: {e}"
            logger.warning(f"#{aid} 分析失败: {e}")

        # b) KCS 合并
        try:
            from datetime import datetime as _dt
            days = 0
            if fetched_at:
                try:
                    days = max(0, (_dt.now() - _dt.fromisoformat(fetched_at)).days)
                except Exception:
                    pass
            kcs = extract_keywords_classify_score_ai(title, content_for_ai, source, days)
            if kcs:
                import json as _json
                kws = kcs.get("keywords", [])
                if kws:
                    db.execute("UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?",
                               (_json.dumps(kws, ensure_ascii=False), _json.dumps(kws, ensure_ascii=False), aid))
                if kcs.get("category"):
                    db.execute("UPDATE news_articles SET ai_category=?, ai_tags=? WHERE id=?",
                               (kcs["category"], _json.dumps(kcs.get("tags", []), ensure_ascii=False), aid))
                if "score" in kcs:
                    db.execute("UPDATE news_articles SET priority_score=?, priority_label=?, ai_priority_score=? WHERE id=?",
                               (kcs["score"], kcs.get("label", "medium"), kcs["score"], aid))
                db.commit()
                result["steps"]["kcs"] = f"{kcs.get('category','?')} {kcs.get('label','medium')}({kcs.get('score',0):.0f})"
            else:
                result["steps"]["kcs"] = "empty"
        except Exception as e:
            result["steps"]["kcs"] = f"error: {e}"
            logger.warning(f"#{aid} KCS 失败: {e}")

        db.commit()
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"process_article #{article_id} 异常: {e}")
    finally:
        db.close()
    return result


def process_all_pending(db_path: str | None = None) -> dict:
    """遍历所有待处理文章，逐篇执行 process_article()。返回进度汇总。"""
    if not db_path:
        db_path = config.db_path

    db = _conn()
    rows = db.execute("""
        SELECT id FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
          AND ai_filtered != -1
          AND (ai_analyzed = 0 OR ai_cleaned_content IS NULL OR ai_cleaned_content = ''
               OR translated_content IS NULL OR translated_content = ''
               OR ai_keywords IS NULL OR ai_keywords = ''
               OR ai_category IS NULL OR ai_category = ''
               OR ai_priority_score IS NULL OR ai_priority_score = 0.0)
        ORDER BY id DESC
    """).fetchall()
    db.close()

    total = len(rows)
    done = 0
    failed = 0
    log: list[str] = []

    log.append(f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] 开始处理 {total} 篇文章")

    for (aid,) in rows:
        r = process_article(aid)
        if r["ok"]:
            done += 1
        else:
            failed += 1
            log.append(f"#{aid} ❌ {r.get('error', '未知错误')}")
        time.sleep(0.5)  # 温和速率控制

    log.append(f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] 完成: {done}/{total}, 失败: {failed}")
    return {"total": total, "done": done, "failed": failed, "log": log}
```

- [ ] **Step 1: Write `process_article.py`**

Write the complete file as shown above.

- [ ] **Step 2: Verify imports resolve**

Run: `cd news-web/backend && python -c "from pipeline.process_article import process_article, process_all_pending; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/pipeline/process_article.py
git commit -m "feat: add process_article.py — single-article linear pipeline orchestrator"
```

---

### Task 2: Create `api/pipeline_article.py` — Article Pipeline API

**Files:**
- Create: `news-web/backend/api/pipeline_article.py`

**Interfaces:**
- Produces: `POST /api/pipeline/article/{id}/process`, `POST /api/pipeline/article/batch-process`, `GET /api/pipeline/article/status`
- Consumes: `pipeline.process_article.process_article()`, `pipeline.process_article.process_all_pending()`

```python
"""文章级管线 API — 缓存→清洗→翻译→分析+KCS"""
import threading, logging
from datetime import datetime
from fastapi import APIRouter

from config import config
from utils.task_lock import task_lock
from utils.task_state import task_state

router = APIRouter(prefix="/api/pipeline/article", tags=["pipeline-article"])
logger = logging.getLogger(__name__)

_article_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}


def _reset_state():
    _article_state.clear()
    _article_state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []})


def _run_single(aid: int):
    global _article_state
    from pipeline.process_article import process_article
    _article_state["current"] = f"#{aid}"
    r = process_article(aid)
    if r["ok"]:
        _article_state["done"] += 1
        _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ✅ {r['steps']}")
    else:
        _article_state["failed"] += 1
        _article_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] #{aid} ❌ {r.get('error', '')}")
    _article_state["current"] = ""


def _run_batch():
    global _article_state
    _reset_state()
    try:
        from pipeline.process_article import process_all_pending
        result = process_all_pending()
        _article_state["total"] = result["total"]
        _article_state["done"] = result["done"]
        _article_state["failed"] = result["failed"]
        _article_state["log"].extend(result["log"])
    except Exception as e:
        logger.error(f"article batch: {e}")
        _article_state["log"].append(f"❌ {e}")
    finally:
        _article_state["running"] = False
        task_lock.release('article')
        task_state.finish('article', success=True)


@router.post("/{article_id}/process")
def start_article_process(article_id: int):
    """单篇完整处理"""
    from pipeline.process_article import process_article
    r = process_article(article_id)
    return r


@router.post("/batch-process")
def start_article_batch():
    global _article_state
    if _article_state.get("running"):
        return {"ok": False, "message": "文章处理已在运行中"}
    ok, msg = task_lock.acquire('article')
    if not ok:
        return {"ok": False, "message": msg}
    from utils.db import get_db_connection
    db = get_db_connection(config.db_path)
    n = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
          AND ai_filtered != -1
          AND (ai_analyzed = 0 OR ai_cleaned_content IS NULL OR ai_cleaned_content = ''
               OR translated_content IS NULL OR translated_content = ''
               OR ai_keywords IS NULL OR ai_keywords = '')
    """).fetchone()[0]
    db.close()
    task_state.init_state('article', total=n)
    _article_state["running"] = True
    _article_state["total"] = n
    threading.Thread(target=_run_batch, daemon=True).start()
    return {"ok": True, "message": f"启动文章批量处理，预计 {n} 篇", "pending": n}


@router.get("/status")
def get_article_status():
    return dict(_article_state)
```

- [ ] **Step 1: Write `pipeline_article.py`**

- [ ] **Step 2: Verify it imports**

Run: `cd news-web/backend && python -c "from api.pipeline_article import router; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/api/pipeline_article.py
git commit -m "feat: add pipeline_article.py API — article-level linear pipeline endpoints"
```

---

### Task 3: Create `api/pipeline_event.py` — Event Pipeline API

**Files:**
- Create: `news-web/backend/api/pipeline_event.py`

**Interfaces:**
- Produces: `POST /api/pipeline/event/nightly`, `GET /api/pipeline/event/status`
- Produces: `POST /api/pipeline/event/recluster`, `POST /api/pipeline/event/summarize`, `POST /api/pipeline/event/build-chains`
- Produces: `GET /api/pipeline/event/{op}/status`
- Consumes: `ai_client.build_panoramic_context()`, `ai_client.build_chains_panoramic()`, `ai_client.rank_events_panoramic()`
- Consumes: existing `_batch_ai_recluster()`, `_batch_ai_summarize_events()`, `_build_logic_chains()` logic from `pipeline.py`

```python
"""事件级管线 API — 聚类→摘要→逻辑链。凌晨 1:00 定时 / 管理员手动触发。"""
import threading, logging, time
from datetime import datetime
from fastapi import APIRouter

from config import config
from utils.task_lock import task_lock
from utils.task_state import task_state
from utils.db import get_db_connection, safe_commit

router = APIRouter(prefix="/api/pipeline/event", tags=["pipeline-event"])
logger = logging.getLogger(__name__)

_event_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "",
                "log": [], "steps": [], "cancelled": False}
_recl_state = _new_state_like()
_es_state = _new_state_like()
_chain_state = _new_state_like()


def _new_state_like():
    return {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "cancelled": False}


def _nightly():
    """线性执行三个阶段：聚类 → 摘要 → 逻辑链"""
    global _event_state, _recl_state, _es_state, _chain_state

    steps = [
        ("事件聚类", _run_recluster, _recl_state, 'recluster'),
        ("事件摘要", _run_summarize, _es_state, 'summarize_events'),
        ("逻辑链构建", _run_build_chains, _chain_state, 'build_chains'),
    ]

    _event_state["running"] = True
    _event_state["steps"] = [{"name": name, "status": "pending"} for name, _, _, _ in steps]
    _event_state["total"] = len(steps)

    for i, (name, fn, st, lock_name) in enumerate(steps):
        if _event_state.get("cancelled"):
            _event_state["steps"][i]["status"] = "cancelled"
            break
        _event_state["steps"][i]["status"] = "running"
        _event_state["current"] = name
        _event_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始: {name}")
        try:
            fn()
            while st.get("running"):
                if _event_state.get("cancelled"):
                    break
                time.sleep(2)
            _event_state["steps"][i]["status"] = "done"
            _event_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {name} 完成")
        except Exception as e:
            _event_state["steps"][i]["status"] = "failed"
            _event_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {name}: {e}")
            logger.error(f"nightly {name}: {e}")

    _event_state["running"] = False
    _event_state["current"] = "完成"
    task_lock.release('event')
    task_state.finish('event', success=True)


def _run_recluster():
    global _recl_state
    _recl_state.clear(); _recl_state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "cancelled": False})
    try:
        from ai_client import match_article_to_events_ai
        from db.news_db import title_similarity
        import json
        db = get_db_connection(config.db_path)
        unlinked = db.execute("SELECT a.id, a.title FROM news_articles a LEFT JOIN news_article_events ae ON a.id=ae.article_id WHERE ae.article_id IS NULL AND a.content_status IN ('fetched', 'translated')").fetchall()
        events = db.execute("SELECT id, title FROM events WHERE status='active'").fetchall()
        _recl_state["total"] = len(unlinked)
        _recl_state["log"].append(f"待聚类 {len(unlinked)} 篇 → {len(events)} 个活跃事件")
        db.close()
        if not unlinked:
            _recl_state["running"] = False; return
        for aid, art_title in unlinked:
            candidates = [(eid, etitle) for eid, etitle in events
                         if title_similarity(art_title, etitle) > 0.1][:50]
            try:
                r = match_article_to_events_ai(art_title, candidates)
                if r and r.get("event_id"):
                    db2 = get_db_connection(config.db_path)
                    db2.execute("INSERT OR IGNORE INTO news_article_events (article_id, event_id) VALUES (?,?)", (aid, r["event_id"]))
                    safe_commit(db2); db2.close()
                    _recl_state["done"] += 1
                else:
                    _recl_state["failed"] += 1
            except Exception as e:
                _recl_state["failed"] += 1
                _recl_state["log"].append(f"#{aid} ❌ {e}")
            time.sleep(0.1)
    except Exception as e:
        logger.error(f"recluster: {e}")
    finally:
        _recl_state["running"] = False
        task_lock.release('recluster')


def _run_summarize():
    global _es_state
    _es_state.clear(); _es_state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "cancelled": False})
    try:
        from ai_client import generate_event_summary_ai
        db = get_db_connection(config.db_path)
        events = db.execute("SELECT id FROM events WHERE article_count>=2 AND (ai_summary IS NULL OR ai_summary='')").fetchall()
        _es_state["total"] = len(events)
        db.close()
        for (eid,) in events:
            db2 = get_db_connection(config.db_path)
            titles = [r[0] for r in db2.execute("SELECT a.title FROM news_articles a JOIN news_article_events ae ON ae.article_id=a.id WHERE ae.event_id=? LIMIT 20", (eid,)).fetchall()]
            db2.close()
            if len(titles) < 2: continue
            try:
                block = "\n".join(f"- {t}" for t in titles)
                summary = generate_event_summary_ai(block)
                if summary:
                    db3 = get_db_connection(config.db_path)
                    db3.execute("UPDATE events SET ai_summary=? WHERE id=?", (summary, eid))
                    safe_commit(db3); db3.close()
                    _es_state["done"] += 1
            except Exception as e:
                _es_state["failed"] += 1
            time.sleep(0.1)
    finally:
        _es_state["running"] = False
        task_lock.release('summarize_events')


def _run_build_chains():
    global _chain_state
    _chain_state.clear(); _chain_state.update({"running": True, "total_groups": 0, "chains_created": 0, "current": "", "log": [], "cancelled": False})
    try:
        from ai_client import build_panoramic_context, build_chains_panoramic
        from datetime import datetime as _dt
        db = get_db_connection(config.db_path)
        context = build_panoramic_context(db)
        _chain_state["log"].append("全景图已构建，请求 AI 识别逻辑链...")
        groups = build_chains_panoramic(context)
        if not groups:
            _chain_state["log"].append("⚠️ AI 未返回有效分组")
            return
        _chain_state["total_groups"] = len(groups)
        for group in groups:
            event_ids = group.get("events", [])
            chain_title = group.get("title", "")
            reason = group.get("reason", "")
            if len(event_ids) < 2 or not chain_title:
                continue
            valid = [eid for eid in event_ids if db.execute("SELECT id FROM events WHERE id=? AND status='active'", (eid,)).fetchone()]
            if len(valid) < 2:
                continue
            existing = db.execute(f"SELECT DISTINCT chain_id FROM chain_events WHERE event_id IN ({','.join('?'*len(valid))})", valid).fetchall()
            if existing:
                continue
            now = _dt.now().isoformat(timespec='seconds')
            cur = db.execute("INSERT INTO logic_chains (title, description, created_at, updated_at, created_by) VALUES (?,?,?,?,'auto')",
                             (chain_title[:100], f"AI 全景推理 — {reason}", now, now))
            chain_id = cur.lastrowid
            for pos, eid in enumerate(valid):
                db.execute("INSERT INTO chain_events (chain_id, event_id, position, note) VALUES (?,?,?,?)",
                           (chain_id, eid, pos, f"AI: {reason}"[:200]))
            _chain_state["chains_created"] += 1
            _chain_state["log"].append(f"✅ {chain_title} ({len(valid)} 事件) — {reason}")
        safe_commit(db)
        db.close()
    except Exception as e:
        logger.error(f"build_chains: {e}")
    finally:
        _chain_state["running"] = False
        task_lock.release('build_chains')


# ── Endpoints ──

@router.post("/nightly")
def start_nightly():
    global _event_state
    if _event_state.get("running"):
        return {"ok": False, "message": "事件管线已在运行中"}
    ok, msg = task_lock.acquire('event')
    if not ok:
        return {"ok": False, "message": msg}
    task_state.init_state('event')
    threading.Thread(target=_nightly, daemon=True).start()
    return {"ok": True, "message": "事件管线已启动（聚类→摘要→逻辑链）"}


@router.get("/status")
def get_event_status():
    return dict(_event_state)


@router.post("/{op}/cancel")
def cancel_event_op(op: str):
    states = {"recluster": _recl_state, "summarize": _es_state, "build-chains": _chain_state}
    if op in states:
        states[op]["cancelled"] = True
        _event_state["cancelled"] = True
        return {"ok": True, "message": f"{op} 取消信号已发送"}
    return {"ok": False, "message": f"未知操作: {op}"}


# 独立操作端点
@router.post("/recluster")
def start_recluster():
    global _recl_state
    if _recl_state.get("running"): return {"ok": False, "message": "重聚类已在运行中"}
    ok, msg = task_lock.acquire('recluster')
    if not ok: return {"ok": False, "message": msg}
    threading.Thread(target=_run_recluster, daemon=True).start()
    return {"ok": True, "message": "事件重聚类已启动"}

@router.get("/recluster/status")
def get_recluster_status(): return dict(_recl_state)

@router.post("/summarize")
def start_summarize():
    global _es_state
    if _es_state.get("running"): return {"ok": False, "message": "摘要已在运行中"}
    ok, msg = task_lock.acquire('summarize_events')
    if not ok: return {"ok": False, "message": msg}
    threading.Thread(target=_run_summarize, daemon=True).start()
    return {"ok": True, "message": "事件摘要已启动"}

@router.get("/summarize/status")
def get_summarize_status(): return dict(_es_state)

@router.post("/build-chains")
def start_build_chains():
    global _chain_state
    if _chain_state.get("running"): return {"ok": False, "message": "逻辑链构建已在运行中"}
    ok, msg = task_lock.acquire('build_chains')
    if not ok: return {"ok": False, "message": msg}
    threading.Thread(target=_run_build_chains, daemon=True).start()
    return {"ok": True, "message": "逻辑链构建已启动"}

@router.get("/build-chains/status")
def get_build_chains_status(): return dict(_chain_state)
```

- [ ] **Step 1: Write `pipeline_event.py`**

Write the complete file as shown above.

- [ ] **Step 2: Verify imports**

Run: `cd news-web/backend && python -c "from api.pipeline_event import router; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/api/pipeline_event.py
git commit -m "feat: add pipeline_event.py API — event-level linear pipeline endpoints"
```

---

### Task 4: Register New Routers in `main.py` and Clean Up `pipeline.py`

**Files:**
- Modify: `news-web/backend/main.py`
- Modify: `news-web/backend/api/pipeline.py` (strip to just keep `batch-ai-filter` endpoint)

- [ ] **Step 1: In `main.py`, find the pipeline router registration and replace**

Find: `from api.pipeline import router as pipeline_router`  
Replace with:
```python
from api.pipeline_article import router as pipeline_article_router
from api.pipeline_event import router as pipeline_event_router
```

Find: `app.include_router(pipeline_router)`  
Replace with:
```python
app.include_router(pipeline_article_router)
app.include_router(pipeline_event_router)
```

Find and remove the old `from api import pipeline` import if separate.

- [ ] **Step 2: In `pipeline.py`, keep only `_batch_ai_filter()` and its endpoints**

Delete all batch functions except `_batch_ai_filter()` (lines 1267-1323) and its three endpoints (`start_batch_ai_filter`, `get_batch_ai_filter_status`, force reset). Delete helper functions `_check_and_lock`, `_unlock`, `_force_reset` if they're only used by removed functions. Keep shared utilities (`_conn`, `_reset_state`, `_check_cancelled`, `_queue_retry`, `_new_state`).

Keep the `ai_filter` endpoints since RSS title filtering is still needed:
- `POST /api/pipeline/batch-ai-filter`
- `GET /api/pipeline/batch-ai-filter/status`

Move `_batch_ai_filter` and its helpers into `pipeline_event.py` or keep a minimal `pipeline.py`.

- [ ] **Step 3: Verify app starts**

Run: `cd news-web/backend && timeout 5 python main.py 2>&1 || true` — check for import errors

- [ ] **Step 4: Commit**

```bash
git add news-web/backend/main.py news-web/backend/api/pipeline.py
git commit -m "refactor: register new pipeline routers, strip old pipeline.py endpoints"
```

---

### Task 5: Update Scheduler — 1:00 AM Event Pipeline

**Files:**
- Modify: `news-web/backend/scheduler.py`
- Modify: `news-web/backend/config.py` (default cron hours)

- [ ] **Step 1: Update default config**

In `config.py`, change `ai_cron_hours` default from `[15, 22]` to `[1]`:

```python
'ai_cron_hours': [1],               # 事件级管线每天运行的小时数（凌晨1点）
'ai_cron_minutes': [0],
```

- [ ] **Step 2: Update `_run_ai_full_job_sync()` in scheduler.py**

Replace its body to call the new event pipeline instead of `_batch_ai_full()`:

```python
def _run_ai_full_job_sync():
    """凌晨 1:00 — 事件级管线：聚类→摘要→逻辑链"""
    from api.pipeline_event import _nightly
    try:
        _nightly()
    except Exception as e:
        logger.error(f"Event pipeline job failed: {e}")
```

Update the function docstring and log messages accordingly — "AI 全流程" → "事件管线".

- [ ] **Step 3: Update `trigger_ai_full_manual()`**

Change to call `_nightly()` instead.

- [ ] **Step 4: Verify scheduler loads**

Run: `cd news-web/backend && python -c "from scheduler import start_scheduler; print('OK')"`

- [ ] **Step 5: Commit**

```bash
git add news-web/backend/scheduler.py news-web/backend/config.py
git commit -m "feat: scheduler now triggers event pipeline at 1:00 AM"
```

---

### Task 6: Simplify `ai_config.py` — 10 Endpoints → 3 Groups

**Files:**
- Modify: `news-web/backend/ai_config.py`

- [ ] **Step 1: Replace `AI_ENDPOINTS` dict**

Replace the 10-endpoint dict with 3 groups:

```python
AI_ENDPOINTS = {
    'title_filter': {
        'name': '标题初筛',
        'description': 'RSS 抓取后的标题批量筛选，判断文章是否值得缓存',
        'default_model': 'deepseek-ai/DeepSeek-V4-Flash',
        'params': ['enable_thinking', 'json_response_format'],
        'legacy_field': 'rss_prefilter',
    },
    'article_processing': {
        'name': '文章处理',
        'description': '内容清洗、翻译、分析摘要、KCS（关键词+分类+评分）',
        'default_model': 'deepseek-ai/DeepSeek-V4-Flash',
        'params': ['enable_thinking', 'thinking_budget'],
        'legacy_field': 'openai',
    },
    'event_pipeline': {
        'name': '事件管线',
        'description': '事件聚类、摘要生成、逻辑链构建',
        'default_model': 'deepseek-ai/DeepSeek-V4-Flash',
        'params': ['enable_thinking', 'thinking_budget'],
        'legacy_field': 'openai',
    },
}
```

- [ ] **Step 2: Update `_get_endpoint_model()`**

```python
def _get_endpoint_model(endpoint_key: str) -> str:
    if endpoint_key == 'title_filter':
        return config.simple_model
    elif endpoint_key in ('article_processing', 'event_pipeline'):
        return config.openai_model
    return config.openai_model
```

- [ ] **Step 3: Update legacy field mappings**

Remove `keyword_extraction`, `article_classification`, `priority_scoring`, `event_ranking` from `_LEGACY_TO_ENDPOINT`. Clean up any other references.

- [ ] **Step 4: Update `apply_ai_endpoint_config()`**

Ensure the body parsing maps the 3 new groups correctly. Update `_get_endpoint_config()` return.

- [ ] **Step 5: Verify**

Run: `cd news-web/backend && python -c "from ai_config import to_ai_endpoint_config; c = to_ai_endpoint_config(); print(list(c['ai_endpoints'].keys()))"`  
Expected: `['title_filter', 'article_processing', 'event_pipeline']`

- [ ] **Step 6: Commit**

```bash
git add news-web/backend/ai_config.py
git commit -m "refactor: collapse 10 AI endpoints into 3 groups (title_filter/article_processing/event_pipeline)"
```

---

### Task 7: Frontend — Simplify Dashboard

**Files:**
- Modify: `news-web/frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Remove old state and timers**

Remove `translating`, `analyzing`, `chaining`, `reclRunning`, `esRunning`, `cleanRunning`, `fullRunning` and all associated `useState` declarations, `useRef` timers, and polling functions. Remove old `useEffect` polling for translate/analyze/chains/recluster/es/clean/full.

Keep: `kcsRunning`/`kcsState`, `stats`, `loading`, `toast`.

Add new state:
```tsx
const [articleRunning, setArticleRunning] = useState(false);
const [articleState, setArticleState] = useState<BatchState>(emptyBatch);
const [eventRunning, setEventRunning] = useState(false);
const [eventState, setEventState] = useState<BatchState>(emptyBatch);
const articleTimer = useRef<ReturnType<typeof setInterval>>();
const eventTimer = useRef<ReturnType<typeof setInterval>>();
```

- [ ] **Step 2: Add new polling**

```tsx
useEffect(() => {
  api.getArticleStatus().then((s) => {
    const st = s as BatchState;
    if (st.running) { setArticleRunning(true); articleTimer.current = setInterval(pollArticle, 2000); }
    else setArticleState(st);
  }).catch(() => {});
  api.getEventStatus().then((s) => {
    const st = s as BatchState;
    if (st.running) { setEventRunning(true); eventTimer.current = setInterval(pollEvent, 2000); }
    else setEventState(st);
  }).catch(() => {});
  api.getBatchKcsStatus().then((s) => {
    const st = s as BatchState;
    if (st.running) { setKcsRunning(true); kcsTimer.current = setInterval(pollKcs, 2000); }
    else setKcsState(st);
  }).catch(() => {});
  return () => { [articleTimer, eventTimer, kcsTimer].forEach(t => clearInterval(t.current)); };
}, []);
```

- [ ] **Step 3: Replace card section**

Replace lines ~260-500 (all AICard instances) with two cards:

```tsx
<div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 16, marginTop: 16 }}>
  {/* 文章处理 */}
  <Card>
    <CardHeader icon="fa-newspaper" iconColor="var(--accent-blue)" title="📰 文章处理" desc="缓存→清洗→翻译→分析+KCS" />
    <CardBody>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Button variant={articleRunning ? 'ghost' : 'primary'} onClick={articleRunning ? () => handleStop('article') : handleArticleBatch}
                icon={articleRunning ? 'fa-stop' : 'fa-play'}>
          {articleRunning ? '停止' : '一键处理全部'}
        </Button>
      </div>
      {articleRunning && <ProgressBar done={articleState.done} total={articleState.total} color="var(--accent-blue)" />}
      {articleRunning && articleState.log && <LogPanel entries={articleState.log} />}
    </CardBody>
  </Card>

  {/* 事件管线 */}
  <Card>
    <CardHeader icon="fa-link" iconColor="var(--accent)" title="🔗 事件管线" desc="聚类→摘要→逻辑链 · 凌晨1:00自动执行" />
    <CardBody>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Button variant={eventRunning ? 'ghost' : 'primary'} onClick={eventRunning ? () => handleStop('event') : handleEventNightly}
                icon={eventRunning ? 'fa-stop' : 'fa-play'}>
          {eventRunning ? '停止' : '启动事件管线'}
        </Button>
        <Button variant="ghost" onClick={handleRecluster} disabled={eventRunning}>重聚类</Button>
        <Button variant="ghost" onClick={handleSummarize} disabled={eventRunning}>生成摘要</Button>
        <Button variant="ghost" onClick={handleBuildChains} disabled={eventRunning}>构建逻辑链</Button>
      </div>
      {eventRunning && eventState.steps && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          {eventState.steps.map((s: {name:string,status:string}, i: number) => (
            <span key={i} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10,
              background: s.status === 'done' ? 'rgba(129,199,132,0.12)' : s.status === 'running' ? 'rgba(0,212,255,0.12)' : 'transparent' }}>
              {s.status === 'done' ? '✅' : s.status === 'running' ? '⏳' : '⬜'} {s.name}
            </span>
          ))}
        </div>
      )}
      {eventRunning && eventState.log && <LogPanel entries={eventState.log} />}
    </CardBody>
  </Card>
</div>
```

- [ ] **Step 4: Add handler functions**

```tsx
const pollArticle = useCallback(() => poll(api.getArticleStatus, v => {const s=v as BatchState; setArticleState(s); if(!s.running){setArticleRunning(false);clearInterval(articleTimer.current)}},(()=>setArticleRunning(false)),articleTimer),[]);
const handleArticleBatch = startPoll(api.startArticleBatch, pollArticle, articleTimer, setArticleRunning);

const pollEvent = useCallback(() => poll(api.getEventStatus, v => {const s=v as BatchState; setEventState(s); if(!s.running){setEventRunning(false);clearInterval(eventTimer.current)}},(()=>setEventRunning(false)),eventTimer),[]);
const handleEventNightly = startPoll(api.startEventNightly, pollEvent, eventTimer, setEventRunning);

const handleRecluster = startPoll(api.startRecluster, pollEvent, eventTimer, setEventRunning);
// ... similar for summarize, buildChains
```

- [ ] **Step 5: Remove old AICard imports**

Remove `DashboardCards` import (if AICard was from there). Clean up unused imports.

- [ ] **Step 6: Build and verify**

Run: `cd news-web/frontend && npm run build` — must compile without errors.

- [ ] **Step 7: Commit**

```bash
git add news-web/frontend/src/pages/Dashboard.tsx
git commit -m "refactor: Dashboard simplified to 2 cards (article + event pipeline)"
```

---

### Task 8: Frontend — Update API Client

**Files:**
- Modify: `news-web/frontend/src/api/client.ts`

- [ ] **Step 1: Add new API functions**

```typescript
// Article pipeline
startArticleBatch: () => fetchJSON<{ ok: boolean; message: string; pending: number }>('/pipeline/article/batch-process', { method: 'POST' }),
getArticleStatus: () => fetchJSON<BatchState>('/pipeline/article/status'),
processArticle: (id: number) => fetchJSON<{ ok: boolean; steps: Record<string, unknown>; error: string }>(`/pipeline/article/${id}/process`, { method: 'POST' }),

// Event pipeline
startEventNightly: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/event/nightly', { method: 'POST' }),
getEventStatus: () => fetchJSON<BatchState>('/pipeline/event/status'),
cancelEventOp: (op: string) => fetchJSON<{ ok: boolean; message: string }>(`/pipeline/event/${op}/cancel`, { method: 'POST' }),

// Event standalone
startRecluster: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/event/recluster', { method: 'POST' }),
getReclusterStatus: () => fetchJSON<BatchState>('/pipeline/event/recluster/status'),
startSummarize: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/event/summarize', { method: 'POST' }),
getSummarizeStatus: () => fetchJSON<BatchState>('/pipeline/event/summarize/status'),
startBuildChains: () => fetchJSON<{ ok: boolean; message: string }>('/pipeline/event/build-chains', { method: 'POST' }),
getBuildChainsStatus: () => fetchJSON<BatchState>('/pipeline/event/build-chains/status'),
```

- [ ] **Step 2: Remove old API functions**

Remove: `startBatchTranslate`, `getBatchTranslateStatus`, `cancelBatchTranslate`, `forceResetBatchTranslate`, `startBatchAnalyze`, `getBatchAnalyzeStatus`, `cancelBatchAnalyze`, `forceResetBatchAnalyze`, `startBatchClean`, `getBatchCleanStatus`, `cancelBatchClean`, `forceResetBatchClean`, `startBatchKeywords`, `getBatchKeywordsStatus`, `startBatchClassify`, `getBatchClassifyStatus`, `startBatchScore`, `getBatchScoreStatus`, `startBatchRankEvents`, `getBatchRankEventsStatus`, `startBatchRecluster`, `getBatchReclusterStatus`, `startBatchSummarizeEvents`, `getBatchSummarizeEventsStatus`, `startBatchAiFull`, `getBatchAiFullStatus`, `cancelBatchAiFull`, `forceResetBatchAiFull`.

Keep: `startBatchKcs`, `getBatchKcsStatus`, `cancelBatchKcs`, `forceResetBatchKcs` (KCS standalone still used).

- [ ] **Step 3: Verify build**

Run: `cd news-web/frontend && npm run build`

- [ ] **Step 4: Commit**

```bash
git add news-web/frontend/src/api/client.ts
git commit -m "refactor: update API client — new article/event pipeline + remove old endpoints"
```

---

### Task 9: Frontend — Restructure AISettings (3 Groups)

**Files:**
- Modify: `news-web/frontend/src/pages/settings/AISettings.tsx`

- [ ] **Step 1: Update `ENDPOINT_META`**

Replace 10-endpoint map with 3 groups:
```tsx
const ENDPOINT_META: Record<string, { name: string; description: string; group: string }> = {
  title_filter: { name: '标题初筛', description: 'RSS 抓取后的标题批量筛选', group: '数据采集' },
  article_processing: { name: '文章处理', description: '清洗 · 翻译 · 分析 · KCS 合并', group: '文章处理' },
  event_pipeline: { name: '事件管线', description: '聚类 · 摘要 · 逻辑链构建', group: '事件管线' },
};
const GROUP_ORDER = ['数据采集', '文章处理', '事件管线'];
```

- [ ] **Step 2: Simplify props**

Remove old props (`translationEnabled`, `translationBaseUrl`, `translationApiKey`, `translationModel`, `deepThinkingMaxTokens`, `jsonResponseFormat`) and their setters. Keep only what's needed for 3 groups: endpoint config fetching/saving.

- [ ] **Step 3: Verify build**

Run: `cd news-web/frontend && npm run build`

- [ ] **Step 4: Commit**

```bash
git add news-web/frontend/src/pages/settings/AISettings.tsx
git commit -m "refactor: AISettings simplified to 3 groups (title_filter/article_processing/event_pipeline)"
```

---

### Task 10: Tests

**Files:**
- Create: `news-web/tests/backend/test_pipeline_article.py`
- Create: `news-web/tests/backend/test_pipeline_event.py`
- Modify: `news-web/tests/backend/test_api.py`

- [ ] **Step 1: Create `test_pipeline_article.py`**

```python
"""文章管线测试"""
import pytest
from fastapi.testclient import TestClient
from main import app
from config import config

client = TestClient(app)

def test_process_single_article_not_found():
    r = client.post("/api/pipeline/article/99999/process")
    assert r.status_code == 200
    assert r.json()["ok"] == False

def test_get_article_status_idle():
    r = client.get("/api/pipeline/article/status")
    assert r.status_code == 200
    assert r.json()["running"] == False

def test_start_batch_process_needs_lock():
    r = client.post("/api/pipeline/article/batch-process")
    assert r.status_code == 200
    # Should either start or return "already running" message
    assert "ok" in r.json()
```

- [ ] **Step 2: Create `test_pipeline_event.py`**

```python
"""事件管线测试"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_get_event_status_idle():
    r = client.get("/api/pipeline/event/status")
    assert r.status_code == 200
    assert r.json()["running"] == False

def test_start_nightly():
    r = client.post("/api/pipeline/event/nightly")
    assert r.status_code == 200
    assert "ok" in r.json()

def test_recluster_status():
    r = client.get("/api/pipeline/event/recluster/status")
    assert r.status_code == 200
    assert "running" in r.json()

def test_summarize_status():
    r = client.get("/api/pipeline/event/summarize/status")
    assert r.status_code == 200

def test_build_chains_status():
    r = client.get("/api/pipeline/event/build-chains/status")
    assert r.status_code == 200
```

- [ ] **Step 3: Clean up `test_api.py`**

Remove test functions that reference deleted endpoints: `test_batch_translate_*`, `test_batch_analyze_*`, `test_batch_ai_full_*`, `test_merge_events` (if it calls old pipeline endpoints). Keep tests for auth, stats, settings, chains.

- [ ] **Step 4: Run all tests**

Run: `cd news-web && python -m pytest tests/backend/ -v`  
Expected: all tests pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add news-web/tests/backend/
git commit -m "test: add pipeline_article + pipeline_event tests, clean up old pipeline tests"
```

---

### Task 11: Final Integration — Deploy and Verify

- [ ] **Step 1: Run full test suite**

```bash
cd news-web && python -m pytest tests/backend/ -v
```

- [ ] **Step 2: Build frontend**

```bash
cd news-web/frontend && npm run build
```

- [ ] **Step 3: Restart backend**

```bash
bash /srv/LapTalk_NewsAggregationTool/start_platform.sh stop
sleep 1
bash /srv/LapTalk_NewsAggregationTool/start_platform.sh start
```

- [ ] **Step 4: Smoke test endpoints**

```bash
curl -s http://localhost:8081/api/pipeline/article/status | python3 -m json.tool
curl -s http://localhost:8081/api/pipeline/event/status | python3 -m json.tool
curl -s http://localhost:8081/api/health
```

- [ ] **Step 5: Commit and push**

```bash
git add -A
git commit -m "chore: final integration — pipeline refactor complete"
git push origin main
```
