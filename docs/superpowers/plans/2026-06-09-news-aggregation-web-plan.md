# News Aggregation Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a knowledge aggregation center Web UI that reads from the claw_skill_news_aggregation SQLite database and lets users search articles, review AI-clustered events, and construct logic chains via drag-and-drop on a React Flow canvas. Also includes an integrated pipeline scheduler that replaces the Hermes/OpenClaw node by running the news fetch-collect-analyze cycle on a cron schedule.

**Architecture:** Python FastAPI backend that both serves the Web API and runs the news pipeline (fetch → cluster → analyze) via APScheduler; React + Vite + React Flow frontend; shared SQLite database with WAL mode. OpenAI-compatible API configuration for AI-powered analysis steps (supporting OpenAI, DeepSeek, Ollama, or any compatible endpoint).

**Tech Stack:** Python FastAPI, SQLite, APScheduler, OpenAI-compatible API (openai library), React 18, Vite, React Flow (xyflow), TypeScript, Vitest, pytest

---

## File Structure

```
news-web/
├── backend/
│   ├── main.py                # FastAPI app factory, CORS, static mount, lifespan
│   ├── config.py              # Config load/save from config.json
│   ├── scheduler.py           # APScheduler: daily 10:00 + 17:00 pipeline runs
│   ├── ai_client.py           # OpenAI-compatible API wrapper
│   ├── api/
│   │   ├── __init__.py
│   │   ├── stats.py           # GET /api/stats
│   │   ├── articles.py        # Article search/review/content proxy
│   │   ├── events.py          # Event CRUD/merge/split
│   │   ├── chains.py          # Logic chain CRUD/splice/split/reorder
│   │   ├── relations.py       # Event relations + AI suggestions
│   │   └── settings.py        # GET/PUT /api/settings
│   ├── db/
│   │   ├── news_db.py         # Copied from Skill repo ORM layer
│   │   └── __init__.py
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── run_all.py         # Orchestrates the full fetch→cluster→analyze cycle
│   │   ├── fetch_english_news.py  # Copied from Skill repo (RSS fetcher)
│   │   ├── collect_data.py        # Copied from Skill repo (dedup+cluster)
│   │   ├── fetch_content.py       # Copied from Skill repo (page archiver)
│   │   ├── analyze.py             # Copied from Skill repo (Agent analysis)
│   │   └── cron_runner.sh         # Copied reference (replaced by scheduler.py)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/
│   │   │   └── client.ts      # Fetch wrapper + typed API methods
│   │   ├── types/
│   │   │   └── index.ts       # TS interfaces matching API responses
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Workspace.tsx
│   │   │   ├── ArticleSearch.tsx
│   │   │   ├── ChainList.tsx
│   │   │   └── Settings.tsx
│   │   ├── components/
│   │   │   ├── NavSidebar.tsx
│   │   │   ├── DashboardCards.tsx
│   │   │   ├── SearchPanel.tsx
│   │   │   ├── ArticleBlock.tsx
│   │   │   ├── EventCard.tsx
│   │   │   ├── ChainCanvas.tsx
│   │   │   └── RelationDialog.tsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── config.json                 # Runtime config: db_path, user_agent, openai_*
└── tests/
    └── backend/
        ├── conftest.py
        └── test_api.py
```

---

### Task 1: Backend Scaffold + Config System

**Files:**
- Create: `news-web/backend/requirements.txt`
- Create: `news-web/backend/config.py`
- Create: `news-web/backend/main.py`
- Create: `news-web/backend/api/__init__.py`
- Create: `news-web/config.json`

- [ ] **Step 1: Write requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
httpx==0.27.0
pytest==8.3.0
```

- [ ] **Step 2: Write backend/config.py**

```python
import json, os
from typing import Optional

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

DEFAULT_CONFIG = {
    'db_path': '',
    'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'openai_base_url': 'https://api.openai.com/v1',
    'openai_api_key': '',
    'openai_model': 'gpt-4o-mini',
    'pipeline_schedule_enabled': True,
}

class AppConfig:
    def __init__(self):
        self._data = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    self._data.update(json.load(f))
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @property
    def db_path(self) -> str:
        return self._data.get('db_path', '')

    @db_path.setter
    def db_path(self, val: str):
        self._data['db_path'] = val
        self.save()

    @property
    def user_agent(self) -> str:
        return self._data.get('user_agent', DEFAULT_CONFIG['user_agent'])

    @user_agent.setter
    def user_agent(self, val: str):
        self._data['user_agent'] = val
        self.save()

    @property
    def openai_base_url(self) -> str:
        return self._data.get('openai_base_url', DEFAULT_CONFIG['openai_base_url'])

    @openai_base_url.setter
    def openai_base_url(self, val: str):
        self._data['openai_base_url'] = val
        self.save()

    @property
    def openai_api_key(self) -> str:
        return self._data.get('openai_api_key', '')

    @openai_api_key.setter
    def openai_api_key(self, val: str):
        self._data['openai_api_key'] = val
        self.save()

    @property
    def openai_model(self) -> str:
        return self._data.get('openai_model', DEFAULT_CONFIG['openai_model'])

    @openai_model.setter
    def openai_model(self, val: str):
        self._data['openai_model'] = val
        self.save()

    @property
    def pipeline_schedule_enabled(self) -> bool:
        return self._data.get('pipeline_schedule_enabled', True)

    @pipeline_schedule_enabled.setter
    def pipeline_schedule_enabled(self, val: bool):
        self._data['pipeline_schedule_enabled'] = val
        self.save()

    def to_dict(self) -> dict:
        # Mask API key in serialized output
        d = dict(self._data)
        if d.get('openai_api_key'):
            d['openai_api_key'] = '***'
        return d

config = AppConfig()
```

- [ ] **Step 3: Write backend/api/__init__.py** (empty file)

- [ ] **Step 4: Write backend/main.py**

```python
import os, sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import config

app = FastAPI(title="News Aggregation Web")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok", "db_path": config.db_path or "(not configured)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
```

- [ ] **Step 5: Write config.json**

```json
{
  "db_path": "",
  "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
  "openai_base_url": "https://api.openai.com/v1",
  "openai_api_key": "",
  "openai_model": "gpt-4o-mini",
  "pipeline_schedule_enabled": true
}
```

- [ ] **Step 6: Verify backend starts**

Run: `cd backend && pip install -r requirements.txt && python main.py`
Expected: uvicorn starts on port 8080, `curl http://localhost:8080/api/health` returns `{"status":"ok"}`

- [ ] **Step 7: Commit**

```bash
git add news-web/backend/requirements.txt news-web/backend/config.py news-web/backend/main.py news-web/backend/api/__init__.py news-web/config.json
git commit -m "feat: add backend scaffold with config system"
```

---

### Task 2: Database Layer — Copy news_db.py + Add Migrations

**Files:**
- Create: `news-web/backend/db/__init__.py`
- Create: `news-web/backend/db/news_db.py` (copied from Skill repo)
- Create: `news-web/backend/db/migrations.py`

- [ ] **Step 1: Copy news_db.py from Skill repo**

Run:
```bash
cp /tmp/claw_skill_news_aggregation/news_db.py news-web/backend/db/news_db.py
```

- [ ] **Step 2: Write db/__init__.py**

```python
from .news_db import NewsDB, extract_keywords, extract_entities, title_similarity
```

- [ ] **Step 3: Write backend/db/migrations.py**

```python
import sqlite3
from config import config

LOGIC_CHAINS_SQL = """
CREATE TABLE IF NOT EXISTS logic_chains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    created_by  TEXT DEFAULT 'human'
);

CREATE TABLE IF NOT EXISTS chain_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER NOT NULL REFERENCES logic_chains(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id),
    position INTEGER NOT NULL,
    note     TEXT DEFAULT '',
    UNIQUE(chain_id, event_id)
);

CREATE TABLE IF NOT EXISTS chain_relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_chain_id INTEGER NOT NULL REFERENCES logic_chains(id) ON DELETE CASCADE,
    child_chain_id  INTEGER NOT NULL REFERENCES logic_chains(id),
    position        INTEGER NOT NULL,
    UNIQUE(parent_chain_id, child_chain_id)
);
"""

def ensure_schema(db_path: str):
    """Run migrations on the target database. Idempotent — uses IF NOT EXISTS."""
    if not db_path:
        return
    conn = sqlite3.connect(db_path)
    conn.executescript("PRAGMA journal_mode=WAL;")
    conn.executescript(LOGIC_CHAINS_SQL)
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Update main.py to call migrations on startup**

In `backend/main.py`, add import and startup event:

```python
# Add after existing imports
from contextlib import asynccontextmanager
from db.migrations import ensure_schema

@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.db_path:
        ensure_schema(config.db_path)
    yield

# Change app creation line to:
app = FastAPI(title="News Aggregation Web", lifespan=lifespan)
```

- [ ] **Step 5: Verify migrations run**

Run: `cd backend && python -c "from db.migrations import ensure_schema; ensure_schema('/tmp/test_migrations.db')"`
Then verify tables exist: `sqlite3 /tmp/test_migrations.db ".tables"` shows `logic_chains`, `chain_events`, `chain_relations`.

- [ ] **Step 6: Commit**

```bash
git add news-web/backend/db/
git commit -m "feat: add database layer with logic_chains migrations"
```

---

### Task 3: Backend Settings + Stats API

**Files:**
- Create: `news-web/backend/api/settings.py`
- Create: `news-web/backend/api/stats.py`

- [ ] **Step 1: Write backend/api/settings.py**

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import config

router = APIRouter(prefix="/api/settings", tags=["settings"])

class SettingsUpdate(BaseModel):
    db_path: str | None = None
    user_agent: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    pipeline_schedule_enabled: bool | None = None

@router.get("")
def get_settings():
    return config.to_dict()

@router.put("")
def update_settings(body: SettingsUpdate):
    if body.db_path is not None:
        config.db_path = body.db_path
    if body.user_agent is not None:
        config.user_agent = body.user_agent
    if body.openai_base_url is not None:
        config.openai_base_url = body.openai_base_url
    if body.openai_api_key is not None:
        config.openai_api_key = body.openai_api_key
    if body.openai_model is not None:
        config.openai_model = body.openai_model
    if body.pipeline_schedule_enabled is not None:
        config.pipeline_schedule_enabled = body.pipeline_schedule_enabled
    return config.to_dict()
```

