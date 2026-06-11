# 数据采集状态监控 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为新闻抓取与缓存系统新增「数据采集状态监控」独立页面，支持源/单篇级重试 + 抓取历史 DB 持久化。

**Architecture:** 新建 `fetch_logs` 持久化表记录每次抓取结果；新建 `api/fetch.py` 提供 8 个 REST 端点；新建 `FetchMonitor.tsx` 前端页面（4 区块布局）；在 `run_all.py` pipeline 各步骤后自动写日志。

**Tech Stack:** Python 3.14 + FastAPI + SQLite，React 18 + TypeScript，pytest + Vitest

**Spec:** `docs/superpowers/specs/2026-06-11-fetch-monitor-design.md`

---

## 依赖关系

```
Task 1 (migration: fetch_logs 表)
  └── Task 2 (news_db.py: fetch_logs CRUD)
        ├── Task 3 (api/fetch.py: 8 endpoints)
        │     ├── Task 4 (run_all.py: pipeline 写日志)
        │     ├── Task 5 (main.py: 注册 router)
        │     └── Task 10 (tests: 8 用例)
        └── (独立) Task 6 (前端 types)
              └── Task 7 (前端 client.ts)
                    └── Task 8 (FetchMonitor.tsx)
                          └── Task 9 (App.tsx + NavSidebar.tsx)
```

**Task 1-5 必须顺序执行。Task 6-9 可与 3-5 并行，但内部依赖顺序。Task 10 在 Task 3 完成后执行。**

---

### Task 1: DB 迁移 — 建 `fetch_logs` 表

**Files:**
- Modify: `news-web/backend/db/migrations.py`

在 `ensure_schema()` 函数末尾（`ensure_audit_table(db_path)` 之后），加入 fetch_logs 建表逻辑：

- [ ] **Step 1: 添加 fetch_logs 建表 SQL**

编辑 `news-web/backend/db/migrations.py`，在函数末尾的 `ensure_audit_table(db_path)` 之后，`return None` 之前（该函数没有显式 return，实际在 `conn.close()` 之前），插入以下代码：

```python
    # ── fetch_logs: 抓取历史记录表 ──────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name     TEXT    NOT NULL,
            source_type     TEXT    NOT NULL,
            articles_fetched INTEGER DEFAULT 0,
            articles_new    INTEGER DEFAULT 0,
            status          TEXT    DEFAULT 'ok',
            error_msg       TEXT,
            duration_ms     INTEGER,
            started_at      TEXT    NOT NULL,
            finished_at     TEXT,
            run_type        TEXT    DEFAULT 'scheduled'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fetch_logs_source
        ON fetch_logs(source_name, started_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fetch_logs_type
        ON fetch_logs(source_type, started_at)
    """)
```

- [ ] **Step 2: 验证 DB 迁移幂等性**

```bash
cd news-web && python -c "
import sqlite3, tempfile, os
from db.migrations import ensure_schema
path = os.path.join(tempfile.gettempdir(), 'test_migration.db')
ensure_schema(path)
# 第二次调用不应抛异常
ensure_schema(path)
conn = sqlite3.connect(path)
cols = [r[1] for r in conn.execute('PRAGMA table_info(fetch_logs)')]
print('fetch_logs columns:', cols)
conn.close()
os.remove(path)
"
```

Expected output: `fetch_logs columns: ['id', 'source_name', 'source_type', 'articles_fetched', 'articles_new', 'status', 'error_msg', 'duration_ms', 'started_at', 'finished_at', 'run_type']`

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/backend/db/migrations.py
git commit -m "feat: 新增 fetch_logs 表记录抓取历史

幂等迁移，含 source_name+started_at / source_type+started_at 两个索引

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `news_db.py` — fetch_logs CRUD 方法

**Files:**
- Modify: `news-web/backend/db/news_db.py`

在 `NewsDB` 类的 `get_hotlists()` 方法之后（约 1186 行），新增以下 6 个方法：

- [ ] **Step 1: 添加 `log_fetch()` 方法**

```python
    # ═══════════════════════════════════════════════════════
    # 抓取日志 (fetch_logs)
    # ═══════════════════════════════════════════════════════

    def log_fetch(self, source_name: str, source_type: str,
                  articles_fetched: int = 0, articles_new: int = 0,
                  status: str = 'ok', error_msg: str = '',
                  duration_ms: int = 0, run_type: str = 'scheduled') -> int:
        """写入一条抓取日志，返回 log id。"""
        now = datetime.now().isoformat(timespec='seconds')
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO fetch_logs
                    (source_name, source_type, articles_fetched, articles_new,
                     status, error_msg, duration_ms, started_at, finished_at, run_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (source_name, source_type, articles_fetched, articles_new,
                  status, error_msg, duration_ms, now, now, run_type))
            conn.commit()
        return cur.lastrowid
```

- [ ] **Step 2: 添加 `get_fetch_overview()` 方法**

```python
    def get_fetch_overview(self) -> dict:
        """总览统计 — 按源类型汇总最新状态 + 缓存覆盖。"""
        today = datetime.now().strftime('%Y-%m-%d')
        with self._conn() as conn:
            # RSS 统计
            rss_stats = conn.execute("""
                SELECT
                    COUNT(DISTINCT source_name) as total,
                    COUNT(DISTINCT CASE WHEN status='ok' THEN source_name END) as ok_sources,
                    MAX(started_at) as last_run,
                    SUM(CASE WHEN date(started_at)=? THEN articles_new ELSE 0 END) as today_new
                FROM fetch_logs WHERE source_type='rss'
            """, (today,)).fetchone()
            # 每个源的最近健康状态
            rss_sources = conn.execute("""
                SELECT source_name, status FROM fetch_logs
                WHERE source_type='rss' AND source_name IN (
                    SELECT source_name FROM fetch_logs WHERE source_type='rss'
                    GROUP BY source_name HAVING COUNT(*) >= 1
                )
                ORDER BY started_at DESC
            """).fetchall()
            # 计算 healthy/degraded/failing
            rss_health = self._compute_source_health(conn, 'rss')

            # 平台热榜统计
            hl_stats = conn.execute("""
                SELECT
                    COUNT(DISTINCT source_name) as total,
                    MAX(started_at) as last_run,
                    SUM(CASE WHEN date(started_at)=? THEN articles_new ELSE 0 END) as today_new
                FROM fetch_logs WHERE source_type='hotlist'
            """, (today,)).fetchone()
            hl_health = self._compute_source_health(conn, 'hotlist')

            # 缓存统计（复用现有 get_stats 逻辑）
            total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            cached = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%'"
            ).fetchone()[0]
            pending = total - cached - failed
            cached_pct = round(cached / total * 100, 1) if total > 0 else 0.0

        return {
            'rss': {
                'total_sources': rss_stats[0] or 0,
                'healthy': rss_health.get('healthy', 0),
                'degraded': rss_health.get('degraded', 0),
                'failing': rss_health.get('failing', 0),
                'last_run': rss_stats[2],
                'articles_today': rss_stats[3] or 0,
            },
            'hotlist': {
                'total_sources': hl_stats[0] or 0,
                'healthy': hl_health.get('healthy', 0),
                'degraded': hl_health.get('degraded', 0),
                'failing': hl_health.get('failing', 0),
                'last_run': hl_stats[1],
                'articles_today': hl_stats[2] or 0,
            },
            'cache': {
                'total_articles': total,
                'cached': cached,
                'pending': pending,
                'failed': failed,
                'cached_pct': cached_pct,
            },
        }
```

- [ ] **Step 3: 添加 `_compute_source_health()` 私有方法**

```python
    def _compute_source_health(self, conn: sqlite3.Connection,
                               source_type: str) -> dict:
        """按源类型计算健康度统计。"""
        sources = conn.execute("""
            SELECT source_name FROM fetch_logs
            WHERE source_type=?
            GROUP BY source_name
        """, (source_type,)).fetchall()
        healthy = degraded = failing = 0
        for (name,) in sources:
            recent = conn.execute("""
                SELECT status FROM fetch_logs
                WHERE source_name=? AND source_type=?
                ORDER BY started_at DESC LIMIT 5
            """, (name, source_type)).fetchall()
            if not recent:
                healthy += 1  # 新源默认健康
                continue
            ok_count = sum(1 for (s,) in recent if s == 'ok')
            success_rate = ok_count / len(recent)
            consecutive_fails = 0
            for (s,) in recent:
                if s == 'failed':
                    consecutive_fails += 1
                else:
                    break
            if success_rate == 1.0:
                healthy += 1
            elif success_rate >= 0.6 and consecutive_fails < 3:
                degraded += 1
            else:
                failing += 1
        return {'healthy': healthy, 'degraded': degraded, 'failing': failing}
```