- [ ] **Step 2: Write backend/api/stats.py**

```python
from fastapi import APIRouter, HTTPException
from config import config
from db.news_db import NewsDB
from datetime import datetime, date

router = APIRouter(prefix="/api/stats", tags=["stats"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def get_stats():
    db = get_db()
    return db.get_stats()
```

- [ ] **Step 3: Register routers in main.py**

```python
# Add after existing imports
from api.settings import router as settings_router
from api.stats import router as stats_router

# Add after app creation
app.include_router(settings_router)
app.include_router(stats_router)
```

- [ ] **Step 4: Commit**

```bash
git add news-web/backend/api/settings.py news-web/backend/api/stats.py news-web/backend/main.py
git commit -m "feat: add settings and stats API endpoints"
```

---

### Task 4: Backend Articles API

**Files:**
- Create: `news-web/backend/api/articles.py`

- [ ] **Step 1: Write articles.py**

```python
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import httpx
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/articles", tags=["articles"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def list_articles(
    q: str = "",
    source: str = "",
    date_from: str = "",
    date_to: str = "",
    priority: str = "",
    verified: str = "",
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    """Search articles with multi-dimensional filtering."""
    db = get_db()
    with db._conn() as conn:
        clauses = []
        params = []
        if q:
            clauses.append("(a.title LIKE ? OR a.keywords LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if source:
            clauses.append("a.source = ?")
            params.append(source)
        if date_from:
            clauses.append("a.fetched_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("a.fetched_at <= ?")
            params.append(date_to)
        if priority in ('high', 'medium', 'low'):
            clauses.append("a.priority_label = ?")
            params.append(priority)
        if verified == 'yes':
            clauses.append("a.human_verified != 0")
        elif verified == 'no':
            clauses.append("a.human_verified = 0")

        where = " AND ".join(clauses) if clauses else "1=1"
        offset = (page - 1) * limit

        count = conn.execute(f"SELECT COUNT(*) FROM articles a WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT a.id, a.title, a.source, a.url, a.published_date, a.fetched_at,
                   a.priority_score, a.priority_label, a.human_verified, a.keywords, a.human_tags
            FROM articles a WHERE {where}
            ORDER BY a.fetched_at DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

    import json
    articles = [{
        'id': r[0], 'title': r[1], 'source': r[2], 'url': r[3],
        'published': r[4], 'fetched': r[5], 'score': r[6],
        'label': r[7], 'verified': r[8],
        'keywords': json.loads(r[9]) if r[9] else [],
        'human_tags': json.loads(r[10]) if r[10] else [],
    } for r in rows]

    return {'articles': articles, 'total': count, 'page': page, 'limit': limit}

@router.get("/{article_id}")
def get_article(article_id: int):
    db = get_db()
    with db._conn() as conn:
        row = conn.execute("""
            SELECT a.id, a.title, a.source, a.url, a.published_date, a.fetched_at,
                   a.priority_score, a.priority_label, a.human_verified, a.keywords, a.human_tags,
                   a.category, a.metadata
            FROM articles a WHERE a.id=?
        """, (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "article_not_found")
        # Find event membership
        evt = conn.execute("""
            SELECT e.id, e.title FROM events e
            JOIN article_events ae ON ae.event_id = e.id
            WHERE ae.article_id=?
        """, (article_id,)).fetchone()

    import json
    return {
        'id': row[0], 'title': row[1], 'source': row[2], 'url': row[3],
        'published': row[4], 'fetched': row[5], 'score': row[6],
        'label': row[7], 'verified': row[8],
        'keywords': json.loads(row[9]) if row[9] else [],
        'human_tags': json.loads(row[10]) if row[10] else [],
        'category': row[11], 'metadata': json.loads(row[12]) if row[12] else {},
        'event': {'id': evt[0], 'title': evt[1]} if evt else None,
    }

class ArticleUpdate(BaseModel):
    priority_label: Optional[str] = None
    human_tags: Optional[str] = None
    human_verified: Optional[int] = None

@router.patch("/{article_id}")
def update_article(article_id: int, body: ArticleUpdate):
    db = get_db()
    if body.priority_label:
        db.record_feedback(article_id, 'priority_label', body.priority_label)
    if body.human_tags:
        db.record_feedback(article_id, 'keywords', body.human_tags)
    if body.human_verified is not None:
        with db._conn() as conn:
            conn.execute("UPDATE articles SET human_verified=? WHERE id=?", (body.human_verified, article_id))
            conn.commit()
    return {'ok': True}

@router.get("/{article_id}/content")
async def proxy_article_content(article_id: int):
    """Proxy fetch the original article content, carrying the configured UA."""
    db = get_db()
    with db._conn() as conn:
        row = conn.execute("SELECT url FROM articles WHERE id=?", (article_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "no_url")
    async with httpx.AsyncClient() as client:
        resp = await client.get(row[0], headers={'User-Agent': config.user_agent}, follow_redirects=True, timeout=15)
    return resp.text
```

- [ ] **Step 2: Register router in main.py**

```python
from api.articles import router as articles_router
app.include_router(articles_router)
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/api/articles.py news-web/backend/main.py
git commit -m "feat: add articles search and review API"
```

---

### Task 5: Backend Events API

**Files:**
- Create: `news-web/backend/api/events.py`

- [ ] **Step 1: Write events.py**

```python
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/events", tags=["events"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def list_events(status: str = "", min_articles: int = Query(1, ge=1), page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    db = get_db()
    with db._conn() as conn:
        clauses = ["1=1"]
        params = []
        if status:
            clauses.append("e.status = ?")
            params.append(status)
        if min_articles > 1:
            clauses.append("e.article_count >= ?")
            params.append(min_articles)
        where = " AND ".join(clauses)
        offset = (page - 1) * limit
        count = conn.execute(f"SELECT COUNT(*) FROM events e WHERE {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT e.id, e.title, e.first_seen, e.last_seen, e.article_count, e.status
            FROM events e WHERE {where}
            ORDER BY e.last_seen DESC LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    return {
        'events': [{'id': r[0], 'title': r[1], 'first_seen': r[2], 'last_seen': r[3], 'article_count': r[4], 'status': r[5]} for r in rows],
        'total': count, 'page': page, 'limit': limit
    }

@router.get("/{event_id}")
def get_event(event_id: int):
    db = get_db()
    return db.get_event_timeline(event_id)

class EventUpdate(BaseModel):
    title: Optional[str] = None
    priority_label: Optional[str] = None

@router.patch("/{event_id}")
def update_event(event_id: int, body: EventUpdate):
    db = get_db()
    with db._conn() as conn:
        if body.title:
            conn.execute("UPDATE events SET title=? WHERE id=?", (body.title, event_id))
        if body.priority_label:
            # Apply priority to all articles in this event
            article_ids = conn.execute(
                "SELECT article_id FROM article_events WHERE event_id=?", (event_id,)
            ).fetchall()
            for (aid,) in article_ids:
                db.record_feedback(aid, 'priority_label', body.priority_label)
        conn.commit()
    return {'ok': True}

class MergeEvents(BaseModel):
    target_event_id: int

@router.post("/{event_id}/merge")
def merge_events(event_id: int, body: MergeEvents):
    """Merge event_id INTO target_event_id. Moves all articles and updates dates."""
    db = get_db()
    if event_id == body.target_event_id:
        raise HTTPException(400, "cannot_merge_with_self")
    with db._conn() as conn:
        src = conn.execute("SELECT first_seen, last_seen, article_count FROM events WHERE id=?", (event_id,)).fetchone()
        tgt = conn.execute("SELECT first_seen, last_seen, article_count FROM events WHERE id=?", (body.target_event_id,)).fetchone()
        if not src or not tgt:
            raise HTTPException(404, "event_not_found")
        # Move articles
        conn.execute("""
            INSERT OR IGNORE INTO article_events (article_id, event_id)
            SELECT article_id, ? FROM article_events WHERE event_id=?
        """, (body.target_event_id, event_id))
        # Update target counts and dates
        conn.execute("""
            UPDATE events SET
                first_seen = CASE WHEN ? < first_seen THEN ? ELSE first_seen END,
                last_seen = CASE WHEN ? > last_seen THEN ? ELSE last_seen END,
                article_count = article_count + ?
            WHERE id=?
        """, (src[0], src[0], src[1], src[1], src[2], body.target_event_id))
        # Delete source event
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.execute("DELETE FROM article_events WHERE event_id=?", (event_id,))
        conn.commit()
    return {'ok': True, 'merged_into': body.target_event_id}

class SplitEvent(BaseModel):
    article_ids: list[int]
    new_event_title: Optional[str] = None

@router.post("/{event_id}/split")
def split_event(event_id: int, body: SplitEvent):
    """Split articles out of an event into a new event."""
    db = get_db()
    with db._conn() as conn:
        if len(body.article_ids) < 1:
            raise HTTPException(400, "need_at_least_one_article")
        event = conn.execute("SELECT title, first_seen, last_seen FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "event_not_found")
        new_title = body.new_event_title or f"{event[0]} (split)"
        today = event[1]
        # Create new event
        cur = conn.execute(
            "INSERT INTO events (title, first_seen, last_seen, article_count) VALUES (?, ?, ?, ?)",
            (new_title, today, today, len(body.article_ids))
        )
        new_id = cur.lastrowid
        # Move articles
        for aid in body.article_ids:
            conn.execute("UPDATE article_events SET event_id=? WHERE article_id=? AND event_id=?",
                        (new_id, aid, event_id))
        # Update old event article count
        remaining = conn.execute("SELECT COUNT(*) FROM article_events WHERE event_id=?", (event_id,)).fetchone()[0]
        conn.execute("UPDATE events SET article_count=? WHERE id=?", (remaining, event_id))
        if remaining == 0:
            conn.execute("UPDATE events SET status='inactive' WHERE id=?", (event_id,))
        conn.commit()
    return {'ok': True, 'new_event_id': new_id}
```

- [ ] **Step 2: Register router in main.py**

```python
from api.events import router as events_router
app.include_router(events_router)
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/api/events.py news-web/backend/main.py
git commit -m "feat: add events CRUD, merge, and split API"
```

---

### Task 6: Backend Logic Chains API

**Files:**
- Create: `news-web/backend/api/chains.py`

- [ ] **Step 1: Write chains.py**

```python
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/chains", tags=["chains"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def list_chains():
    db = get_db()
    with db._conn() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.description, c.created_at, c.updated_at, c.created_by,
                   (SELECT COUNT(*) FROM chain_events WHERE chain_id=c.id) as event_count
            FROM logic_chains c ORDER BY c.updated_at DESC
        """).fetchall()
    return {'chains': [
        {'id': r[0], 'title': r[1], 'description': r[2], 'created_at': r[3],
         'updated_at': r[4], 'created_by': r[5], 'event_count': r[6]}
        for r in rows
    ]}

class CreateChain(BaseModel):
    title: str
    description: str = ''
    event_ids: list[int] = []

@router.post("")
def create_chain(body: CreateChain):
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        cur = conn.execute(
            "INSERT INTO logic_chains (title, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (body.title, body.description, now, now)
        )
        chain_id = cur.lastrowid
        for pos, eid in enumerate(body.event_ids):
            conn.execute(
                "INSERT INTO chain_events (chain_id, event_id, position) VALUES (?, ?, ?)",
                (chain_id, eid, pos)
            )
        conn.commit()
    return {'id': chain_id, 'title': body.title}

@router.get("/{chain_id}")
def get_chain(chain_id: int):
    """Get chain with full event tree including sub-chains."""
    db = get_db()
    with db._conn() as conn:
        chain = conn.execute(
            "SELECT id, title, description, created_at, updated_at, created_by FROM logic_chains WHERE id=?",
            (chain_id,)
        ).fetchone()
        if not chain:
            raise HTTPException(404, "chain_not_found")

        # Get direct events
        events = conn.execute("""
            SELECT e.id, e.title, e.first_seen, e.last_seen, e.article_count, ce.position, ce.note
            FROM chain_events ce
            JOIN events e ON e.id = ce.event_id
            WHERE ce.chain_id=?
            ORDER BY ce.position
        """, (chain_id,)).fetchall()

        # Get sub-chains
        sub_chains = conn.execute("""
            SELECT lc.id, lc.title, cr.position
            FROM chain_relations cr
            JOIN logic_chains lc ON lc.id = cr.child_chain_id
            WHERE cr.parent_chain_id=?
            ORDER BY cr.position
        """, (chain_id,)).fetchall()

    return {
        'id': chain[0], 'title': chain[1], 'description': chain[2],
        'created_at': chain[3], 'updated_at': chain[4], 'created_by': chain[5],
        'events': [
            {'id': r[0], 'title': r[1], 'first_seen': r[2], 'last_seen': r[3],
             'article_count': r[4], 'position': r[5], 'note': r[6]}
            for r in events
        ],
        'sub_chains': [
            {'id': r[0], 'title': r[1], 'position': r[2]} for r in sub_chains
        ]
    }

class UpdateChain(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

@router.patch("/{chain_id}")
def update_chain(chain_id: int, body: UpdateChain):
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        updates = []
        params = []
        if body.title is not None:
            updates.append("title=?")
            params.append(body.title)
        if body.description is not None:
            updates.append("description=?")
            params.append(body.description)
        if updates:
            updates.append("updated_at=?")
            params.append(now)
            params.append(chain_id)
            conn.execute(f"UPDATE logic_chains SET {', '.join(updates)} WHERE id=?", params)
            conn.commit()
    return {'ok': True}

@router.delete("/{chain_id}")
def delete_chain(chain_id: int):
    db = get_db()
    with db._conn() as conn:
        conn.execute("DELETE FROM logic_chains WHERE id=?", (chain_id,))
        conn.commit()
    return {'ok': True}

class SpliceChains(BaseModel):
    child_chain_ids: list[int]

@router.post("/{chain_id}/splice")
def splice_chain(chain_id: int, body: SpliceChains):
    """Attach sub-chains to this parent chain."""
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        parent = conn.execute("SELECT id FROM logic_chains WHERE id=?", (chain_id,)).fetchone()
        if not parent:
            raise HTTPException(404, "parent_chain_not_found")
        for pos, child_id in enumerate(body.child_chain_ids):
            child = conn.execute("SELECT id FROM logic_chains WHERE id=?", (child_id,)).fetchone()
            if not child:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO chain_relations (parent_chain_id, child_chain_id, position)
                VALUES (?, ?, ?)
            """, (chain_id, child_id, pos))
        conn.execute("UPDATE logic_chains SET updated_at=? WHERE id=?", (now, chain_id))
        conn.commit()
    return {'ok': True}

class SplitChain(BaseModel):
    at_event_id: int
    new_title: str = ''

@router.post("/{chain_id}/split")
def split_chain(chain_id: int, body: SplitChain):
    """Split chain at a given event. Returns the new chain id."""
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        chain = conn.execute("SELECT title FROM logic_chains WHERE id=?", (chain_id,)).fetchone()
        if not chain:
            raise HTTPException(404, "chain_not_found")
        events = conn.execute(
            "SELECT id, event_id, position FROM chain_events WHERE chain_id=? ORDER BY position",
            (chain_id,)
        ).fetchall()

        split_pos = None
        for eid, evt_id, pos in events:
            if evt_id == body.at_event_id:
                split_pos = pos
                break
        if split_pos is None:
            raise HTTPException(400, "event_not_in_chain")

        new_title = body.new_title or f"{chain[0]} (续)"
        # Create new chain
        cur = conn.execute(
            "INSERT INTO logic_chains (title, description, created_at, updated_at) VALUES (?, '', ?, ?)",
            (new_title, now, now)
        )
        new_id = cur.lastrowid
        # Move split events
        for eid, evt_id, pos in events:
            if pos >= split_pos:
                conn.execute("UPDATE chain_events SET chain_id=?, position=position-? WHERE id=?",
                            (new_id, split_pos, eid))
        conn.execute("UPDATE logic_chains SET updated_at=? WHERE id=?", (now, chain_id))
        conn.commit()
    return {'ok': True, 'new_chain_id': new_id}

class ReorderChain(BaseModel):
    event_ids: list[int]

@router.post("/{chain_id}/reorder")
def reorder_chain(chain_id: int, body: ReorderChain):
    db = get_db()
    with db._conn() as conn:
        for pos, eid in enumerate(body.event_ids):
            conn.execute(
                "UPDATE chain_events SET position=? WHERE chain_id=? AND event_id=?",
                (pos, chain_id, eid)
            )
        conn.execute("UPDATE logic_chains SET updated_at=? WHERE id=?",
                    (datetime.now().isoformat(timespec='seconds'), chain_id))
        conn.commit()
    return {'ok': True}
```

- [ ] **Step 2: Register router in main.py**

```python
from api.chains import router as chains_router
app.include_router(chains_router)
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/api/chains.py news-web/backend/main.py
git commit -m "feat: add logic chains CRUD, splice, split, and reorder API"
```

---

### Task 7: Backend Event Relations API

**Files:**
- Create: `news-web/backend/api/relations.py`

- [ ] **Step 1: Write relations.py**

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/relations", tags=["relations"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("/suggested")
def get_suggested_relations():
    """Get AI-suggested event relations pending human review."""
    db = get_db()
    return {'suggestions': db.get_pending_relations()}

@router.post("/{relation_id}/confirm")
def confirm_relation(relation_id: int):
    db = get_db()
    ok = db.confirm_relation(relation_id)
    if not ok:
        raise HTTPException(404, "relation_not_found")
    return {'ok': True}

@router.delete("/{relation_id}")
def reject_relation(relation_id: int):
    db = get_db()
    ok = db.reject_relation(relation_id)
    if not ok:
        raise HTTPException(404, "relation_not_found")
    return {'ok': True}

class CreateRelation(BaseModel):
    from_event_id: int
    to_event_id: int
    relation: str  # before|after|update|spawn|related

@router.post("")
def create_relation(body: CreateRelation):
    db = get_db()
    if body.relation not in ('before', 'after', 'update', 'spawn', 'related'):
        raise HTTPException(400, "invalid_relation_type")
    ok = db.link_events(body.from_event_id, body.to_event_id, body.relation)
    if not ok:
        raise HTTPException(400, "failed_to_create_relation")
    return {'ok': True}