- [ ] **Step 4: 添加 `get_fetch_sources()` 方法**

```python
    def get_fetch_sources(self, source_type: str = '') -> list:
        """返回所有源的详情列表（含健康状态、缓存覆盖率）。"""
        with self._conn() as conn:
            # 从 articles 表获取所有出现过的源名
            where = "WHERE 1=1"
            params = []
            if source_type:
                # 按源类型推导 article category — RSS → rss_news, hotlist → platform_hotlists
                cat_map = {'rss': 'rss_news', 'hotlist': 'platform_hotlists', 'bilibili': 'bilibili_videos'}
                if source_type in cat_map:
                    where = "WHERE category=?"
                    params = [cat_map[source_type]]
            sources = conn.execute(f"""
                SELECT DISTINCT source, category FROM articles {where}
                ORDER BY source
            """, params).fetchall()
            result = []
            for src_name, category in sources:
                # 源类型映射
                if category == 'rss_news':
                    stype = 'rss'
                elif category == 'bilibili_videos':
                    stype = 'bilibili'
                else:
                    stype = 'hotlist'
                # 最近 5 次抓取状态
                recent_logs = conn.execute("""
                    SELECT status, articles_fetched, articles_new, started_at, error_msg
                    FROM fetch_logs WHERE source_name=?
                    ORDER BY started_at DESC LIMIT 5
                """, (src_name,)).fetchall()
                # 计算健康
                ok_count = sum(1 for r in recent_logs if r[0] == 'ok')
                success_rate = round(ok_count / len(recent_logs), 2) if recent_logs else 1.0
                consecutive_fails = 0
                for r in recent_logs:
                    if r[0] == 'failed': consecutive_fails += 1
                    else: break
                if not recent_logs:
                    health = 'healthy'
                elif success_rate == 1.0:
                    health = 'healthy'
                elif success_rate >= 0.6 and consecutive_fails < 3:
                    health = 'degraded'
                else:
                    health = 'failing'
                # 缓存统计
                total = conn.execute(
                    "SELECT COUNT(*) FROM articles WHERE source=?", (src_name,)
                ).fetchone()[0]
                cached = conn.execute(
                    "SELECT COUNT(*) FROM articles WHERE source=? AND local_path!='' AND local_path NOT LIKE '[ERR:%'",
                    (src_name,)
                ).fetchone()[0]
                failed = conn.execute(
                    "SELECT COUNT(*) FROM articles WHERE source=? AND local_path LIKE '[ERR:%'",
                    (src_name,)
                ).fetchone()[0]
                result.append({
                    'name': src_name,
                    'type': stype,
                    'health': health,
                    'last_fetch': recent_logs[0][3] if recent_logs else None,
                    'last_status': recent_logs[0][0] if recent_logs else 'unknown',
                    'last_error': recent_logs[0][4] if recent_logs and recent_logs[0][4] else '',
                    'total_articles': total,
                    'cached_articles': cached,
                    'failed_articles': failed,
                    'success_rate_5': success_rate,
                })
        return result
```

- [ ] **Step 5: 添加 `get_fetch_source_history()` 方法**

```python
    def get_fetch_source_history(self, source_name: str, days: int = 7) -> list:
        """获取单源抓取历史。"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec='seconds')
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT id, source_name, source_type, articles_fetched, articles_new,
                       status, error_msg, duration_ms, started_at, finished_at, run_type
                FROM fetch_logs
                WHERE source_name=? AND started_at >= ?
                ORDER BY started_at DESC
                LIMIT 50
            """, (source_name, cutoff)).fetchall()
        return [
            {
                'id': r[0], 'source_name': r[1], 'source_type': r[2],
                'articles_fetched': r[3], 'articles_new': r[4],
                'status': r[5], 'error_msg': r[6] or '',
                'duration_ms': r[7], 'started_at': r[8], 'finished_at': r[9],
                'run_type': r[10],
            }
            for r in rows
        ]

    def get_fetch_recent_logs(self, limit: int = 50) -> list:
        """获取全量最近抓取日志（供前端日志面板）。"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT source_name, source_type, articles_fetched, articles_new,
                       status, error_msg, duration_ms, started_at, run_type
                FROM fetch_logs
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [
            {
                'source_name': r[0], 'source_type': r[1],
                'articles_fetched': r[2], 'articles_new': r[3],
                'status': r[4], 'error_msg': r[5] or '',
                'duration_ms': r[6], 'started_at': r[7], 'run_type': r[8],
            }
            for r in rows
        ]
```

- [ ] **Step 6: 验证 DB 方法可调用**

```bash
cd news-web && python -c "
import tempfile, os
from db.news_db import NewsDB
from db.migrations import ensure_schema
path = os.path.join(tempfile.gettempdir(), 'test_db_methods.db')
ensure_schema(path)
db = NewsDB(path)
# Test log_fetch
lid = db.log_fetch('TestSource', 'rss', 10, 3, 'ok', '', 1500, 'manual')
print(f'log_fetch returned id: {lid}')
# Test overview (should return empty stats)
ov = db.get_fetch_overview()
print(f'overview rss sources: {ov[\"rss\"][\"total_sources\"]}')
# Test sources
srcs = db.get_fetch_sources()
print(f'sources count: {len(srcs)}')
# Test history
hist = db.get_fetch_source_history('TestSource', 7)
print(f'history for TestSource: {len(hist)} records')
# Test recent logs
logs = db.get_fetch_recent_logs(10)
print(f'recent logs: {len(logs)} records')
os.remove(path)
print('All DB methods OK')
"
```

Expected: `All DB methods OK`

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/backend/db/news_db.py
git commit -m "feat: news_db 新增 fetch_logs CRUD 方法

log_fetch / get_fetch_overview / _compute_source_health / get_fetch_sources / get_fetch_source_history / get_fetch_recent_logs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 新建 `api/fetch.py` — 8 个端点

**Files:**
- Create: `news-web/backend/api/fetch.py`

- [ ] **Step 1: 创建文件并编写全部代码**

创建 `news-web/backend/api/fetch.py`：