```

- [ ] **Step 2: Register router in main.py**

```python
from api.relations import router as relations_router
app.include_router(relations_router)
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/api/relations.py news-web/backend/main.py
git commit -m "feat: add event relations (confirm/reject/create) API"
```

---

### Task 8: Frontend Scaffold

**Files:**
- Create: `news-web/frontend/package.json`
- Create: `news-web/frontend/tsconfig.json`
- Create: `news-web/frontend/vite.config.ts`
- Create: `news-web/frontend/index.html`
- Create: `news-web/frontend/src/main.tsx`
- Create: `news-web/frontend/src/index.css`

- [ ] **Step 1: Scaffold Vite project**

Run:
```bash
cd news-web
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-router-dom@6 @xyflow/react
```

- [ ] **Step 2: Write vite.config.ts** (overwrite scaffolded file)

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8080'
    }
  }
})
```

- [ ] **Step 3: Write index.html** (overwrite scaffolded)

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>新闻知识聚合中心</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Write src/main.tsx**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
```

- [ ] **Step 5: Write basic index.css**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg-primary: #0f0f1a;
  --bg-secondary: #1a1a2e;
  --bg-card: #2a2a3e;
  --text-primary: #e0e0e0;
  --text-secondary: #888;
  --accent: #4fc3f7;
  --accent-green: #81c784;
  --accent-orange: #ffb74d;
  --accent-red: #e57373;
  --accent-purple: #ce93d8;
  --border: #2a2a3e;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
}
a { color: var(--accent); text-decoration: none; }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: #444; border-radius: 3px; }
```

- [ ] **Step 6: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds, output in `dist/`

- [ ] **Step 7: Commit**

```bash
git add news-web/frontend/
git commit -m "feat: scaffold React frontend with Vite, router, and xyflow"
```

---

### Task 9: Frontend Types + API Client

**Files:**
- Create: `news-web/frontend/src/types/index.ts`
- Create: `news-web/frontend/src/api/client.ts`

- [ ] **Step 1: Write types/index.ts**

```typescript
export interface Article {
  id: number;
  title: string;
  source: string;
  url: string;
  published: string;
  fetched: string;
  score: number;
  label: string;
  verified: number;
  keywords: string[];
  human_tags: string[];
  category?: string;
  event?: { id: number; title: string } | null;
}

export interface Event {
  id: number;
  title: string;
  first_seen: string;
  last_seen: string;
  article_count: number;
  status: string;
}

export interface EventDetail extends Event {
  articles: Article[];
  relations: {
    outgoing: Relation[];
    incoming: Relation[];
  };
}

export interface Relation {
  id: number;
  target_id?: number;
  source_id?: number;
  relation: string;
  target_title?: string;
  source_title?: string;
  target_first?: string;
  target_last?: string;
}

export interface LogicChain {
  id: number;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
  created_by: string;
  event_count?: number;
}

export interface ChainDetail extends LogicChain {
  events: ChainEvent[];
  sub_chains: { id: number; title: string; position: number }[];
}

export interface ChainEvent {
  id: number;
  title: string;
  first_seen: string;
  last_seen: string;
  article_count: number;
  position: number;
  note: string;
}

export interface Stats {
  articles: number;
  events: number;
  active_events: number;
  human_verified: number;
  by_category: Record<string, number>;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  limit: number;
  articles?: T[];
  events?: T[];
}
```

- [ ] **Step 2: Write api/client.ts**

```typescript
import type { Article, Event, EventDetail, LogicChain, ChainDetail, Stats, PaginatedResponse } from '../types';

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => fetchJSON<{ status: string }>('/health'),

  getStats: () => fetchJSON<Stats>('/stats'),

  searchArticles: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, String(v)); });
    return fetchJSON<PaginatedResponse<Article>>(`/articles?${qs}`);
  },

  getArticle: (id: number) => fetchJSON<Article>(`/articles/${id}`),

  updateArticle: (id: number, data: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>(`/articles/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  getArticleContent: async (id: number) => {
    const res = await fetch(`${BASE}/articles/${id}/content`);
    return res.text();
  },

  listEvents: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, String(v)); });
    return fetchJSON<PaginatedResponse<Event>>(`/events?${qs}`);
  },

  getEvent: (id: number) => fetchJSON<EventDetail>(`/events/${id}`),

  updateEvent: (id: number, data: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>(`/events/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  mergeEvents: (id: number, targetId: number) =>
    fetchJSON<{ ok: boolean }>(`/events/${id}/merge`, { method: 'POST', body: JSON.stringify({ target_event_id: targetId }) }),

  splitEvent: (id: number, articleIds: number[], newTitle?: string) =>
    fetchJSON<{ ok: boolean; new_event_id: number }>(`/events/${id}/split`, {
      method: 'POST', body: JSON.stringify({ article_ids: articleIds, new_event_title: newTitle })
    }),

  listChains: () => fetchJSON<{ chains: LogicChain[] }>('/chains'),

  getChain: (id: number) => fetchJSON<ChainDetail>(`/chains/${id}`),

  createChain: (data: { title: string; description?: string; event_ids?: number[] }) =>
    fetchJSON<{ id: number; title: string }>('/chains', { method: 'POST', body: JSON.stringify(data) }),

  updateChain: (id: number, data: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteChain: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}`, { method: 'DELETE' }),

  spliceChains: (id: number, childIds: number[]) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}/splice`, { method: 'POST', body: JSON.stringify({ child_chain_ids: childIds }) }),

  splitChain: (id: number, atEventId: number, newTitle?: string) =>
    fetchJSON<{ ok: boolean; new_chain_id: number }>(`/chains/${id}/split`, {
      method: 'POST', body: JSON.stringify({ at_event_id: atEventId, new_title: newTitle || '' })
    }),

  reorderChain: (id: number, eventIds: number[]) =>
    fetchJSON<{ ok: boolean }>(`/chains/${id}/reorder`, { method: 'POST', body: JSON.stringify({ event_ids: eventIds }) }),

  getSuggestedRelations: () => fetchJSON<{ suggestions: unknown[] }>('/relations/suggested'),

  confirmRelation: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/relations/${id}/confirm`, { method: 'POST' }),

  rejectRelation: (id: number) =>
    fetchJSON<{ ok: boolean }>(`/relations/${id}`, { method: 'DELETE' }),

  createRelation: (from: number, to: number, relation: string) =>
    fetchJSON<{ ok: boolean }>('/relations', { method: 'POST', body: JSON.stringify({ from_event_id: from, to_event_id: to, relation }) }),

  getSettings: () => fetchJSON<{ db_path: string; user_agent: string }>('/settings'),

  updateSettings: (data: Record<string, string>) =>
    fetchJSON<{ db_path: string; user_agent: string }>('/settings', { method: 'PUT', body: JSON.stringify(data) }),
};
```

- [ ] **Step 3: Commit**

```bash
git add news-web/frontend/src/types/ news-web/frontend/src/api/
git commit -m "feat: add TypeScript types and API client"
```

---

### Task 10: Frontend Layout + Navigation

**Files:**
- Create: `news-web/frontend/src/components/NavSidebar.tsx`
- Modify: `news-web/frontend/src/App.tsx`

- [ ] **Step 1: Write NavSidebar.tsx**

```tsx
import { NavLink } from 'react-router-dom';

const NAV_ITEMS = [
  { path: '/', label: '仪表盘', icon: '📊' },
  { path: '/workspace', label: '逻辑链工作台', icon: '🖱' },
  { path: '/articles', label: '文章检索', icon: '📄' },
  { path: '/chains', label: '逻辑链列表', icon: '📋' },
  { path: '/settings', label: '设置', icon: '⚙' },
];