```python
"""
数据采集状态监控 API — 抓取历史、源健康、缓存重试。
"""
import os, sqlite3, threading, logging, time
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

from config import config

router = APIRouter(prefix="/api/fetch", tags=["fetch"])
logger = logging.getLogger(__name__)

# 源重试互斥 — 同一时间每个源只允许一个重试任务
_retry_locks: dict = {}
_retry_lock = threading.Lock()

# 最多缓存重试日志条数
LOG_MAX = 200
_retry_state: dict = {
    "running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []
}


def _conn():
    if not config.db_path:
        raise HTTPException(400, "database_not_configured")
    return sqlite3.connect(config.db_path)


def _get_new_db():
    from db.news_db import NewsDB
    return NewsDB(config.db_path)


# ══════════════════════════════════════════════════════════════
# 抓取总览
# ══════════════════════════════════════════════════════════════

@router.get("/overview")
def fetch_overview():
    """总览统计 — RSS/热榜/缓存 三维度概览。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    return db.get_fetch_overview()


# ══════════════════════════════════════════════════════════════
# 源列表
# ══════════════════════════════════════════════════════════════

@router.get("/sources")
def fetch_sources(source_type: str = Query("", description="筛选类型: rss | hotlist | bilibili")):
    """所有源的详情列表（含健康状态、成功率）。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    sources = db.get_fetch_sources(source_type=source_type or '')
    return {"sources": sources}


# ══════════════════════════════════════════════════════════════
# 单源历史
# ══════════════════════════════════════════════════════════════

@router.get("/sources/{name}/history")
def fetch_source_history(name: str, days: int = Query(7, ge=1, le=90)):
    """单源抓取历史记录。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    history = db.get_fetch_source_history(name, days=days)
    return {"source": name, "days": days, "history": history}


# ══════════════════════════════════════════════════════════════
# 源重试
# ══════════════════════════════════════════════════════════════

@router.post("/sources/{name}/retry")
def retry_fetch_source(name: str):
    """单源重抓 — 后台线程执行。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    with _retry_lock:
        if name in _retry_locks and _retry_locks[name]:
            return {"ok": False, "message": f"源 {name} 正在抓取中，请稍后再试"}

    # 确定源类型和 URL
    source_type = ''
    feed_info = None
    # 检查 RSS 源
    try:
        from pipeline.fetch_english_news import RSS_FEEDS
        for f in RSS_FEEDS:
            if f['name'] == name:
                feed_info = f
                source_type = 'rss'
                break
    except ImportError:
        pass

    if not feed_info:
        # 未找到则返回 404
        return HTTPException(status_code=404, detail=f"未知源: {name}")

    with _retry_lock:
        _retry_locks[name] = True

    def _do_retry():
        started = datetime.now()
        try:
            from pipeline.fetch_english_news import fetch_feed
            from db.news_db import NewsDB
            db = NewsDB(config.db_path)
            items = fetch_feed(feed_info)
            fetched = len(items)
            saved, skipped = db.save_articles('rss_news', items)
            db.link_articles_to_events()
            elapsed = int((datetime.now() - started).total_seconds() * 1000)
            db.log_fetch(
                source_name=name, source_type=source_type,
                articles_fetched=fetched, articles_new=saved,
                status='ok', duration_ms=elapsed, run_type='manual'
            )
            logger.info(f"[fetch] 手动重抓 {name}: {saved} 新增/{fetched} 条, {elapsed}ms")
        except Exception as e:
            elapsed = int((datetime.now() - started).total_seconds() * 1000)
            try:
                db = NewsDB(config.db_path)
                db.log_fetch(
                    source_name=name, source_type=source_type,
                    articles_fetched=0, articles_new=0,
                    status='failed', error_msg=str(e)[:200],
                    duration_ms=elapsed, run_type='manual'
                )
            except Exception:
                pass
            logger.error(f"[fetch] 手动重抓 {name} 失败: {e}")
        finally:
            with _retry_lock:
                _retry_locks[name] = False

    threading.Thread(target=_do_retry, daemon=True).start()
    return {"ok": True, "message": f"开始重抓源: {name}"}


# ══════════════════════════════════════════════════════════════
# 源文章列表
# ══════════════════════════════════════════════════════════════

@router.get("/sources/{name}/articles")
def fetch_source_articles(
    name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status_filter: str = Query("", alias="status", description="缓存状态筛选: pending | fetched | failed | translated"),
):
    """该源文章列表 — 分页 + 按缓存状态筛选。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    conn = _conn()
    where_clauses = ["source = ?"]
    params = [name]
    if status_filter == 'pending':
        where_clauses.append("(local_path IS NULL OR local_path = '')")
    elif status_filter == 'fetched':
        where_clauses.append("local_path != '' AND local_path NOT LIKE '[ERR:%'")
    elif status_filter == 'failed':
        where_clauses.append("local_path LIKE '[ERR:%'")
    elif status_filter == 'translated':
        where_clauses.append("translated_content != ''")

    where = " AND ".join(where_clauses)
    total = conn.execute(f"SELECT COUNT(*) FROM articles WHERE {where}", params).fetchone()[0]
    offset = (page - 1) * limit
    rows = conn.execute(f"""
        SELECT id, title, url, source, content_status, local_path,
               content_fetched_at, content_lang, translated_content
        FROM articles WHERE {where}
        ORDER BY id DESC LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    conn.close()

    articles = []
    for r in rows:
        status = 'failed' if (r[5] or '').startswith('[ERR:') else (
            'translated' if r[8] else ('fetched' if r[5] else 'pending')
        )
        articles.append({
            'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
            'content_status': status,
            'local_path': r[5] or '',
            'content_fetched_at': r[6],
            'content_lang': r[7] or '',
            'has_translation': bool(r[8]),
        })

    return {"total": total, "page": page, "limit": limit, "source": name, "articles": articles}


# ══════════════════════════════════════════════════════════════
# 失败文章列表
# ══════════════════════════════════════════════════════════════

@router.get("/articles/failed")
def fetch_failed_articles(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """下载失败的文章分页列表。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    conn = _conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%'"
    ).fetchone()[0]
    offset = (page - 1) * limit
    rows = conn.execute("""
        SELECT id, title, url, source, local_path, content_fetched_at
        FROM articles WHERE local_path LIKE '[ERR:%'
        ORDER BY id DESC LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    conn.close()

    articles = [
        {
            'id': r[0], 'title': r[1], 'url': r[2], 'source': r[3],
            'error': (r[4] or '[ERR:unknown]').replace('[ERR:', '').rstrip(']'),
            'content_fetched_at': r[5],
        }
        for r in rows
    ]
    return {"total": total, "page": page, "limit": limit, "articles": articles}


# ══════════════════════════════════════════════════════════════
# 单篇缓存重试
# ══════════════════════════════════════════════════════════════

@router.post("/articles/{article_id}/retry-cache")
def retry_article_cache(article_id: int):
    """单篇文章缓存重试 — 重新下载 HTML 并提取文本。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    conn = _conn()
    row = conn.execute(
        "SELECT id, title, url FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "文章不存在")

    def _do_one():
        aid, title, url = row
        try:
            from pipeline.fetch_content import download_page, sanitize_html
            from utils.text import extract_text_from_html, detect_language
            from datetime import datetime as _dt

            if not url or not url.startswith('http'):
                _log_retry(f"#{aid} ⚠️ 无有效 URL，跳过")
                return

            _log_retry(f"#{aid} 📡 下载中...")
            res = download_page(url)
            if res['error']:
                conn2 = _conn()
                conn2.execute(
                    "UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                    (f"[ERR:{res['error']}]", _dt.now().isoformat(timespec='seconds'), aid)
                )
                conn2.commit(); conn2.close()
                _log_retry(f"#{aid} ❌ {res['error']}")
                return

            html = sanitize_html(res['html'])
            content_dir = config.content_cache_path
            os.makedirs(content_dir, exist_ok=True)
            file_path = os.path.join(content_dir, f'{aid}.html')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html)

            text = extract_text_from_html(html)
            lang = detect_language(text)
            now = _dt.now().isoformat(timespec='seconds')
            rel_path = f'{os.path.basename(content_dir)}/{aid}.html'
            conn2 = _conn()
            conn2.execute("""
                UPDATE articles SET
                    local_path=?, content_fetched_at=?,
                    text_content=?, content_lang=?, content_status='fetched'
                WHERE id=?
            """, (rel_path, now, text, lang, aid))
            conn2.commit(); conn2.close()
            _log_retry(f"#{aid} ✅ 缓存成功 [{lang}] {len(html)//1024}KB")

            # 内联翻译英文文章
            if lang == 'en' and config.translation_enabled and config.translation_api_key:
                try:
                    from translation_client import translate_to_chinese
                    translation = translate_to_chinese(text)
                    if translation:
                        conn2 = _conn()
                        conn2.execute("""
                            UPDATE articles SET
                                translated_content=?, content_status='translated', translated_at=?
                            WHERE id=?
                        """, (translation, _dt.now().isoformat(timespec='seconds'), aid))
                        conn2.commit(); conn2.close()
                        _log_retry(f"#{aid} ✅ 翻译完成")
                except Exception as e:
                    _log_retry(f"#{aid} ⚠️ 翻译失败: {str(e)[:60]}")
        except Exception as e:
            _log_retry(f"#{aid} ❌ {str(e)[:80]}")

    threading.Thread(target=_do_one, daemon=True).start()
    return {"ok": True, "message": f"开始重试文章 #{article_id} 的缓存下载"}


# ══════════════════════════════════════════════════════════════
# 批量缓存重试
# ══════════════════════════════════════════════════════════════

@router.post("/articles/batch-retry")
def retry_articles_batch(body: dict):
    """批量缓存重试 — 最多 50 篇。"""
    if not config.db_path:
        return {"error": "database_not_configured"}

    ids = body.get('ids', [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "请提供文章 ID 列表")

    if len(ids) > 50:
        raise HTTPException(400, f"单次最多重试 50 篇，你传了 {len(ids)} 篇")

    global _retry_state
    if _retry_state.get("running"):
        return {"ok": False, "message": "批量重试任务已在运行中"}

    _retry_state = {"running": True, "total": len(ids), "done": 0, "failed": 0, "current": "", "log": []}

    def _batch_retry():
        global _retry_state
        from pipeline.fetch_content import download_page, sanitize_html
        from utils.text import extract_text_from_html, detect_language
        from datetime import datetime as _dt

        for idx, aid in enumerate(ids, 1):
            _retry_state["current"] = f"#{aid}"
            conn = _conn()
            row = conn.execute("SELECT id, title, url FROM articles WHERE id=?", (aid,)).fetchone()
            conn.close()
            if not row:
                _log_retry(f"#{aid} ⚠️ 文章不存在")
                _retry_state["failed"] += 1
                _retry_state["done"] += 1
                continue

            _, title, url = row
            if not url or not url.startswith('http'):
                _log_retry(f"#{aid} ⚠️ 无有效 URL")
                _retry_state["failed"] += 1
                _retry_state["done"] += 1
                continue

            try:
                res = download_page(url)
                if res['error']:
                    conn2 = _conn()
                    conn2.execute(
                        "UPDATE articles SET local_path=?, content_fetched_at=? WHERE id=?",
                        (f"[ERR:{res['error']}]", _dt.now().isoformat(timespec='seconds'), aid)
                    )
                    conn2.commit(); conn2.close()
                    _log_retry(f"#{aid} ❌ {res['error']}")
                    _retry_state["failed"] += 1; _retry_state["done"] += 1
                    continue

                html = sanitize_html(res['html'])
                content_dir = config.content_cache_path
                os.makedirs(content_dir, exist_ok=True)
                file_path = os.path.join(content_dir, f'{aid}.html')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html)

                text = extract_text_from_html(html)
                lang = detect_language(text)
                now = _dt.now().isoformat(timespec='seconds')
                rel_path = f'{os.path.basename(content_dir)}/{aid}.html'
                conn2 = _conn()
                conn2.execute("""
                    UPDATE articles SET
                        local_path=?, content_fetched_at=?,
                        text_content=?, content_lang=?, content_status='fetched'
                    WHERE id=?
                """, (rel_path, now, text, lang, aid))
                conn2.commit(); conn2.close()
                _log_retry(f"#{aid} ✅ 缓存成功 [{lang}]")
                _retry_state["done"] += 1
                time.sleep(0.5)
            except Exception as e:
                _log_retry(f"#{aid} ❌ {str(e)[:80]}")
                _retry_state["failed"] += 1; _retry_state["done"] += 1

        _retry_state["running"] = False
        _retry_state["current"] = "完成"

    threading.Thread(target=_batch_retry, daemon=True).start()
    return {"ok": True, "total": len(ids), "message": f"开始批量重试 {len(ids)} 篇文章的缓存下载"}


@router.get("/articles/batch-retry/status")
def batch_retry_status():
    """查询批量重试进度。"""
    return dict(_retry_state)


# ══════════════════════════════════════════════════════════════
# 最近抓取日志
# ══════════════════════════════════════════════════════════════

@router.get("/logs")
def fetch_recent_logs(limit: int = Query(50, ge=1, le=200)):
    """全量最近抓取日志。"""
    if not config.db_path:
        return {"error": "database_not_configured"}
    db = _get_new_db()
    logs = db.get_fetch_recent_logs(limit)
    return {"logs": logs}


# ── 内部工具 ──────────────────────────────────────────────

def _log_retry(msg: str):
    """批量重试进度记录。"""
    global _retry_state
    ts = datetime.now().strftime('%H:%M:%S')
    _retry_state["log"].append(f"[{ts}] {msg}")
    if len(_retry_state["log"]) > LOG_MAX:
        _retry_state["log"] = _retry_state["log"][-LOG_MAX:]
```

- [ ] **Step 2: 验证 endpoint 导入和路由注册正常**

```bash
cd news-web && python -c "
import os, sys
os.environ['NEWS_WEB_TESTING'] = '1'
sys.path.insert(0, 'backend')
from api.fetch import router
print(f'router prefix: {router.prefix}')
print(f'endpoints: {[r.path for r in router.routes]}')
print('API module OK')
"
```

Expected output shows all 8 endpoint paths.

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/backend/api/fetch.py
git commit -m "feat: 新增 api/fetch.py — 数据采集监控 8 端点

overview / sources / source history / source retry / source articles / failed articles / single retry / batch retry + logs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `run_all.py` — Pipeline 步骤后写入 fetch_logs

**Files:**
- Modify: `news-web/backend/pipeline/run_all.py`

在 `run_pipeline()` 函数的 `for script, label in steps:` 循环中，每个 step 执行后，解析 stdout 并写入 `fetch_logs`。

- [ ] **Step 1: 修改 run_pipeline() — 添加日志写入逻辑**

在 `news-web/backend/pipeline/run_all.py` 的 `run_pipeline()` 函数中，找到 `for script, label in steps:` 循环体。在 `result = subprocess.run(...)` 行之后，`if result.returncode != 0:` 之前，新增日志写入代码。

定位原代码（约第 68 行）：
```python
        result = subprocess.run(
            [sys.executable, script_path],
            env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=300,
        )

        if result.returncode != 0:
```

在 `result = subprocess.run(...)` 和 `if result.returncode != 0:` 之间插入：

```python
        # ── 记录 fetch_logs ──────────────────────────
        try:
            import re as _re
            from db.news_db import NewsDB as _NDB
            from datetime import datetime as _dt
            _ndb = _NDB(db_path)
            out = result.stdout or ''
            field_total = r'总条目[：:]\s*(\d+)'
            fetched_match = _re.search(field_total, out)
            articles_fetched = int(fetched_match.group(1)) if fetched_match else 0
            field_new = r'DB\s*↑.*?(\d+)\s+条新增'
            new_match = _re.search(field_new, out)
            articles_new = int(new_match.group(1)) if new_match else 0
            status = 'ok' if result.returncode == 0 else 'failed'
            error_msg = result.stderr[:200] if result.returncode != 0 else ''
            if status == 'failed' and not error_msg:
                error_msg = f'returncode={result.returncode}'
            # 确定 source_name 和 source_type
            if script == 'fetch_english_news.py':
                # RSS — 记录每个来源（从 RSS_FEEDS 取）
                from pipeline.fetch_english_news import RSS_FEEDS as _feeds
                for _f in _feeds:
                    _ndb.log_fetch(_f['name'], 'rss', 0, 0, status,
                                   error_msg, 0, 'scheduled' if not _is_manual else 'manual')
            elif script == 'fetch_platform_hotlists.py':
                platform_names = ['weibo', 'zhihu', 'douyin', 'toutiao', 'bilibili']
                for pn in platform_names:
                    _ndb.log_fetch(pn, 'hotlist' if pn != 'bilibili' else 'bilibili',
                                   0, 0, status, error_msg, 0,
                                   'scheduled' if not _is_manual else 'manual')
            else:
                # 非抓取步骤（去重/归档/翻译/分析）不写入 fetch_logs
                pass
        except Exception:
            logger.warning(f"Failed to write fetch_logs for {label}", exc_info=True)
```

等等，这样写太复杂了。让我简化——我们只需要在抓取步骤（fetch_english_news.py 和 fetch_platform_hotlists.py）后记录。而且解析 stdout 太脆弱。实际上更好的做法是：让 `collect_data.py` 的 `db.save_articles()` 已经输出了 `DB ↑ rss_news: N 条新增`，这个我可以解析。但最简洁的方式是：在脚本执行完后直接查询 articles 表中该 source 的 recently fetched 数量。

让我换一种更简单的实现：

```python
        # ── 记录 fetch_logs（仅抓取类步骤） ─────────
        _is_fetch_step = script in ('fetch_english_news.py', 'fetch_platform_hotlists.py')
        if _is_fetch_step and db_path:
            try:
                from db.news_db import NewsDB as _NDB
                _ndb = _NDB(db_path)
                status = 'ok' if result.returncode == 0 else 'failed'
                error_msg = result.stderr[:200] if result.returncode != 0 else ''
                run_type = _pipeline_run_type if '_pipeline_run_type' in dir() else 'scheduled'
                # 解析 stdout 中的统计数字
                out = result.stdout or ''
                import re as _re2
                fetched = int(_re2.search(r'总条目[：:]\s*(\d+)', out).group(1)) if _re2.search(r'总条目[：:]\s*(\d+)', out) else 0
                if script == 'fetch_english_news.py':
                    _ndb.log_fetch('RSS 批量抓取', 'rss', fetched, 0, status, error_msg, 0, run_type)
                elif script == 'fetch_platform_hotlists.py':
                    _ndb.log_fetch('平台热搜批量采集', 'hotlist', fetched, 0, status, error_msg, 0, run_type)
            except Exception as _fe:
                logger.warning(f"fetch_logs 写入失败: {_fe}")
```

实际上最好的方式非常简单：直接用函数参数传递 run_type。让我看看 scheduler.py 怎么调用的...