export default function NavSidebar() {
  return (
    <nav style={{
      width: 200, height: '100vh', background: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', padding: '12px 0'
    }}>
      <div style={{ padding: '12px 16px', fontSize: 16, fontWeight: 'bold', color: 'var(--accent)', marginBottom: 8 }}>
        新闻知识聚合
      </div>
      {NAV_ITEMS.map(item => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.path === '/'}
          style={({ isActive }) => ({
            display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px',
            fontSize: 14, color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
            background: isActive ? 'rgba(79,195,247,0.1)' : 'transparent',
            borderLeft: isActive ? '3px solid var(--accent)' : '3px solid transparent',
            textDecoration: 'none',
          })}
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
```

- [ ] **Step 2: Write App.tsx**

```tsx
import { Routes, Route } from 'react-router-dom';
import NavSidebar from './components/NavSidebar';
import Dashboard from './pages/Dashboard';
import Workspace from './pages/Workspace';
import ArticleSearch from './pages/ArticleSearch';
import ChainList from './pages/ChainList';
import Settings from './pages/Settings';

export default function App() {
  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <NavSidebar />
      <main style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/articles" element={<ArticleSearch />} />
          <Route path="/chains" element={<ChainList />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Verify routing**

Run: `cd frontend && npm run dev`
Expected: App renders at localhost:3000 with sidebar and 5 route placeholders

- [ ] **Step 4: Commit**

```bash
git add news-web/frontend/src/App.tsx news-web/frontend/src/components/NavSidebar.tsx
git commit -m "feat: add app layout with sidebar navigation"
```

---

### Task 11: Frontend Dashboard

**Files:**
- Create: `news-web/frontend/src/components/DashboardCards.tsx`
- Create: `news-web/frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write DashboardCards.tsx**

```tsx
import type { Stats } from '../types';

interface Props {
  stats: Stats | null;
  loading: boolean;
}

const CARD_STYLE: React.CSSProperties = {
  background: 'var(--bg-secondary)', padding: 20, borderRadius: 10, textAlign: 'center',
};

export default function DashboardCards({ stats, loading }: Props) {
  if (loading) return <div style={{ color: 'var(--text-secondary)' }}>加载中...</div>;
  if (!stats) return <div style={{ color: 'var(--accent-red)' }}>数据库未配置</div>;

  const cards = [
    { label: '总文章数', value: stats.articles, color: 'var(--accent)' },
    { label: '活跃事件', value: stats.active_events, color: 'var(--accent-green)' },
    { label: '待审核', value: stats.articles - stats.human_verified, color: 'var(--accent-orange)' },
    { label: '已审核', value: stats.human_verified, color: 'var(--accent-purple)' },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16 }}>
      {cards.map(c => (
        <div key={c.label} style={CARD_STYLE}>
          <div style={{ fontSize: 32, fontWeight: 'bold', color: c.color }}>{c.value}</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Write Dashboard.tsx**

```tsx
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Stats } from '../types';
import DashboardCards from '../components/DashboardCards';

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>📊 仪表盘</h2>
      <DashboardCards stats={stats} loading={loading} />

      {stats && (
        <div style={{ marginTop: 24, background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
          <h3 style={{ fontSize: 15, marginBottom: 12 }}>来源分布</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {Object.entries(stats.by_category).map(([cat, count]) => (
              <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <span style={{ width: 100, color: 'var(--text-secondary)' }}>{cat}</span>
                <div style={{ flex: 1, background: 'var(--bg-card)', borderRadius: 4, height: 16, overflow: 'hidden' }}>
                  <div style={{
                    width: `${(count / stats.articles) * 100}%`, height: '100%',
                    background: 'var(--accent)', borderRadius: 4, minWidth: 4
                  }} />
                </div>
                <span style={{ width: 40, textAlign: 'right' }}>{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add news-web/frontend/src/pages/Dashboard.tsx news-web/frontend/src/components/DashboardCards.tsx
git commit -m "feat: add dashboard page with stats cards and category distribution"
```

---

### Task 12: Frontend Article Search

**Files:**
- Create: `news-web/frontend/src/pages/ArticleSearch.tsx`

- [ ] **Step 1: Write ArticleSearch.tsx**

```tsx
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Article } from '../types';

const INPUT_STYLE: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '8px 12px', color: 'var(--text-primary)', fontSize: 13, outline: 'none',
};

export default function ArticleSearch() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState({ q: '', source: '', date_from: '', date_to: '', priority: '', verified: '' });
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Article | null>(null);

  const search = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const res = await api.searchArticles({ ...query, page: p, limit: 50 });
      setArticles(res.articles || []);
      setTotal(res.total);
      setPage(p);
    } catch { setArticles([]); }
    setLoading(false);
  }, [query]);

  useEffect(() => { search(1) }, [search]);

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>📄 文章检索</h2>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        <input placeholder="关键词" value={query.q} onChange={e => setQuery(q => ({ ...q, q: e.target.value }))} style={{ ...INPUT_STYLE, flex: 1, minWidth: 200 }} />
        <input placeholder="来源" value={query.source} onChange={e => setQuery(q => ({ ...q, source: e.target.value }))} style={{ ...INPUT_STYLE, width: 120 }} />
        <input type="date" value={query.date_from} onChange={e => setQuery(q => ({ ...q, date_from: e.target.value }))} style={INPUT_STYLE} />
        <input type="date" value={query.date_to} onChange={e => setQuery(q => ({ ...q, date_to: e.target.value }))} style={INPUT_STYLE} />
        <select value={query.priority} onChange={e => setQuery(q => ({ ...q, priority: e.target.value }))} style={INPUT_STYLE}>
          <option value="">全部优先级</option>
          <option value="high">高</option><option value="medium">中</option><option value="low">低</option>
        </select>
        <select value={query.verified} onChange={e => setQuery(q => ({ ...q, verified: e.target.value }))} style={INPUT_STYLE}>
          <option value="">全部状态</option>
          <option value="no">待审核</option><option value="yes">已审核</option>
        </select>
        <button onClick={() => search(1)} style={{ background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '8px 16px', color: '#000', fontWeight: 'bold', cursor: 'pointer' }}>搜索</button>
      </div>

      {/* Table */}
      <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px 80px 70px 70px', gap: 8, padding: '10px 16px', fontSize: 12, color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)', fontWeight: 'bold' }}>
          <span>标题</span><span>来源</span><span>评分</span><span>状态</span><span>日期</span>
        </div>
        {articles.map(a => (
          <div key={a.id}
            onClick={() => setSelected(a)}
            style={{ display: 'grid', gridTemplateColumns: '1fr 100px 80px 70px 70px', gap: 8, padding: '10px 16px', fontSize: 13, cursor: 'pointer', borderBottom: '1px solid var(--border)', background: selected?.id === a.id ? 'rgba(79,195,247,0.1)' : 'transparent' }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</span>
            <span style={{ color: 'var(--accent)' }}>{a.source}</span>
            <span style={{ color: a.score > 0.7 ? 'var(--accent-green)' : a.score > 0.4 ? 'var(--accent-orange)' : 'var(--text-secondary)' }}>{a.score.toFixed(2)}</span>
            <span style={{ color: a.verified ? 'var(--accent-green)' : 'var(--accent-orange)' }}>{a.verified ? '已审' : '待审'}</span>
            <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{a.fetched?.slice(5, 10)}</span>
          </div>
        ))}
        {!articles.length && <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-secondary)' }}>{loading ? '搜索中...' : '无结果'}</div>}
      </div>

      {total > 50 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 16 }}>
          <button disabled={page <= 1} onClick={() => search(page - 1)} style={paginationBtn}>上一页</button>
          <span style={{ padding: '6px 12px', fontSize: 13, color: 'var(--text-secondary)' }}>{page} / {Math.ceil(total / 50)}</span>
          <button disabled={page >= Math.ceil(total / 50)} onClick={() => search(page + 1)} style={paginationBtn}>下一页</button>
        </div>
      )}

      {/* Detail Panel */}
      {selected && (
        <div style={{ marginTop: 16, background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
          <h3 style={{ fontSize: 15, marginBottom: 8 }}>{selected.title}</h3>
          <div style={{ display: 'flex', gap: 16, fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
            <span>来源: {selected.source}</span>
            <span>评分: {selected.score.toFixed(2)}</span>
            <span>状态: {selected.verified ? '已审核' : '待审核'}</span>
          </div>
          {selected.keywords?.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
              {selected.keywords.map(k => <span key={k} style={{ background: 'var(--bg-card)', padding: '2px 8px', borderRadius: 4, fontSize: 11 }}>{k}</span>)}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <a href={selected.url} target="_blank" rel="noopener noreferrer" style={{ background: 'var(--accent)', padding: '6px 14px', borderRadius: 6, fontSize: 12, color: '#000', textDecoration: 'none' }}>打开原文</a>
            {selected.event && (
              <a href={`/workspace?event=${selected.event.id}`} style={{ background: 'var(--bg-card)', padding: '6px 14px', borderRadius: 6, fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>查看所属事件 →</a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const paginationBtn: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
  padding: '6px 14px', color: 'var(--text-primary)', fontSize: 13, cursor: 'pointer',
};
```

- [ ] **Step 2: Commit**

```bash
git add news-web/frontend/src/pages/ArticleSearch.tsx
git commit -m "feat: add article search page with multi-dimensional filters"
```

---

### Task 13: Frontend Chain Canvas — Workspace Core

**Files:**
- Create: `news-web/frontend/src/components/SearchPanel.tsx`
- Create: `news-web/frontend/src/components/ArticleBlock.tsx`
- Create: `news-web/frontend/src/components/EventCard.tsx`
- Create: `news-web/frontend/src/components/RelationDialog.tsx`
- Create: `news-web/frontend/src/components/ChainCanvas.tsx`

This is the largest task — the core React Flow canvas that renders event containers as nodes, with drag-and-drop from the search panel.

- [ ] **Step 1: Write ArticleBlock.tsx**

```tsx
import { useDrag } from '@xyflow/react';
import type { Article } from '../types';

interface Props {
  article: Article;
}

export default function ArticleBlock({ article }: Props) {
  const { isDragging } = useDrag({
    id: `article-${article.id}`,
    data: { type: 'article', article },
  });

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('application/json', JSON.stringify({ type: 'article', article }));
      }}
      style={{
        background: 'var(--bg-card)', padding: '6px 10px', borderRadius: 6, fontSize: 12,
        cursor: 'grab', opacity: isDragging ? 0.5 : 1, borderLeft: '3px solid var(--accent)',
        marginBottom: 4,
      }}
    >
      <div style={{ fontWeight: 'bold', fontSize: 12, marginBottom: 2 }}>{article.title.slice(0, 60)}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: 10 }}>
        <span>{article.source}</span>
        <span>{article.fetched?.slice(5, 10)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write SearchPanel.tsx**

```tsx
import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import type { Article } from '../types';
import ArticleBlock from './ArticleBlock';

interface Props {
  onSearchResults: (articles: Article[]) => void;
}

export default function SearchPanel({ onSearchResults }: Props) {
  const [query, setQuery] = useState('');
  const [datePreset, setDatePreset] = useState('today');
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const search = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { limit: 30 };
      if (query) params.q = query;
      if (datePreset === 'today') params.date_from = new Date().toISOString().slice(0, 10);
      else if (datePreset === '3days') {
        const d = new Date(); d.setDate(d.getDate() - 3);
        params.date_from = d.toISOString().slice(0, 10);
      } else if (datePreset === '7days') {
        const d = new Date(); d.setDate(d.getDate() - 7);
        params.date_from = d.toISOString().slice(0, 10);
      }
      const res = await api.searchArticles(params);
      setArticles(res.articles || []);
      onSearchResults(res.articles || []);
    } catch { setArticles([]); }
    setLoading(false);
  }, [query, datePreset, onSearchResults]);

  useEffect(() => { search() }, [search]);

  if (collapsed) {
    return (
      <div style={{ width: 40, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
        onClick={() => setCollapsed(false)}>
        <span style={{ fontSize: 20, transform: 'rotate(180deg)' }}>▶</span>
      </div>
    );
  }

  return (
    <div style={{ width: 280, background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: 12, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 'bold' }}>🔍 搜索</span>
        <span style={{ cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)' }} onClick={() => setCollapsed(true)}>◀ 收起</span>
      </div>

      <div style={{ padding: '8px 12px' }}>
        <input placeholder="搜索新闻..." value={query} onChange={e => setQuery(e.target.value)}
          style={{ width: '100%', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'var(--text-primary)', fontSize: 12, outline: 'none' }} />
        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
          {['today', '3days', '7days'].map(p => (
            <button key={p} onClick={() => setDatePreset(p)}
              style={{ flex: 1, padding: '4px 0', borderRadius: 4, border: 'none', fontSize: 11, cursor: 'pointer',
                background: datePreset === p ? 'var(--accent)' : 'var(--bg-card)', color: datePreset === p ? '#000' : 'var(--text-secondary)' }}>
              {p === 'today' ? '今天' : p === '3days' ? '3天' : '7天'}
            </button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 12px' }}>
        {loading && <div style={{ color: 'var(--text-secondary)', fontSize: 12, textAlign: 'center', padding: 20 }}>搜索中...</div>}
        {!loading && articles.length === 0 && <div style={{ color: 'var(--text-secondary)', fontSize: 12, textAlign: 'center', padding: 20 }}>无结果</div>}
        {!loading && articles.map(a => <ArticleBlock key={a.id} article={a} />)}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write EventCard.tsx**

This is the React Flow custom node that displays an event container with its articles.

```tsx
import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import type { Article } from '../types';

interface EventNodeData {
  eventId: number;
  title: string;
  priority: string;
  articles: Article[];
}

function EventCard({ data }: NodeProps<EventNodeData>) {
  const priorityColor = data.priority === 'high' ? 'var(--accent-green)' :
    data.priority === 'medium' ? 'var(--accent-orange)' : 'var(--accent-purple)';

  return (
    <div style={{
      background: 'var(--bg-secondary)', border: `1px solid ${priorityColor}`, borderRadius: 10,
      padding: 12, minWidth: 280, maxWidth: 360, fontSize: 12, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
    }}>
      <Handle type="target" position={Position.Left} style={{ background: priorityColor, width: 8, height: 8 }} />
      <div style={{ fontWeight: 'bold', fontSize: 13, marginBottom: 2, color: priorityColor }}>📦 {data.title}</div>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginBottom: 8 }}>
        {data.articles.length} 篇文章 · {data.priority === 'high' ? '高' : data.priority === 'medium' ? '中' : '低'}优先级
      </div>
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 6 }}>
        {data.articles.slice(0, 5).map(a => (
          <div key={a.id} style={{ padding: '3px 0', fontSize: 11, color: 'var(--text-primary)', display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{a.title}</span>
            <span style={{ color: 'var(--accent)', fontSize: 10, marginLeft: 8 }}>{a.source}</span>
          </div>
        ))}
        {data.articles.length > 5 && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 4 }}>+{data.articles.length - 5} 篇</div>}
      </div>
      <Handle type="source" position={Position.Right} style={{ background: priorityColor, width: 8, height: 8 }} />
    </div>
  );
}

export default memo(EventCard);
```

- [ ] **Step 4: Write RelationDialog.tsx**

```tsx
interface Props {
  open: boolean;
  onClose: () => void;
  onSelect: (relation: string) => void;
}

const RELATIONS = [
  { value: 'before', label: '之前发生', desc: '此事件在目标事件之前' },
  { value: 'after', label: '之后发生', desc: '此事件在目标事件之后' },
  { value: 'update', label: '更新', desc: '同一事件的新信息' },
  { value: 'spawn', label: '衍生', desc: '此事件导致另一事件' },
  { value: 'related', label: '相关', desc: '非时间性关联' },
];

export default function RelationDialog({ open, onClose, onSelect }: Props) {
  if (!open) return null;
  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
      onClick={onClose}>
      <div style={{ background: 'var(--bg-secondary)', borderRadius: 12, padding: 20, minWidth: 280 }} onClick={e => e.stopPropagation()}>
        <h3 style={{ fontSize: 14, marginBottom: 12 }}>选择关系类型</h3>
        {RELATIONS.map(r => (
          <div key={r.value} onClick={() => onSelect(r.value)}
            style={{ padding: '8px 12px', borderRadius: 6, cursor: 'pointer', marginBottom: 4, background: 'var(--bg-card)' }}>
            <div style={{ fontWeight: 'bold', fontSize: 12 }}>{r.label}</div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{r.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Write ChainCanvas.tsx**

```tsx
import { useCallback, useRef, useState } from 'react';
import {
  ReactFlow, addEdge, useNodesState, useEdgesState, Controls, Background,
  type Connection, type Edge, type Node, type DragEvent,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import EventCard from './EventCard';
import RelationDialog from './RelationDialog';
import { api } from '../api/client';
import type { Article } from '../types';

const nodeTypes = { eventCard: EventCard };

interface Props {
  articles: Article[];
}

export default function ChainCanvas({ articles }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [relationDialog, setRelationDialog] = useState<{ from: string; to: string } | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  // Group dropped articles by event for node creation
  const groupByEvent = useCallback((articles: Article[]) => {
    const map = new Map<string, { eventName: string; articles: Article[] }>();
    articles.forEach(a => {
      const key = a.event?.title || '未分类';
      if (!map.has(key)) map.set(key, { eventName: key, articles: [] });
      map.get(key)!.articles.push(a);
    });
    return Array.from(map.values());
  }, []);

  const onDrop = useCallback((event: DragEvent) => {
    event.preventDefault();
    const json = event.dataTransfer.getData('application/json');
    if (!json) return;
    const data = JSON.parse(json);
    if (data.type !== 'article') return;

    const article: Article = data.article;
    const eventName = article.event?.title || '未分类';

    // Check if node for this event already exists
    const existing = nodes.find(n => n.data?.eventId === article.event?.id);
    if (existing) {
      // Append article to existing node
      setNodes(nds => nds.map(n => {
        if (n.id === existing.id) {
          const arts = [...(n.data?.articles || []), article];
          // Deduplicate by id
          const deduped = arts.filter((a, i, arr) => arr.findIndex(x => x.id === a.id) === i);
          return { ...n, data: { ...n.data, articles: deduped } };
        }
        return n;
      }));
      return;
    }

    // Create new event node
    const position = reactFlowWrapper.current
      ? { x: event.clientX - 150, y: event.clientY - 50 }
      : { x: Math.random() * 300, y: Math.random() * 300 };

    const newNode: Node = {
      id: `event-${Date.now()}`,
      type: 'eventCard',
      position,
      data: {
        eventId: article.event?.id || 0,
        title: eventName,
        priority: article.label || 'medium',
        articles: [article],
      },
    };
    setNodes(nds => [...nds, newNode]);
  }, [nodes, setNodes]);

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    if (connection.source && connection.target) {
      setRelationDialog({ from: connection.source.toString(), to: connection.target.toString() });
    }
  }, []);

  const handleRelationSelect = useCallback(async (relation: string) => {
    if (!relationDialog) return;
    setEdges(eds => addEdge({
      source: relationDialog.from,
      target: relationDialog.to,
      label: relation,
      style: { stroke: '#4fc3f7', strokeWidth: 2 },
      labelStyle: { fill: '#4fc3f7', fontSize: 10 },
      animated: true,
    }, eds));
    setRelationDialog(null);
  }, [relationDialog, setEdges]);

  const handleCreateChain = useCallback(async () => {
    const title = prompt('请输入逻辑链标题:', '新建逻辑链');
    if (!title) return;
    const eventIds = nodes
      .map(n => n.data?.eventId)
      .filter((id): id is number => id != null && id > 0);
    try {
      await api.createChain({ title, event_ids: eventIds });
      alert('逻辑链创建成功');
    } catch (e) {
      alert('创建失败: ' + (e as Error).message);
    }
  }, [nodes]);

  return (
    <div ref={reactFlowWrapper} style={{ flex: 1, position: 'relative' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        nodeTypes={nodeTypes}
        fitView
        style={{ background: 'var(--bg-primary)' }}
      >
        <Controls />
        <Background color="#2a2a3e" gap={20} />
      </ReactFlow>

      {/* Create chain button */}
      {nodes.length > 0 && (
        <button onClick={handleCreateChain}
          style={{ position: 'absolute', top: 12, right: 12, background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '8px 16px', color: '#000', fontWeight: 'bold', fontSize: 13, cursor: 'pointer', zIndex: 10 }}>
          ➕ 创建逻辑链
        </button>
      )}

      <RelationDialog open={!!relationDialog} onClose={() => setRelationDialog(null)} onSelect={handleRelationSelect} />
    </div>
  );
}
```

- [ ] **Step 6: Write Workspace.tsx**

```tsx
import { useCallback, useState } from 'react';
import SearchPanel from '../components/SearchPanel';
import ChainCanvas from '../components/ChainCanvas';
import type { Article } from '../types';

export default function Workspace() {
  const [canvasArticles, setCanvasArticles] = useState<Article[]>([]);

  const handleSearchResults = useCallback((articles: Article[]) => {
    // Keep articles in state for canvas context; canvas handles drops separately
  }, []);

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 48px)', margin: -24 }}>
      <SearchPanel onSearchResults={handleSearchResults} />
      <ChainCanvas articles={canvasArticles} />
    </div>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add news-web/frontend/src/components/ArticleBlock.tsx news-web/frontend/src/components/SearchPanel.tsx news-web/frontend/src/components/EventCard.tsx news-web/frontend/src/components/RelationDialog.tsx news-web/frontend/src/components/ChainCanvas.tsx news-web/frontend/src/pages/Workspace.tsx
git commit -m "feat: add workspace page with drag-and-drop chain canvas"
```

---

### Task 14: Frontend Chain List + Settings

**Files:**
- Create: `news-web/frontend/src/pages/ChainList.tsx`
- Create: `news-web/frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Write ChainList.tsx**

```tsx
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { LogicChain } from '../types';

export default function ChainList() {
  const [chains, setChains] = useState<LogicChain[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.listChains().then(res => setChains(res.chains)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const handleDelete = async (id: number, title: string) => {
    if (!confirm(`删除「${title}」？`)) return;
    await api.deleteChain(id);
    setChains(chains => chains.filter(c => c.id !== id));
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>📋 逻辑链列表</h2>
        <button onClick={() => navigate('/workspace')}
          style={{ background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '8px 16px', color: '#000', fontWeight: 'bold', fontSize: 13, cursor: 'pointer' }}>
          ＋ 新建
        </button>
      </div>

      {loading && <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>加载中...</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {chains.map(chain => (
          <div key={chain.id} style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
              <div>
                <div style={{ fontWeight: 'bold', fontSize: 14, marginBottom: 4 }}>{chain.title}</div>
                {chain.description && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>{chain.description}</div>}
                <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--text-secondary)' }}>
                  <span>{chain.event_count} 个事件</span>
                  <span>创建于 {chain.created_at?.slice(0, 10)}</span>
                  <span>{chain.created_by === 'auto' ? 'AI 生成' : '人工创建'}</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={() => navigate(`/workspace?chain=${chain.id}`)}
                  style={{ background: 'var(--bg-card)', border: 'none', borderRadius: 4, padding: '6px 12px', color: 'var(--accent)', fontSize: 11, cursor: 'pointer' }}>编辑</button>
                <button onClick={() => handleDelete(chain.id, chain.title)}
                  style={{ background: 'var(--bg-card)', border: 'none', borderRadius: 4, padding: '6px 12px', color: 'var(--accent-red)', fontSize: 11, cursor: 'pointer' }}>删除</button>
              </div>
            </div>
          </div>
        ))}
        {!loading && chains.length === 0 && <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>暂无逻辑链</div>}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write Settings.tsx**

```tsx
import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function Settings() {
  const [dbPath, setDbPath] = useState('');
  const [userAgent, setUserAgent] = useState('');
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState('');
  const [openaiApiKey, setOpenaiApiKey] = useState('');
  const [openaiModel, setOpenaiModel] = useState('');
  const [pipelineEnabled, setPipelineEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    api.getSettings().then(s => {
      setDbPath(s.db_path);
      setUserAgent(s.user_agent);
      setOpenaiBaseUrl(s.openai_base_url || 'https://api.openai.com/v1');
      setOpenaiModel(s.openai_model || 'gpt-4o-mini');
      setPipelineEnabled(s.pipeline_schedule_enabled !== false);
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      await api.updateSettings({
        db_path: dbPath,
        user_agent: userAgent,
        openai_base_url: openaiBaseUrl,
        openai_api_key: openaiApiKey,
        openai_model: openaiModel,
        pipeline_schedule_enabled: pipelineEnabled,
      });
      setMessage('已保存');
    } catch (e) {
      setMessage('保存失败: ' + (e as Error).message);
    }
    setSaving(false);
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6,
    padding: '8px 12px', color: 'var(--text-primary)', fontSize: 13, outline: 'none', marginTop: 4,
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, color: 'var(--text-secondary)', marginTop: 16, display: 'block' };

  return (
    <div style={{ maxWidth: 600 }}>
      <h2 style={{ marginBottom: 20 }}>⚙ 设置</h2>

      <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: 20 }}>
        <h3 style={{ fontSize: 14, marginBottom: 8, color: 'var(--accent)' }}>数据库</h3>
        <label style={labelStyle}>
          📁 数据库路径
          <input value={dbPath} onChange={e => setDbPath(e.target.value)} placeholder="/path/to/news.db" style={inputStyle} />
        </label>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 4 }}>支持本地路径或 NAS 共享挂载点</div>

        <h3 style={{ fontSize: 14, marginTop: 20, marginBottom: 8, color: 'var(--accent)' }}>AI 配置（OpenAI 兼容）</h3>
        <label style={labelStyle}>
          🔗 API 地址
          <input value={openaiBaseUrl} onChange={e => setOpenaiBaseUrl(e.target.value)} style={inputStyle} />
        </label>
        <label style={labelStyle}>
          🔑 API Key
          <input value={openaiApiKey} onChange={e => setOpenaiApiKey(e.target.value)} type="password" style={inputStyle} />
        </label>
        <label style={labelStyle}>
          🤖 模型
          <input value={openaiModel} onChange={e => setOpenaiModel(e.target.value)} style={inputStyle} />
        </label>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 4 }}>支持 OpenAI、DeepSeek、Ollama 等兼容端点</div>

        <h3 style={{ fontSize: 14, marginTop: 20, marginBottom: 8, color: 'var(--accent)' }}>抓取调度</h3>
        <label style={{ ...labelStyle, flexDirection: 'row', display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={pipelineEnabled} onChange={e => setPipelineEnabled(e.target.checked)}
            style={{ width: 16, height: 16 }} />
          <span>启用定时抓取（每天 10:00 / 17:00）</span>
        </label>

        <h3 style={{ fontSize: 14, marginTop: 20, marginBottom: 8, color: 'var(--accent)' }}>网络</h3>
        <label style={labelStyle}>
          🌐 User-Agent
          <input value={userAgent} onChange={e => setUserAgent(e.target.value)} style={inputStyle} />
        </label>

        <button onClick={handleSave} disabled={saving}
          style={{ marginTop: 20, background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '10px 24px', color: '#000', fontWeight: 'bold', fontSize: 14, cursor: 'pointer' }}>
          {saving ? '保存中...' : '保存设置'}
        </button>

        {message && <div style={{ marginTop: 12, fontSize: 13, color: 'var(--accent-green)' }}>{message}</div>}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add news-web/frontend/src/pages/ChainList.tsx news-web/frontend/src/pages/Settings.tsx
git commit -m "feat: add chain list and settings pages"
```

---

### Task 15: Backend Integration Tests

**Files:**
- Create: `news-web/tests/backend/conftest.py`
- Create: `news-web/tests/backend/test_api.py`

- [ ] **Step 1: Write conftest.py**

```python
import os, sys, pytest, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

from db.news_db import NewsDB
from db.migrations import ensure_schema

@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / 'test.db')

@pytest.fixture
def news_db(test_db_path):
    db = NewsDB(test_db_path)
    # Enable WAL
    with db._conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(test_db_path)
    # Seed test data
    db.save_articles('rss_news', [
        {'title': 'Intel Nova Lake leak', 'source': 'Guru3D', 'url': 'https://test.com/1', 'metadata': {}},
        {'title': 'Intel Nova Lake CPU details', 'source': 'Wccftech', 'url': 'https://test.com/2', 'metadata': {}},
        {'title': 'AMD RDNA 4 architecture', 'source': 'TechPowerUp', 'url': 'https://test.com/3', 'metadata': {}},
    ])
    db.link_articles_to_events()
    yield db
```

- [ ] **Step 2: Write test_api.py**

```python
import pytest, json
from fastapi.testclient import TestClient
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

from main import app
from config import config

@pytest.fixture
def client(test_db_path):
    config.db_path = test_db_path
    return TestClient(app)

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_stats(client, news_db):
    resp = client.get("/api/stats")
    data = resp.json()
    assert data["articles"] >= 3
    assert data["events"] >= 2
    assert "rss_news" in data["by_category"]

def test_list_articles(client, news_db):
    resp = client.get("/api/articles")
    data = resp.json()
    assert len(data["articles"]) >= 3
    assert data["total"] >= 3

def test_search_articles(client, news_db):
    resp = client.get("/api/articles?q=Nova")
    data = resp.json()
    assert len(data["articles"]) >= 2

def test_get_article(client, news_db):
    resp = client.get("/api/articles/1")
    assert resp.status_code == 200
    assert resp.json()["id"] == 1

def test_update_article(client, news_db):
    resp = client.patch("/api/articles/1", json={"priority_label": "high"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

def test_list_events(client, news_db):
    resp = client.get("/api/events")
    data = resp.json()
    assert len(data["events"]) >= 2

def test_get_event(client, news_db):
    resp = client.get("/api/events/1")
    assert resp.status_code == 200
    assert "articles" in resp.json()

def test_create_chain(client, news_db):
    resp = client.post("/api/chains", json={"title": "Test Chain", "event_ids": [1, 2]})
    assert resp.status_code == 200
    assert resp.json()["id"] > 0

def test_list_chains(client, news_db):
    client.post("/api/chains", json={"title": "Chain 1"})
    resp = client.get("/api/chains")
    assert len(resp.json()["chains"]) >= 1

def test_delete_chain(client, news_db):
    r = client.post("/api/chains", json={"title": "To Delete"})
    cid = r.json()["id"]
    resp = client.delete(f"/api/chains/{cid}")
    assert resp.status_code == 200

def test_merge_events(client, news_db):
    resp = client.post("/api/events/1/merge", json={"target_event_id": 2})
    assert resp.status_code == 200

def test_split_event(client, news_db):
    # Get event detail to find article ids
    resp = client.get("/api/events/1")
    articles = resp.json().get("articles", [])
    if len(articles) >= 2:
        ids = [a["id"] for a in articles[:2]]
        resp = client.post("/api/events/1/split", json={"article_ids": ids, "new_event_title": "Split Event"})
        assert resp.status_code == 200
        assert resp.json()["new_event_id"] > 0

def test_create_relation(client, news_db):
    resp = client.post("/api/relations", json={"from_event_id": 1, "to_event_id": 2, "relation": "related"})
    assert resp.status_code == 200

def test_settings(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert "db_path" in resp.json()

    resp = client.put("/api/settings", json={"user_agent": "test-agent"})
    assert resp.status_code == 200
    assert resp.json()["user_agent"] == "test-agent"
```

- [ ] **Step 3: Run tests and verify they pass**

Run: `cd tests/backend && pip install fastapi.testclient httpx && python -m pytest test_api.py -v`
Expected: All tests pass (or skip the ones requiring testclient availability — use `pytest` from the backend directory after installing `httpx`)

- [ ] **Step 4: Commit**

```bash
git add tests/backend/
git commit -m "test: add backend integration tests for all API endpoints"
```

---

### Task 16: AI Client Module

**Files:**
- Create: `news-web/backend/ai_client.py`

- [ ] **Step 1: Write ai_client.py**

```python
"""
OpenAI-compatible API client wrapper.
Supports OpenAI, DeepSeek, Ollama, or any compatible endpoint.
"""
from openai import OpenAI
from config import config


def get_client() -> OpenAI:
    return OpenAI(
        base_url=config.openai_base_url,
        api_key=config.openai_api_key or 'sk-placeholder',
    )


def chat(prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
    """Simple chat completion. Returns the response text."""
    client = get_client()
    resp = client.chat.completions.create(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def summarize_events(articles_text: str) -> str:
    """Ask AI to generate a neutral event summary from a set of article titles."""
    return chat(
        f"Below are news article titles about the same topic. "
        f"Write a concise neutral event title (max 15 words) that covers all of them:\n\n{articles_text}",
        system_prompt="You are a news analysis assistant. Output only the title, no explanation."
    )
```

- [ ] **Step 2: Add openai to requirements.txt**

```
openai==1.55.0
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/ai_client.py news-web/backend/requirements.txt
git commit -m "feat: add OpenAI-compatible AI client module"
```

---

### Task 17: Pipeline Scripts Integration

**Files:**
- Create: `news-web/backend/pipeline/__init__.py`
- Copy: pipeline scripts from Skill repo
- Create: `news-web/backend/pipeline/run_all.py`

- [ ] **Step 1: Copy pipeline scripts from Skill repo**

Run:
```bash
mkdir -p news-web/backend/pipeline
for f in fetch_english_news.py collect_data.py fetch_content.py analyze.py cron_runner.sh; do
  cp /tmp/claw_skill_news_aggregation/$f news-web/backend/pipeline/$f
done
```

- [ ] **Step 2: Write pipeline/__init__.py**

```python
from .run_all import run_pipeline
```

- [ ] **Step 3: Write pipeline/run_all.py**

```python
"""
Pipeline orchestrator — runs the full fetch → cluster → analyze cycle.
Replaces cron_runner.sh / Hermes/OpenClaw scheduling.
Call via `run_pipeline(db_path, user_agent)` or `python -m backend.pipeline.run_all`.
"""
import os, sys, subprocess, json, logging
from datetime import datetime

logger = logging.getLogger(__name__)

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_pipeline(db_path: str = "", user_agent: str = "", callback=None):
    """
    Execute the full pipeline sequence:
    1. fetch_english_news.py — RSS feeds
    2. collect_data.py — dedup, cluster, save to DB
    3. fetch_content.py — archive pages (optional)
    4. AI analysis (if API configured)
    
    Args:
        db_path: SQLite database path (injects into subprocess env)
        user_agent: UA for fetch scripts
        callback: optional function(status, step) for progress reporting
    """
    env = os.environ.copy()
    if db_path:
        env['NEWS_DB_PATH'] = db_path
    if user_agent:
        env['USER_AGENT'] = user_agent

    steps = [
        ('fetch_english_news.py', 'RSS 抓取'),
        ('collect_data.py', '去重聚类'),
        ('fetch_content.py', '页面归档'),
    ]

    for script, label in steps:
        logger.info(f"[Pipeline] {label}...")
        if callback:
            callback('running', label)
        
        result = subprocess.run(
            [sys.executable, os.path.join(PIPELINE_DIR, script)],
            env=env, capture_output=True, text=True, timeout=300,
        )
        
        if result.returncode != 0:
            logger.error(f"[Pipeline] {label} 失败: {result.stderr[:200]}")
            if callback:
                callback('error', f"{label}: {result.stderr[:100]}")
            return False
        
        logger.info(f"[Pipeline] {label} 完成")

    if callback:
        callback('complete', '全部完成')
    return True


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    success = run_pipeline()
    sys.exit(0 if success else 1)
```

- [ ] **Step 4: Commit**

```bash
git add news-web/backend/pipeline/
git commit -m "feat: integrate pipeline scripts with orchestrator"
```

---

### Task 18: Scheduler — Automated Daily Runs

**Files:**
- Create: `news-web/backend/scheduler.py`
- Modify: `news-web/backend/main.py` (start scheduler on startup)

- [ ] **Step 1: Add APScheduler to requirements.txt**

```
apscheduler==3.10.4
```

- [ ] **Step 2: Write scheduler.py**

```python
"""
APScheduler-based pipeline scheduler.
Runs the news pipeline at 10:00 and 17:00 daily.
Can be toggled on/off via config.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from pipeline.run_all import run_pipeline

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

PIPELINE_CRON = [
    CronTrigger(hour=10, minute=0),   # 10:00
    CronTrigger(hour=17, minute=0),   # 17:00
]


async def _run_pipeline_job():
    """Wrapper that logs the pipeline run."""
    logger.info("Scheduled pipeline starting...")
    try:
        success = run_pipeline(
            db_path=config.db_path,
            user_agent=config.user_agent,
        )
        if success:
            logger.info("Scheduled pipeline completed successfully")
        else:
            logger.error("Scheduled pipeline failed")
    except Exception as e:
        logger.exception(f"Scheduled pipeline error: {e}")


def start_scheduler():
    """Start scheduler if enabled in config."""
    if not config.pipeline_schedule_enabled:
        logger.info("Pipeline scheduler is disabled in config")
        return
    
    if not scheduler.running:
        for trigger in PIPELINE_CRON:
            scheduler.add_job(_run_pipeline_job, trigger)
        scheduler.start()
        logger.info("Pipeline scheduler started: daily 10:00 / 17:00")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Pipeline scheduler stopped")


async def trigger_pipeline_manual():
    """Manually trigger a pipeline run (via API)."""
    await _run_pipeline_job()
    return {'ok': True}
```

- [ ] **Step 3: Update main.py to start/stop scheduler on lifespan**

Add scheduler imports and integration into the lifespan:

```python
# Add after existing imports
from scheduler import start_scheduler, stop_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.db_path:
        ensure_schema(config.db_path)
    start_scheduler()                      # Start daily cron jobs
    yield
    stop_scheduler()                       # Clean shutdown
```

Also add a manual trigger endpoint for testing:

```python
# Add after health endpoint
from scheduler import trigger_pipeline_manual

@app.post("/api/pipeline/run")
async def manual_pipeline_run():
    """Manually trigger the news pipeline."""
    import asyncio
    asyncio.create_task(trigger_pipeline_manual())
    return {"status": "pipeline_started"}
```

- [ ] **Step 4: Update API client with pipeline endpoint**

In `frontend/src/api/client.ts`, add:

```typescript
triggerPipeline: () => fetchJSON<{ status: string }>('/pipeline/run', { method: 'POST' }),
```

- [ ] **Step 5: Commit**

```bash
git add news-web/backend/scheduler.py news-web/backend/main.py news-web/backend/requirements.txt
git commit -m "feat: add APScheduler for daily pipeline at 10:00 and 17:00"
```

---

## Spec Coverage Check

| Spec requirement | Implemented in |
|---|---|
| 1.1 logic_chains table schema | Task 2 (migrations.py) |
| 2.2 Directory structure | Task 1-18 (all files) |
| 3.1 Sidebar navigation | Task 10 (NavSidebar) |
| 3.2 Workspace canvas + drag-drop | Task 13 (ChainCanvas, SearchPanel) |
| 3.3 Logic chain operations (splice/split/reorder) | Task 6 (chains.py API) |
| 3.4 Dashboard with stats | Task 11 (Dashboard) |
| 3.5 Article search with filters | Task 12 (ArticleSearch) |
| 3.6 Settings panel (DB + OpenAI + schedule) | Task 14 (Settings) |
| 4.1 GET /api/stats | Task 3 |
| 4.2 Article endpoints | Task 4 |
| 4.3 Event endpoints | Task 5 |
| 4.4 Chain endpoints | Task 6 |
| 4.5 Relation endpoints | Task 7 |
| 4.6 Settings endpoints | Task 3 |
| 5 Scheduler (10:00 / 17:00) | Task 18 |
| 5 Manual pipeline trigger | Task 18 |
| 6.1 DB not found handling | Task 3 (get_db() raises 400) |
| 6.2 WAL mode | Task 2 |
| 6.4 Event split safety | Task 5 (rejects <1 article) |
| 7 Backend integration tests | Task 15 |
| OpenAI-compatible config | Task 1 (config.py), Task 3 (settings API), Task 14 (frontend), Task 16 (ai_client) |
| Pipeline integration | Task 17 (copy scripts + run_all.py) |
| Scheduler integration | Task 18 |