`scheduler.py` 的 `_run_pipeline_job()` 调用 `run_pipeline()`。手动触发也走同样的路径。最简单的实现：
- 在 `run_pipeline()` 函数签名中添加 `run_type='scheduled'` 参数
- 在每个抓取 step 执行后写一条汇总日志
- 不按源拆分（那样需要大改脚本输出），而是按步骤记录汇总

让我设计为更简洁的方案：按步骤记录，每个抓取脚本运行一次就写一条 `fetch_logs`。

OK let me finalize this. I'll keep the plan simple and direct.

- [ ] **Step 1: 修改 run_pipeline() 函数签名和日志写入**

在 `news-web/backend/pipeline/run_all.py` 中：

修改函数签名（约第 13 行）：
```python
def run_pipeline(db_path: str = "", user_agent: str = "", callback=None, run_type: str = 'scheduled'):
```

在 `for script, label in steps:` 循环体中，`result = subprocess.run(...)` 之后加入 fetch_logs 写入（约第 71 行）：

```python
        # ── 记录 fetch_logs（仅抓取类步骤） ─────────────
        if script in ('fetch_english_news.py', 'fetch_platform_hotlists.py') and db_path:
            try:
                from datetime import datetime as _dt
                from db.news_db import NewsDB as _NDB_
                _ndb2 = _NDB_(db_path)
                status = 'ok' if result.returncode == 0 else 'failed'
                error_msg = result.stderr[:200] if result.returncode != 0 else ''
                out = result.stdout or ''
                import re as _re3
                fm = _re3.search(r'总条目[：:]\s*(\d+)', out)
                fetched = int(fm.group(1)) if fm else 0
                source_name = 'RSS' if script == 'fetch_english_news.py' else '平台热搜'
                source_type = 'rss' if script == 'fetch_english_news.py' else 'hotlist'
                _ndb2.log_fetch(source_name, source_type, fetched, 0, status, error_msg, 0, run_type)
            except Exception as _fe:
                logger.warning(f"fetch_logs write failed: {_fe}")
```

- [ ] **Step 2: 修改 scheduler.py 传递 run_type**

在 `news-web/backend/scheduler.py` 中，找到 `trigger_pipeline_manual()` 函数（约 116 行）。需要修改 `run_pipeline()` 调用，增加 `run_type='manual'`。但由于 `run_pipeline` 是在 `_run_pipeline_job` 中调用的，我需要让手动触发时传递不同参数。

最简单的改法：在 `_pipeline_state` 中加一个字段区分手动/调度触发：

```python
# 修改 _pipeline_state 字典（约第 24 行）
_pipeline_state = {
    'running': False,
    'last_run': None,
    'last_status': None,
    'current_step': None,
    'steps': [],
    'run_type': 'scheduled',  # 新增
}
```

修改 `trigger_pipeline_manual()`（约 116 行）：
```python
async def trigger_pipeline_manual():
    """Manually trigger a pipeline run (via API)."""
    global _pipeline_state
    _pipeline_state['run_type'] = 'manual'
    asyncio.create_task(_run_pipeline_job())
    return {'status': 'pipeline_started'}
```

修改 `_run_pipeline_job()` 中的 `run_pipeline()` 调用（约 48 行），传入 run_type：
```python
        success = run_pipeline(
            db_path=config.db_path,
            user_agent=config.user_agent,
            callback=progress_callback,
            run_type=_pipeline_state.get('run_type', 'scheduled'),
        )
```

并在 finally 中重置：
```python
    finally:
        _pipeline_state['running'] = False
        _pipeline_state['run_type'] = 'scheduled'
        _pipeline_state['last_run'] = datetime.now().isoformat(timespec='seconds')
```

- [ ] **Step 3: 验证改动不影响现有功能**

```bash
cd news-web/backend && python -c "
# 仅语法检查，不实际运行 pipeline
import py_compile
py_compile.compile('pipeline/run_all.py', doraise=True)
py_compile.compile('scheduler.py', doraise=True)
print('Syntax OK')
"
```

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/backend/pipeline/run_all.py news-web/backend/scheduler.py
git commit -m "feat: pipeline 抓取步骤后自动写入 fetch_logs

run_all.py 添加 run_type 参数，scheduler.py 手动触发标记为 manual

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `main.py` — 注册 fetch_router

**Files:**
- Modify: `news-web/backend/main.py`

- [ ] **Step 1: 添加导入和注册**

在 `main.py` 的路由注册区域，找到：
```python
from api.hotlists import router as hotlists_router
```

在其后新增一行：
```python
from api.fetch import router as fetch_router
```

在 `app.include_router` 区域，找到：
```python
app.include_router(hotlists_router)
```

在其后新增：
```python
app.include_router(fetch_router)
```

- [ ] **Step 2: 验证 FastAPI 路由已注册**

```bash
cd news-web && python -c "
import os, sys
os.environ['NEWS_WEB_TESTING'] = '1'
sys.path.insert(0, 'backend')
from main import app
routes = [r.path for r in app.routes if '/api/fetch' in str(r.path)]
print('fetch routes:', sorted(routes))
assert '/api/fetch/overview' in str(routes), 'overview missing'
assert '/api/fetch/sources' in str(routes), 'sources missing'
print('All fetch routes registered OK')
"
```

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/backend/main.py
git commit -m "feat: main.py 注册 fetch_router

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 前端 Types — 新增 FetchMonitor 类型

**Files:**
- Modify: `news-web/frontend/src/types/index.ts`

- [ ] **Step 1: 在文件末尾添加类型定义**

```typescript
// ── 数据采集监控 ──────────────────────────────────────

export interface FetchOverview {
  rss: {
    total_sources: number;
    healthy: number;
    degraded: number;
    failing: number;
    last_run: string | null;
    articles_today: number;
  };
  hotlist: {
    total_sources: number;
    healthy: number;
    degraded: number;
    failing: number;
    last_run: string | null;
    articles_today: number;
  };
  cache: {
    total_articles: number;
    cached: number;
    pending: number;
    failed: number;
    cached_pct: number;
  };
}

export interface FetchSource {
  name: string;
  type: 'rss' | 'hotlist' | 'bilibili';
  health: 'healthy' | 'degraded' | 'failing';
  last_fetch: string | null;
  last_status: string;
  last_error: string;
  total_articles: number;
  cached_articles: number;
  failed_articles: number;
  success_rate_5: number;
}

export interface FetchLog {
  id?: number;
  source_name: string;
  source_type: string;
  articles_fetched: number;
  articles_new: number;
  status: string;
  error_msg: string;
  duration_ms: number;
  started_at: string;
  finished_at?: string;
  run_type: string;
}

export interface FetchArticleItem {
  id: number;
  title: string;
  url: string;
  source: string;
  content_status: string;
  local_path: string;
  content_fetched_at: string | null;
  content_lang: string;
  has_translation: boolean;
}

export interface FailedArticle {
  id: number;
  title: string;
  url: string;
  source: string;
  error: string;
  content_fetched_at: string | null;
}

export interface BatchRetryState {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  current: string;
  log: string[];
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd news-web/frontend && npx tsc --noEmit src/types/index.ts
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/frontend/src/types/index.ts
git commit -m "feat: 新增 FetchMonitor 相关 TypeScript 类型

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 前端 API Client — 新增 fetch 端点封装

**Files:**
- Modify: `news-web/frontend/src/api/client.ts`

- [ ] **Step 1: 在 `api` 对象末尾（`getHotlistsTop` 之后，`};` 之前）添加 fetch API**

```typescript
  // ── 数据采集监控 ────────────────────────────────────
  getFetchOverview: () =>
    fetchJSON<import('../types').FetchOverview>('/fetch/overview'),

  getFetchSources: (sourceType?: string) => {
    const qs = sourceType ? `?source_type=${encodeURIComponent(sourceType)}` : '';
    return fetchJSON<{ sources: import('../types').FetchSource[] }>(`/fetch/sources${qs}`);
  },

  getFetchSourceHistory: (name: string, days = 7) =>
    fetchJSON<{ source: string; days: number; history: import('../types').FetchLog[] }>(
      `/fetch/sources/${encodeURIComponent(name)}/history?days=${days}`
    ),

  retryFetchSource: (name: string) =>
    fetchJSON<{ ok: boolean; message: string }>(
      `/fetch/sources/${encodeURIComponent(name)}/retry`, { method: 'POST' }
    ),

  getFetchSourceArticles: (name: string, params: { page?: number; limit?: number; status?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.status) qs.set('status', params.status);
    const query = qs.toString();
    return fetchJSON<{ total: number; page: number; limit: number; source: string; articles: import('../types').FetchArticleItem[] }>(
      `/fetch/sources/${encodeURIComponent(name)}/articles${query ? `?${query}` : ''}`
    );
  },

  retryArticleCache: (id: number) =>
    fetchJSON<{ ok: boolean; message: string }>(`/fetch/articles/${id}/retry-cache`, { method: 'POST' }),

  retryArticlesBatch: (ids: number[]) =>
    fetchJSON<{ ok: boolean; total: number; message: string }>(
      '/fetch/articles/batch-retry', { method: 'POST', body: JSON.stringify({ ids }) }
    ),

  getBatchRetryStatus: () =>
    fetchJSON<import('../types').BatchRetryState>('/fetch/articles/batch-retry/status'),

  getFailedArticles: (page = 1, limit = 50) =>
    fetchJSON<{ total: number; page: number; limit: number; articles: import('../types').FailedArticle[] }>(
      `/fetch/articles/failed?page=${page}&limit=${limit}`
    ),

  getFetchLogs: (limit = 50) =>
    fetchJSON<{ logs: import('../types').FetchLog[] }>(`/fetch/logs?limit=${limit}`),
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd news-web/frontend && npx tsc --noEmit src/api/client.ts
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/frontend/src/api/client.ts
git commit -m "feat: 前端 client.ts 新增数据采集监控 API 封装

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: 新建 `FetchMonitor.tsx` 页面

**Files:**
- Create: `news-web/frontend/src/pages/FetchMonitor.tsx`

- [ ] **Step 1: 创建完整页面组件**

```typescript
import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';
import type { FetchOverview, FetchSource, FetchLog, FailedArticle, FetchArticleItem, BatchRetryState } from '../types';

const emptyOverview: FetchOverview = {
  rss: { total_sources: 0, healthy: 0, degraded: 0, failing: 0, last_run: null, articles_today: 0 },
  hotlist: { total_sources: 0, healthy: 0, degraded: 0, failing: 0, last_run: null, articles_today: 0 },
  cache: { total_articles: 0, cached: 0, pending: 0, failed: 0, cached_pct: 0 },
};

const emptyBatch: BatchRetryState = { running: false, total: 0, done: 0, failed: 0, current: '', log: [] };

// ── 状态徽章 ──────────────────────────────────────────
const healthBadge: Record<string, React.CSSProperties> = {
  healthy: { background: 'rgba(129,199,132,0.15)', color: '#81c784', padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600 },
  degraded: { background: 'rgba(255,183,77,0.15)', color: '#ffb74d', padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600 },
  failing: { background: 'rgba(239,83,80,0.15)', color: '#ef5350', padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600 },
};

const typeLabels: Record<string, string> = { rss: 'RSS', hotlist: '平台热榜', bilibili: 'B站视频' };

const statusStyle: Record<string, React.CSSProperties> = {
  fetched: { background: 'rgba(129,199,132,0.12)', color: '#81c784', padding: '2px 8px', borderRadius: 12, fontSize: 11 },
  translated: { background: 'rgba(0,212,255,0.12)', color: '#00d4ff', padding: '2px 8px', borderRadius: 12, fontSize: 11 },
  pending: { background: 'rgba(255,183,77,0.12)', color: '#ffb74d', padding: '2px 8px', borderRadius: 12, fontSize: 11 },
  failed: { background: 'rgba(239,83,80,0.12)', color: '#ef5350', padding: '2px 8px', borderRadius: 12, fontSize: 11 },
};

export default function FetchMonitor() {
  const [overview, setOverview] = useState<FetchOverview>(emptyOverview);
  const [sources, setSources] = useState<FetchSource[]>([]);
  const [logs, setLogs] = useState<FetchLog[]>([]);
  const [loading, setLoading] = useState(true);

  // 源列表状态
  const [sourceFilter, setSourceFilter] = useState('');
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const [sourceHistory, setSourceHistory] = useState<FetchLog[]>([]);
  const [sourceArticles, setSourceArticles] = useState<FetchArticleItem[]>([]);
  const [sourceArticlesTotal, setSourceArticlesTotal] = useState(0);
  const [sourceArticlesPage, setSourceArticlesPage] = useState(1);
  const [sourceArticlesFilter, setSourceArticlesFilter] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [retryingSource, setRetryingSource] = useState('');

  // 失败文章
  const [failedArticles, setFailedArticles] = useState<FailedArticle[]>([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [failedPage, setFailedPage] = useState(1);

  // 批量重试
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchState, setBatchState] = useState<BatchRetryState>(emptyBatch);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const batchTimer = useRef<ReturnType<typeof setInterval>>();

  const pollBatch = useCallback(async () => {
    try {
      const s = await api.getBatchRetryStatus();
      setBatchState(s);
      if (!s.running) { clearInterval(batchTimer.current); refreshAll(); }
    } catch { clearInterval(batchTimer.current); }
  }, []);

  const refreshAll = useCallback(() => {
    Promise.all([
      api.getFetchOverview().then(setOverview).catch(() => {}),
      api.getFetchSources(sourceFilter).then(r => setSources(r.sources)).catch(() => {}),
      api.getFetchLogs(50).then(r => setLogs(r.logs)).catch(() => {}),
      api.getFailedArticles(1, 50).then(r => { setFailedArticles(r.articles); setFailedTotal(r.total); setFailedPage(1); }).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, [sourceFilter]);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  const handleExpand = async (name: string) => {
    if (expandedSource === name) { setExpandedSource(null); return; }
    setExpandedSource(name);
    setHistoryLoading(true);
    try {
      const h = await api.getFetchSourceHistory(name, 7);
      setSourceHistory(h.history);
    } catch { setSourceHistory([]); }
    finally { setHistoryLoading(false); }
  };

  const handleViewArticles = async (name: string, status?: string, page = 1) => {
    try {
      const r = await api.getFetchSourceArticles(name, { page, limit: 30, status: status || '' });
      setSourceArticles(r.articles);
      setSourceArticlesTotal(r.total);
      setSourceArticlesPage(page);
      setSourceArticlesFilter(status || '');
    } catch { /* ignore */ }
  };

  const handleRetrySource = async (name: string) => {
    setRetryingSource(name);
    try {
      await api.retryFetchSource(name);
      setTimeout(refreshAll, 3000);
    } catch { /* ignore */ }
    finally { setRetryingSource(''); }
  };

  const handleRetryArticle = async (id: number) => {
    await api.retryArticleCache(id);
    setTimeout(refreshAll, 3000);
  };

  const handleBatchRetry = async () => {
    if (selectedIds.size === 0) return;
    setBatchSubmitting(true);
    try {
      const res = await api.retryArticlesBatch(Array.from(selectedIds));
      if (res.ok) {
        setSelectedIds(new Set());
        setBatchState({ running: true, total: res.total, done: 0, failed: 0, current: '', log: [] });
        batchTimer.current = setInterval(pollBatch, 2000);
      }
    } catch { /* ignore */ }
    finally { setBatchSubmitting(false); }
  };

  const toggleSelect = (id: number) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    if (next.size > 50) return; // 限制 50
    setSelectedIds(next);
  };

  const toggleSelectAll = (ids: number[]) => {
    if (selectedIds.size === Math.min(ids.length, 50)) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(ids.slice(0, 50)));
    }
  };

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-secondary)' }}>加载数据采集状态...</div>;
  }

  return (
    <div style={{ padding: 24, overflow: 'auto', flex: 1 }}>
      <h2 style={{ marginBottom: 20 }}>📡 数据采集</h2>

      {/* ═══ 区块 1: 总览栏 ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
        <StatCard icon="fa-rss" label="RSS 源" value={`${overview.rss.healthy} 正常 / ${overview.rss.degraded + overview.rss.failing} 异常`} color="var(--accent)" />
        <StatCard icon="fa-fire" label="平台热榜" value={`${overview.hotlist.healthy} 正常`} color="var(--accent-orange)" />
        <StatCard icon="fa-database" label="缓存覆盖率" value={`${overview.cache.cached_pct}%`} color="var(--accent-tertiary)" />
        <StatCard icon="fa-file-arrow-down" label="今日新增" value={`${overview.rss.articles_today + overview.hotlist.articles_today} 篇`} color="var(--accent-green)" />
        <StatCard icon="fa-clock" label="待下载" value={`${overview.cache.pending} 篇`} color="#ffb74d" />
        <StatCard icon="fa-triangle-exclamation" label="下载失败" value={`${overview.cache.failed} 篇`} color="#ef5350" />
      </div>

      {/* ═══ 区块 2: 源列表 ═══ */}
      <Section title="📋 数据源">
        <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
          {['', 'rss', 'hotlist', 'bilibili'].map(t => (
            <button key={t} onClick={() => setSourceFilter(t)}
              style={{ ...filterBtn, background: sourceFilter === t ? 'var(--accent)' : 'var(--bg-card)', color: sourceFilter === t ? '#000' : 'var(--text-secondary)' }}>
              {t === '' ? '全部' : typeLabels[t] || t}
            </button>
          ))}
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={tableStyle}>
            <thead><tr>
              <th style={thStyle}>源名称</th><th style={thStyle}>类型</th><th style={thStyle}>最近抓取</th>
              <th style={thStyle}>状态</th><th style={thStyle}>成功率</th><th style={thStyle}>文章(缓存/总计)</th>
              <th style={thStyle}>操作</th>
            </tr></thead>
            <tbody>
              {sources.map(s => (
                <>
                  <tr key={s.name} style={trStyle(s.health === 'failing' ? 'rgba(239,83,80,0.04)' : 'transparent')}>
                    <td style={tdStyle}>
                      <button onClick={() => handleExpand(s.name)} style={{ ...expandBtn, fontWeight: 600 }}>
                        {expandedSource === s.name ? '▼' : '▶'} {s.name}
                      </button>
                    </td>
                    <td style={tdStyle}>{typeLabels[s.type] || s.type}</td>
                    <td style={tdStyle}>{s.last_fetch ? formatTime(s.last_fetch) : '—'}</td>
                    <td style={tdStyle}><span style={healthBadge[s.health]}>{s.health === 'healthy' ? '正常' : s.health === 'degraded' ? '降级' : '异常'}</span></td>
                    <td style={tdStyle}>{(s.success_rate_5 * 100).toFixed(0)}%</td>
                    <td style={tdStyle}>{s.cached_articles}/{s.total_articles}</td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button onClick={() => handleViewArticles(s.name)} style={smallBtn}>查看</button>
                        <button onClick={() => handleRetrySource(s.name)} disabled={retryingSource === s.name} style={smallBtn}>
                          {retryingSource === s.name ? '⏳' : '重抓'}
                        </button>
                      </div>
                    </td>
                  </tr>
                  {/* 展开行 */}
                  {expandedSource === s.name && (
                    <tr><td colSpan={7} style={{ padding: '8px 16px', background: 'var(--bg-primary)' }}>
                      {historyLoading ? <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>加载中...</span> : (
                        <div style={{ fontSize: 12 }}>
                          <div style={{ marginBottom: 8, fontWeight: 600, color: 'var(--text-secondary)' }}>最近抓取历史 (7 天)</div>
                          {sourceHistory.length === 0 ? (
                            <span style={{ color: 'var(--text-muted)' }}>暂无记录 — 该源可能尚未被系统调度抓取</span>
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 140, overflowY: 'auto' }}>
                              {sourceHistory.map((h, i) => (
                                <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 11, fontFamily: 'monospace' }}>
                                  <span style={{ color: 'var(--text-muted)', minWidth: 130 }}>{h.started_at?.replace('T', ' ').substring(0, 19)}</span>
                                  <span style={{ color: h.status === 'ok' ? '#81c784' : '#ef5350', minWidth: 20 }}>{h.status === 'ok' ? '✅' : '❌'}</span>
                                  <span>{h.articles_fetched} 条</span>
                                  <span style={{ color: 'var(--text-muted)' }}>+{h.articles_new} 新增</span>
                                  <span style={{ color: 'var(--text-muted)' }}>{h.run_type === 'manual' ? '手动' : '调度'}</span>
                                  {h.error_msg && <span style={{ color: '#ef5350' }}>{h.error_msg.substring(0, 60)}</span>}
                                </div>
                              ))}
                            </div>
                          )}
                          {/* 该源文章列表内嵌展开 */}
                          <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                              {['', 'pending', 'fetched', 'failed', 'translated'].map(st => (
                                <button key={st} onClick={() => handleViewArticles(s.name, st || undefined)}
                                  style={{ ...filterBtn, background: sourceArticlesFilter === st ? 'var(--accent-tertiary)' : 'var(--bg-card)', color: sourceArticlesFilter === st ? '#000' : 'var(--text-muted)', fontSize: 11 }}>
                                  {st === '' ? '全部' : st === 'pending' ? '待下载' : st === 'fetched' ? '已缓存' : st === 'failed' ? '失败' : '已翻译'}
                                </button>
                              ))}
                            </div>
                            {sourceArticles.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 200, overflowY: 'auto' }}>
                                {sourceArticles.map(a => (
                                  <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, padding: '3px 0' }}>
                                    <span style={{ minWidth: 36, color: 'var(--text-muted)' }}>#{a.id}</span>
                                    <a href={`/articles/${a.id}`} target="_blank" style={{ flex: 1, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: 'none' }}
                                      onMouseEnter={e => (e.currentTarget.style.color = 'var(--accent)')}
                                      onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-secondary)')}>
                                      {a.title}
                                    </a>
                                    <span style={statusStyle[a.content_status] || statusStyle.pending}>{a.content_status}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {sourceArticlesTotal > 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>共 {sourceArticlesTotal} 篇 · 显示前 30 篇</div>}
                          </div>
                        </div>
                      )}
                    </td></tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ═══ 区块 3: 失败文章列表（含批量操作） ═══ */}
      <Section title={`⚠️ 下载失败的文章 (${failedTotal})`}>
        {batchState.running && (
          <div style={{ marginBottom: 12, padding: '8px 14px', background: 'rgba(0,212,255,0.08)', borderRadius: 8, border: '1px solid rgba(0,212,255,0.2)', fontSize: 12 }}>
            <i className="fas fa-spinner fa-spin" /> 批量重试中: {batchState.done}/{batchState.total} · {batchState.current}
          </div>
        )}
        <div style={{ marginBottom: 12, display: 'flex', gap: 10, alignItems: 'center' }}>
          <button onClick={() => toggleSelectAll(failedArticles.map(a => a.id))} style={smallBtn}>
            {selectedIds.size > 0 ? `取消全选 (${selectedIds.size})` : '全选'}
          </button>
          <button onClick={handleBatchRetry} disabled={selectedIds.size === 0 || batchSubmitting || batchState.running}
            style={{ ...smallBtn, background: selectedIds.size > 0 ? 'var(--accent)' : 'var(--bg-card)', color: selectedIds.size > 0 ? '#000' : 'var(--text-muted)' }}>
            {batchSubmitting ? '提交中...' : `批量重试 (${selectedIds.size} 篇)`}
          </button>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>最多 50 篇</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={tableStyle}>
            <thead><tr>
              <th style={thStyle}><input type="checkbox" onChange={() => toggleSelectAll(failedArticles.map(a => a.id))}
                checked={selectedIds.size > 0 && selectedIds.size === Math.min(failedArticles.length, 50)} /></th>
              <th style={thStyle}>ID</th><th style={thStyle}>标题</th><th style={thStyle}>来源</th>
              <th style={thStyle}>错误</th><th style={thStyle}>最近尝试</th><th style={thStyle}>操作</th>
            </tr></thead>
            <tbody>
              {failedArticles.map(a => (
                <tr key={a.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={tdStyle}><input type="checkbox" checked={selectedIds.has(a.id)} onChange={() => toggleSelect(a.id)} /></td>
                  <td style={tdStyle}>{a.id}</td>
                  <td style={{ ...tdStyle, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</td>
                  <td style={tdStyle}>{a.source}</td>
                  <td style={{ ...tdStyle, color: '#ef5350' }}>{a.error}</td>
                  <td style={tdStyle}>{a.content_fetched_at ? formatTime(a.content_fetched_at) : '—'}</td>
                  <td style={tdStyle}>
                    <button onClick={() => handleRetryArticle(a.id)} style={smallBtn}>重试</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {failedTotal > 50 && (
          <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
            <button onClick={() => { setFailedPage(failedPage - 1); api.getFailedArticles(failedPage - 1, 50).then(r => setFailedArticles(r.articles)).catch(() => {}); }}
              disabled={failedPage <= 1} style={smallBtn}>上一页</button>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>第 {failedPage}/{Math.ceil(failedTotal / 50)} 页</span>
            <button onClick={() => { setFailedPage(failedPage + 1); api.getFailedArticles(failedPage + 1, 50).then(r => setFailedArticles(r.articles)).catch(() => {}); }}
              disabled={failedPage >= Math.ceil(failedTotal / 50)} style={smallBtn}>下一页</button>
          </div>
        )}
      </Section>

      {/* ═══ 区块 4: 最近抓取日志 ═══ */}
      <Section title="📜 最近抓取日志">
        <div style={{ background: '#0d1117', borderRadius: 6, padding: '8px 10px', maxHeight: 240, overflowY: 'auto', fontFamily: 'Consolas, "Courier New", monospace', fontSize: 10, lineHeight: 1.8, border: '1px solid var(--border)' }}>
          {logs.map((l, i) => {
            const icon = l.status === 'ok' ? '✅' : l.status === 'partial' ? '⚠️' : '❌';
            const color = l.status === 'ok' ? '#81c784' : l.status === 'partial' ? '#ffb74d' : '#ef5350';
            return (
              <div key={i} style={{ color }}>
                [{formatTime(l.started_at)}] {l.source_name} {icon} {l.articles_fetched} 条, +{l.articles_new} 新增
                {l.duration_ms > 0 ? ` · ${(l.duration_ms / 1000).toFixed(1)}s` : ''}
                {l.run_type === 'manual' ? ' [手动]' : ''}
                {l.error_msg ? ` — ${l.error_msg}` : ''}
              </div>
            );
          })}
          {logs.length === 0 && <div style={{ color: 'var(--text-muted)' }}>暂无抓取记录 — 等待首次调度运行</div>}
        </div>
      </Section>
    </div>
  );
}

// ── 子组件 ─────────────────────────────────────────────

function StatCard({ icon, label, value, color }: { icon: string; label: string; value: string; color: string }) {
  return (
    <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: '14px 18px', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
      <i className={`fas ${icon}`} style={{ color, fontSize: 20 }} />
      <div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
        <div style={{ fontSize: 16, fontWeight: 700, color }}>{value}</div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h3 style={{ fontSize: 14, marginBottom: 10, color: 'var(--text-secondary)' }}>{title}</h3>
      {children}
    </div>
  );
}

function formatTime(iso: string) {
  if (!iso) return '—';
  try {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso.substring(0, 19).replace('T', ' ');
  }
}

// ── 样式 ───────────────────────────────────────────────
const tableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 13 };
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap' };
const tdStyle: React.CSSProperties = { padding: '6px 10px', borderBottom: '1px solid var(--border)', fontSize: 12 };
const trStyle = (bg: string): React.CSSProperties => ({ background: bg, borderBottom: '1px solid var(--border)' });
const filterBtn: React.CSSProperties = { border: '1px solid var(--border)', borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer' };
const smallBtn: React.CSSProperties = { background: 'var(--bg-card)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 5, padding: '3px 10px', fontSize: 11, cursor: 'pointer' };
const expandBtn: React.CSSProperties = { background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 12, padding: 0 };
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd news-web/frontend && npx tsc --noEmit src/pages/FetchMonitor.tsx
```

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/frontend/src/pages/FetchMonitor.tsx
git commit -m "feat: 新建 FetchMonitor 页面 — 数据采集 4 区块监控

总览/源列表(可展开)/缓存文章(批量重试)/抓取日志

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: 前端路由 + 导航入口

**Files:**
- Modify: `news-web/frontend/src/App.tsx`
- Modify: `news-web/frontend/src/components/NavSidebar.tsx`

- [ ] **Step 1: 在 App.tsx 中添加路由导入和 Route**

在 `App.tsx` 顶部导入区域找到：
```typescript
import HotTrends from './pages/HotTrends';
```

在下方加入：
```typescript
import FetchMonitor from './pages/FetchMonitor';
```

在 Routes 区域，找到 `HotTrends` 路由（`/hotlists`），在其后添加：
```tsx
          <Route path="/fetch" element={<FetchMonitor />} />
```

- [ ] **Step 2: 在 NavSidebar.tsx 中添加导航项**

找到 `ALL_ITEMS` 数组（约第 5 行），在 HotTrends 项之后添加：
```typescript
  { path: '/fetch', label: '数据采集', icon: 'fa-satellite-dish', adminOnly: false },
```

- [ ] **Step 3: 验证前端构建**

```bash
cd news-web/frontend && npm run build
```

Expected: Build succeeds without errors.

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/frontend/src/App.tsx news-web/frontend/src/components/NavSidebar.tsx
git commit -m "feat: 注册 /fetch 路由 + 导航栏添加数据采集入口

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: 后端测试 — 新增 8 个 fetch API 用例

**Files:**
- Modify: `news-web/tests/backend/test_api.py`

- [ ] **Step 1: 添加 8 个测试函数**

在 `test_api.py` 文件末尾（`test_settings` 函数之后）添加：

```python
# ══════════════════════════════════════════════════════════════
# 数据采集监控 API 测试 (api/fetch.py)
# ══════════════════════════════════════════════════════════════

def test_fetch_overview(client, news_db):
    """overview 返回正确四级统计结构 + 缓存维度"""
    # 先写入一条 fetch_log 以保证有数据
    news_db.log_fetch('Guru3D', 'rss', 10, 3, 'ok', '', 1200, 'scheduled')
    resp = client.get("/api/fetch/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "rss" in data
    assert "hotlist" in data
    assert "cache" in data
    assert isinstance(data["rss"]["healthy"], int)
    assert isinstance(data["cache"]["cached_pct"], float)
    assert data["rss"]["articles_today"] >= 0


def test_fetch_sources(client, news_db):
    """sources 列表返回所有源及健康状态"""
    resp = client.get("/api/fetch/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert isinstance(data["sources"], list)
    # 已有种子数据，至少有一个源
    assert len(data["sources"]) >= 1
    src = data["sources"][0]
    assert "name" in src
    assert "type" in src
    assert "health" in src
    assert src["health"] in ("healthy", "degraded", "failing")


def test_fetch_source_history(client, news_db):
    """单源历史按 days 参数正确筛选"""
    # 注入历史记录
    news_db.log_fetch('Guru3D', 'rss', 5, 2, 'ok', '', 1000, 'scheduled')
    news_db.log_fetch('Guru3D', 'rss', 3, 0, 'failed', 'Timeout', 8000, 'scheduled')
    resp = client.get("/api/fetch/sources/Guru3D/history?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "Guru3D"
    assert len(data["history"]) >= 2


def test_fetch_source_retry_unknown(client, news_db):
    """重试不存在的源应返回错误"""
    resp = client.post("/api/fetch/sources/NonExistentSource/retry")
    # 404 或返回错误 JSON
    assert resp.status_code in (404, 200)
    if resp.status_code == 200:
        assert resp.json().get("ok") is False


def test_fetch_source_articles(client, news_db):
    """源文章列表筛选 + 分页正确"""
    resp = client.get("/api/fetch/sources/Guru3D/articles?page=1&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "articles" in data
    assert data["source"] == "Guru3D"
    assert data["total"] >= 1
    assert len(data["articles"]) >= 1
    art = data["articles"][0]
    assert "content_status" in art


def test_fetch_retry_article_cache(client, news_db):
    """单篇缓存重试返回 ok"""
    # 使用种子文章 ID 1
    resp = client.post("/api/fetch/articles/1/retry-cache")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_fetch_batch_retry_limit(client, news_db):
    """批量重试超过 50 篇应返回错误"""
    resp = client.post("/api/fetch/articles/batch-retry", json={"ids": list(range(1, 60))})
    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data or "error" in data


def test_fetch_failed_articles(client, news_db):
    """失败文章列表分页正确"""
    resp = client.get("/api/fetch/articles/failed?page=1&limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert "articles" in data
    assert "total" in data
    assert "page" in data
```

- [ ] **Step 2: 运行测试验证**

```bash
cd news-web && python -m pytest tests/backend/test_api.py -v -k "fetch" --tb=short
```

Expected: 8 passed

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/PegionFish/Desktop/LapTalk_NewsAggregationTool"
git add news-web/tests/backend/test_api.py
git commit -m "test: 新增 fetch API 监控 8 个测试用例

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 最终验证

- [ ] 运行全部后端测试: `cd news-web && python -m pytest tests/backend/test_api.py -v`
- [ ] 构建前端: `cd news-web/frontend && npm run build`
- [ ] 启动服务确认 `/fetch` 页面可访问: `bash start_platform.sh restart`

**总计:** 10 个 Task，约 15 次 commit。
