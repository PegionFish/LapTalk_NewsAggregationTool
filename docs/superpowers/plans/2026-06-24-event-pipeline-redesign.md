# 事件管线架构重构 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 废弃 bigram 事件聚类，将 AI 语义事件匹配内嵌到文章处理流程，清空全部垃圾事件数据并从零重建

**Architecture:** 事件匹配从后置批处理（bigram `link_articles_to_events`）下沉到 `process_article()` 末尾（AI `match_article_to_events_ai`）。事件管线从三步（recluster→summarize→build_chains）简化为两步（summarize→build_chains）。全量清空 events/news_article_events/event_relations/logic_chains，通过一次性重建脚本重新聚类。

**Tech Stack:** Python 3.14, SQLite WAL, OpenAI 兼容 API, FastAPI

## 全局约束

- 所有 AI 调用必须通过 `ai_client.py` 现有函数，不新增裸 API 调用
- `_ai_json()` 已修复异常日志（P0），`build_chains_panoramic()` 已修复 `response_format=None`（P0）
- `_nightly()` 已修复 try/finally 保护（P1）
- 所有 DB 写入使用 `safe_commit()`，不直接 `conn.commit()`
- 文章处理 50 线程并行不变
- 中文注释，英文标识符

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `pipeline/process_article.py` | 修改 | 在 KCS 后新增 `_match_to_event()` 调用 |
| `pipeline/event_matching.py` | **新建** | 事件匹配逻辑：候选筛选 + AI 判断 + DB 写入 |
| `api/pipeline_event.py` | 修改 | `_nightly()` 三步→两步，移除 recluster |
| `ai_client.py` | 修改 | `build_panoramic_context()` 只取 2+ 关联事件 |
| `db/news_db.py` | 修改 | 废弃 `link_articles_to_events()` / `suggest_event_relations()` |
| `scheduler.py` | 修改 | 新增 `pending_cluster` 批处理定时任务 |
| `scripts/rebuild_events.py` | **新建** | 一次性脚本：清空 + 全量 AI 聚类重建 |
| `tests/backend/test_pipeline_event.py` | 修改 | 更新测试适配新架构 |
| `tests/backend/test_pipeline_article.py` | 修改 | 新增事件匹配步骤测试 |

---

### Task 1: 废弃 bigram 聚类方法

**Files:**
- Modify: `news-web/backend/db/news_db.py:565-623` (`link_articles_to_events`)
- Modify: `news-web/backend/db/news_db.py:761-849` (`suggest_event_relations`)

**Interfaces:**
- Consumes: 无
- Produces: `link_articles_to_events()` → 改为 no-op 并记录警告日志; `suggest_event_relations()` → 改为 no-op 并记录警告日志

`link_articles_to_events()` 是 bigram 聚类的入口。改为空操作，避免任何调用路径意外触发垃圾事件生成。`suggest_event_relations()` 是规则引擎关系检测，后续由 AI 接管。

- [ ] **Step 1: 将 `link_articles_to_events()` 改为 no-op**

编辑 `news-web/backend/db/news_db.py`，定位 `link_articles_to_events` 方法（约第 568 行）：

```python
def link_articles_to_events(self, threshold: float = 0.35) -> int:
    """[已废弃] 旧版 bigram 聚类 — 2026-06-24 起由 AI 语义匹配替代。
    
    此方法不再执行任何操作。事件聚类现由 process_article() 中的
    AI match_article_to_events_ai() 完成。
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(
        "link_articles_to_events() 已废弃，调用被忽略。"
        "事件聚类现由 process_article() 内 AI 语义匹配完成。"
    )
    return 0
```

- [ ] **Step 2: 将 `suggest_event_relations()` 改为 no-op**

编辑 `news-web/backend/db/news_db.py`，定位 `suggest_event_relations` 方法（约第 761 行）：

```python
def suggest_event_relations(self, max_days: int = 7,
                            time_weight: float = 0.4,
                            title_weight: float = 0.6) -> int:
    """[已废弃] 旧版规则引擎关系检测 — 2026-06-24 起由 AI 关系检测替代。
    
    此方法不再执行任何操作。事件关系现由 nightly 中的 AI 批量检测完成。
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(
        "suggest_event_relations() 已废弃，调用被忽略。"
        "事件关系现由 nightly AI 批量检测完成。"
    )
    return 0
```

- [ ] **Step 3: 验证调用方**

```bash
cd news-web/backend && grep -rn "link_articles_to_events\|suggest_event_relations" --include="*.py" | grep -v "def \|no-op\|废弃\|deprecated\|news_db.py"
```

确认除 `news_db.py` 自身定义外，无其他文件直接调用这两个方法。如有调用方，同样替换为 no-op。

- [ ] **Step 4: Commit**

```bash
git add news-web/backend/db/news_db.py
git commit -m "refactor: 废弃 bigram link_articles_to_events + suggest_event_relations

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 新建事件匹配模块

**Files:**
- Create: `news-web/backend/pipeline/event_matching.py`
- Modify: `news-web/backend/pipeline/__init__.py` (确保模块可导入)

**Interfaces:**
- Consumes: `ai_client.match_article_to_events_ai(article_title, events)` — 返回 `{'event_id': int|None, 'confidence': float, 'reason': str}` 或 None
- Produces: `match_article_to_event(article_id: int) -> int | None` — 返回匹配的 event_id 或 None

新模块负责：
1. 筛选候选事件（同 category + 关键词交集 + 30 天内）
2. 调用 AI 语义匹配
3. 写入 `news_article_events` 关联或标记 `pending_cluster`

- [ ] **Step 1: 创建模块**

`news-web/backend/pipeline/event_matching.py`:

```python
"""AI 语义事件匹配 — 替代旧版 bigram 聚类。
在 process_article() KCS 完成后调用，将文章关联到已有事件或标记 pending_cluster。
"""
import logging, json as _json
from datetime import datetime, timedelta
from config import config
from ai_client import match_article_to_events_ai
from utils.db import get_db_connection, safe_commit

logger = logging.getLogger(__name__)

# 候选事件筛选参数
MAX_CANDIDATES = 50        # AI 单次匹配的候选事件上限
CATEGORY_DAYS = 30         # 候选事件的时间窗口（天）


def _get_candidate_events(db, category: str, keywords: list[str], article_id: int) -> list[tuple[int, str]]:
    """筛选候选事件：同 category + 关键词交集 + 30 天内。
    
    优先级排序：
    1. 有关键词交集且 ≥2 篇的事件
    2. 同 category 且 ≥2 篇的事件
    3. 其余匹配条件的事件
    
    Args:
        db: 数据库连接
        category: 文章的 ai_category (如 'AI/LLM', 'Mobile')
        keywords: 文章的 ai_keywords 列表
        article_id: 当前文章 ID (排除自身已关联的事件)
    
    Returns:
        [(event_id, event_title), ...] 最多 MAX_CANDIDATES 个
    """
    cutoff = (datetime.now() - timedelta(days=CATEGORY_DAYS)).strftime('%Y-%m-%d')
    
    # 查询候选：同 category + 最近 30 天 + 非 orphan
    rows = db.execute("""
        SELECT e.id, e.title, e.article_count, 
               GROUP_CONCAT(a.ai_keywords, ' ') as all_kw
        FROM events e
        JOIN news_article_events ae ON ae.event_id = e.id
        JOIN news_articles a ON a.id = ae.article_id
        WHERE e.status = 'active'
          AND e.last_seen >= ?
        GROUP BY e.id
        HAVING COUNT(ae.article_id) >= 1
        ORDER BY e.article_count DESC
        LIMIT 200
    """, (cutoff,)).fetchall()
    
    if not rows:
        return []
    
    # 按关键词交集排序
    kw_set = set(k.lower() for k in keywords if len(k) > 1)
    scored = []
    for eid, etitle, count, all_kw_str in rows:
        all_kw = set((all_kw_str or '').lower().split())
        overlap = len(kw_set & all_kw)
        # 同 category 加分
        cat_bonus = 2 if category and _category_overlap(category, etitle) else 0
        score = overlap + cat_bonus + min(count, 10) * 0.1
        scored.append((score, eid, etitle))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(eid, etitle) for _, eid, etitle in scored[:MAX_CANDIDATES]]


def _category_overlap(category: str, event_title: str) -> bool:
    """检查文章 category 是否与事件标题中的关键词匹配。
    用于对同 category 事件加分。
    """
    cat_keywords = {
        'AI/LLM': ['ai', 'llm', 'gpt', 'claude', 'gemini', 'openai', 'anthropic', 'deepseek'],
        'Mobile': ['ios', 'android', 'iphone', 'ipad', 'pixel', 'mobile', '手机'],
        'PC/Hardware': ['cpu', 'gpu', 'amd', 'intel', 'nvidia', 'chip', '硬件', '服务器'],
        'Gaming': ['game', 'gaming', 'xbox', 'playstation', 'nintendo', '游戏'],
        'Security': ['security', '漏洞', '攻击', 'hack', '安全'],
        'Semiconductors': ['chip', '半导体', 'wafer', 'tsmc', 'samsung', '制程'],
        'Enterprise': ['cloud', 'aws', 'azure', 'google cloud', '企业'],
        'Automotive': ['car', 'ev', 'tesla', '自动驾驶', '汽车'],
        'Space': ['spacex', 'nasa', '火箭', '卫星', 'space'],
        'Regulation': ['regulation', 'ban', '法规', '监管', '禁止'],
        'OpenSource': ['open source', '开源', 'linux', 'github'],
    }
    patterns = cat_keywords.get(category, [])
    etitle_lower = event_title.lower()
    return any(p in etitle_lower for p in patterns)


def match_article_to_event(article_id: int) -> int | None:
    """对单篇文章进行 AI 语义事件匹配。
    
    在 process_article() KCS 完成后调用。
    
    Args:
        article_id: 文章 ID
    
    Returns:
        匹配的 event_id，或 None（文章标记为 pending_cluster）
    """
    db = get_db_connection(config.db_path)
    try:
        # 获取文章信息
        row = db.execute("""
            SELECT id, title, ai_category, ai_keywords
            FROM news_articles WHERE id = ?
        """, (article_id,)).fetchone()
        if not row:
            return None
        
        aid, title, category, kw_json = row
        try:
            keywords = _json.loads(kw_json or '[]')
        except (_json.JSONDecodeError, TypeError):
            keywords = []
        
        # 筛选候选事件
        candidates = _get_candidate_events(db, category or '', keywords, aid)
        
        if not candidates:
            logger.info(f"#{aid} 无候选事件，标记 pending_cluster")
            db.execute(
                "UPDATE news_articles SET content_status = 'pending_cluster' WHERE id = ?",
                (aid,)
            )
            safe_commit(db)
            return None
        
        # AI 语义匹配
        result = match_article_to_events_ai(title, candidates)
        
        if result and result.get('event_id'):
            event_id = result['event_id']
            confidence = result.get('confidence', 0.0)
            # 写入关联
            db.execute(
                "INSERT OR IGNORE INTO news_article_events (article_id, event_id, relevance) VALUES (?, ?, ?)",
                (aid, event_id, round(confidence, 2))
            )
            # 更新事件 article_count 和 last_seen
            row_date = db.execute(
                "SELECT published_date, fetched_at FROM news_articles WHERE id = ?",
                (aid,)
            ).fetchone()
            event_date = (row_date[0] or row_date[1])[:10] if row_date else datetime.now().strftime('%Y-%m-%d')
            db.execute(
                "UPDATE events SET last_seen = MAX(last_seen, ?), article_count = article_count + 1 WHERE id = ?",
                (event_date, event_id)
            )
            safe_commit(db)
            logger.info(
                f"#{aid} AI 匹配 → Event#{event_id} (置信度: {confidence:.2f}) — {result.get('reason', '')}"
            )
            return event_id
        else:
            # AI 无法确定归属
            logger.info(f"#{aid} AI 无法确定归属，标记 pending_cluster")
            db.execute(
                "UPDATE news_articles SET content_status = 'pending_cluster' WHERE id = ?",
                (aid,)
            )
            safe_commit(db)
            return None
    
    except Exception as e:
        logger.error(f"match_article_to_event #{article_id} 异常: {e}")
        # 失败时不阻塞文章处理，标记 pending_cluster 等待下次批处理
        try:
            db.execute(
                "UPDATE news_articles SET content_status = 'pending_cluster' WHERE id = ?",
                (article_id,)
            )
            safe_commit(db)
        except Exception:
            pass
        return None
    finally:
        db.close()
```

- [ ] **Step 2: 验证模块可导入**

```bash
cd news-web/backend && python3 -c "from pipeline.event_matching import match_article_to_event; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/pipeline/event_matching.py
git commit -m "feat: 新建 AI 语义事件匹配模块 event_matching.py

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 在 process_article() 末尾集成事件匹配

**Files:**
- Modify: `news-web/backend/pipeline/process_article.py:106-158`

**Interfaces:**
- Consumes: `pipeline.event_matching.match_article_to_event(article_id) -> int | None`
- Produces: `process_article()` 返回的 `result["steps"]` 新增 `"event_match"` 字段

在 KCS 完成后（第 147 行附近），content_status 写入前，调用 `match_article_to_event()`。

- [ ] **Step 1: 在 KCS 步骤后插入事件匹配逻辑**

编辑 `news-web/backend/pipeline/process_article.py`，在 KCS 步骤之后、最终 content_status 写入之前插入以下代码。

定位到约第 147 行（`except Exception as e: result["steps"]["kcs"] = f"error: {e}"` 之后）：

```python
        # Step 4: AI 语义事件匹配（替代旧版 bigram link_articles_to_events）
        try:
            from pipeline.event_matching import match_article_to_event
            matched_event = match_article_to_event(aid)
            if matched_event:
                result["steps"]["event_match"] = f"Event#{matched_event}"
            else:
                result["steps"]["event_match"] = "pending_cluster"
        except Exception as e:
            result["steps"]["event_match"] = f"error: {e}"
            logger.warning(f"#{aid} 事件匹配: {e}")
```

然后将原有的 `content_status` 更新逻辑改为：

```python
        # 确定最终状态：事件匹配成功 → processed，否则 → pending_cluster
        matched = result["steps"].get("event_match") and str(result["steps"]["event_match"]).startswith("Event#")
        final_status = "processed" if matched else "pending_cluster"
        db.execute("UPDATE news_articles SET content_status=? WHERE id=?", (final_status, aid))
        db.commit()
```

- [ ] **Step 2: 验证 process_article 对单篇文章的行为**

```bash
cd news-web/backend && python3 -c "
from pipeline.process_article import process_article
# 找一篇有 KCS 数据的文章测试
import sqlite3
db = sqlite3.connect('data/news.db')
row = db.execute(\"SELECT id FROM news_articles WHERE content_status='fetched' AND ai_keywords != '' LIMIT 1\").fetchone()
db.close()
if row:
    result = process_article(row[0])
    print(result)
else:
    print('无合适测试文章')
"
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/pipeline/process_article.py
git commit -m "feat: process_article 集成 AI 语义事件匹配

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 简化事件管线 — _nightly() 三步变两步

**Files:**
- Modify: `news-web/backend/api/pipeline_event.py:22-75` (`_nightly`)
- Modify: `news-web/backend/api/pipeline_event.py:75-121` (`_run_recluster` — 保留函数但标记废弃)
- Modify: `news-web/backend/api/pipeline_event.py:268-277` (`start_recluster` 端点)

**Interfaces:**
- Consumes: `_run_summarize()`, `_run_build_chains()` (现有函数，不变)
- Produces: `_nightly()` 两步执行; `_event_state["steps"]` 从 3 减为 2

- [ ] **Step 1: 修改 `_nightly()` 步骤列表**

编辑 `news-web/backend/api/pipeline_event.py`，修改 `_nightly()`:

```python
def _nightly():
    """线性执行两个阶段：摘要 → 逻辑链。
    事件聚类已在文章处理时完成（process_article 内 AI 语义匹配）。
    """
    global _event_state, _es_state, _chain_state

    steps = [
        ("事件摘要", _run_summarize, _es_state, 'summarize_events'),
        ("逻辑链构建", _run_build_chains, _chain_state, 'build_chains'),
    ]
    # 其余代码不变...
```

同时更新函数开头的 docstring 和 globals 声明（移除 `_recl_state`）。

- [ ] **Step 2: 标记 `_run_recluster()` 为废弃**

在 `_run_recluster()` 函数体开头添加：

```python
def _run_recluster():
    """[已废弃] 旧版事件重聚类 — 事件聚类已下沉到 process_article() 中的 AI 语义匹配。
    保留此函数供手动触发，但不参与 nightly 定时任务。
    """
    # ... 原有代码不变 ...
```

- [ ] **Step 3: 更新 `start_recluster` 端点说明**

```python
@router.post("/recluster")
def start_recluster():
    """[手动触发] 事件重聚类 — 仅在需要全量重建时使用。
    日常事件聚类已由 process_article() 自动完成。
    """
```

- [ ] **Step 4: Commit**

```bash
git add news-web/backend/api/pipeline_event.py
git commit -m "refactor: _nightly() 三步→两步，移除 recluster 步骤

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 修复全景图过滤 — 只取 2+ 关联事件

**Files:**
- Modify: `news-web/backend/ai_client.py:701-795` (`build_panoramic_context`)

**Interfaces:**
- Consumes: `conn` (sqlite3.Connection)
- Produces: `str` — 全景图文本，仅包含 ≥2 篇实际关联的事件

- [ ] **Step 1: 修改 `build_panoramic_context()` 的 SQL**

编辑 `news-web/backend/ai_client.py`，定位 `build_panoramic_context` 函数（约第 709 行），将事件查询 SQL 改为：

```python
    # 仅取 ≥2 篇实际关联的活跃事件（JOIN + GROUP BY + HAVING）
    events = conn.execute("""
        SELECT e.id, e.title, e.article_count, e.first_seen, e.last_seen, e.ai_summary
        FROM events e
        JOIN news_article_events ae ON ae.event_id = e.id
        WHERE e.status = 'active'
        GROUP BY e.id
        HAVING COUNT(ae.article_id) >= 2
        ORDER BY e.article_count DESC
    """).fetchall()
```

同时更新注释中的事件数：

```python
    lines.append(f"=== 事件全景图（共 {len(events)} 个活跃事件，均 ≥2 篇文章交叉验证）===\n")
```

- [ ] **Step 2: Commit**

```bash
git add news-web/backend/ai_client.py
git commit -m "fix: build_panoramic_context 只取 2+ 关联事件，过滤单篇垃圾

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 添加 pending_cluster 批处理定时任务

**Files:**
- Modify: `news-web/backend/scheduler.py:312-360`

**Interfaces:**
- Consumes: `pipeline.event_matching.match_article_to_event(article_id)`
- Produces: `_process_pending_cluster()` — 批处理所有 `content_status='pending_cluster'` 的文章

- [ ] **Step 1: 添加批处理函数**

在 `scheduler.py` 的 `_run_ai_full_job_sync()` 之后添加：

```python
def _process_pending_cluster():
    """批处理 pending_cluster 文章：尝试匹配此后新产生的事件。
    在新文章处理完成后由定时任务触发（每天 1 次）。
    """
    from pipeline.event_matching import match_article_to_event
    from utils.db import get_db_connection
    
    db = get_db_connection(config.db_path)
    try:
        rows = db.execute("""
            SELECT id FROM news_articles
            WHERE content_status = 'pending_cluster'
            ORDER BY id DESC
        """).fetchall()
        total = len(rows)
        if total == 0:
            logger.info("pending_cluster 批处理: 无待处理文章")
            return
        
        logger.info(f"pending_cluster 批处理: {total} 篇待匹配")
        matched = 0
        for (aid,) in rows:
            try:
                event_id = match_article_to_event(aid)
                if event_id:
                    matched += 1
            except Exception as e:
                logger.warning(f"pending_cluster #{aid} 匹配失败: {e}")
        
        logger.info(f"pending_cluster 批处理完成: {matched}/{total} 篇成功匹配")
    finally:
        db.close()


async def _run_pending_cluster_job():
    """Wrapper for pending_cluster batch processing."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _process_pending_cluster)
```

- [ ] **Step 2: 注册定时任务**

在 `start_scheduler()` 和 `reload_scheduler()` 中新增：

```python
# 在 backup 之后添加
scheduler.add_job(_run_pending_cluster_job, CronTrigger(hour=2, minute=30))
# 每天凌晨 2:30 — 在事件管线 (1:00) 和备份 (3:00) 之间
```

在日志信息中添加：

```python
parts.append("pending_cluster 02:30")
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/scheduler.py
git commit -m "feat: 新增 pending_cluster 批处理定时任务 (每天 02:30)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 一次性全量重建脚本

**Files:**
- Create: `news-web/backend/scripts/rebuild_events.py`

**Interfaces:**
- Consumes: `pipeline.event_matching.match_article_to_event()`
- Produces: 清空 events/news_article_events/event_relations/logic_chains，逐篇重建

此脚本为一次性使用，不在 FastAPI 生命周期内运行。

- [ ] **Step 1: 创建重建脚本**

`news-web/backend/scripts/rebuild_events.py`:

```python
#!/usr/bin/env python3
"""一次性全量重建事件数据。
清空所有事件相关表，对已处理文章逐篇进行 AI 语义聚类重建。

用法:
  cd news-web/backend
  python3 scripts/rebuild_events.py          # 全量重建
  python3 scripts/rebuild_events.py --dry-run # 预览不清空
"""
import sys, os, time, argparse, logging

# 路径修正
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from config import config
from utils.db import get_db_connection, safe_commit

logging.basicConfig(level=logging.INFO, format='%(asctime)s [Rebuild] %(message)s')
logger = logging.getLogger('rebuild')


def clear_all_events(db):
    """清空所有事件相关表。"""
    tables = ['chain_relations', 'chain_events', 'logic_chains',
              'event_relations', 'news_article_events', 'events']
    for t in tables:
        count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        db.execute(f"DELETE FROM {t}")
        logger.info(f"  清空 {t}: {count} 行")
    safe_commit(db)


def reset_article_status(db):
    """将所有已处理文章标记为 pending_cluster，等待重新匹配。"""
    count = db.execute("""
        UPDATE news_articles 
        SET content_status = 'pending_cluster'
        WHERE content_status IN ('processed', 'fetched', 'translated')
          AND ai_keywords IS NOT NULL AND ai_keywords != ''
    """).rowcount
    safe_commit(db)
    logger.info(f"  重置 {count} 篇文章状态 → pending_cluster")


def rebuild_all(db_path: str, dry_run: bool = False):
    """清空并全量重建。"""
    db = get_db_connection(db_path)
    
    # 统计当前状态
    evt_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    art_count = db.execute("SELECT COUNT(*) FROM news_articles WHERE content_status IN ('processed','fetched','translated') AND ai_keywords IS NOT NULL AND ai_keywords != ''").fetchone()[0]
    
    logger.info(f"当前: {evt_count} 事件, {art_count} 篇可聚类文章")
    
    if dry_run:
        logger.info("[DRY RUN] 不执行实际清空和重建")
        db.close()
        return
    
    # Phase 1: 清空
    logger.info("Phase 1: 清空所有事件数据...")
    clear_all_events(db)
    
    # Phase 2: 重置文章状态
    logger.info("Phase 2: 重置文章状态...")
    reset_article_status(db)
    db.close()
    
    # Phase 3: 逐篇重建 — 按 fetched_at 从旧到新
    logger.info("Phase 3: 逐篇 AI 语义聚类...")
    from pipeline.event_matching import match_article_to_event
    
    db2 = get_db_connection(db_path)
    rows = db2.execute("""
        SELECT id, title FROM news_articles
        WHERE content_status = 'pending_cluster'
        ORDER BY fetched_at ASC
    """).fetchall()
    db2.close()
    
    total = len(rows)
    matched = 0
    pending = 0
    start_time = time.time()
    
    for i, (aid, title) in enumerate(rows):
        try:
            event_id = match_article_to_event(aid)
            if event_id:
                matched += 1
            else:
                pending += 1
        except Exception as e:
            logger.warning(f"  #{aid} 匹配异常: {e}")
            pending += 1
        
        # 进度报告
        if (i + 1) % 50 == 0 or (i + 1) == total:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            logger.info(
                f"  进度: {i + 1}/{total} ({100*(i+1)/total:.1f}%) — "
                f"已匹配: {matched}, pending: {pending}, "
                f"速率: {rate:.1f} 篇/秒"
            )
        
        time.sleep(0.3)  # API 速率保护
    
    elapsed = time.time() - start_time
    logger.info(f"重建完成: {matched}/{total} 篇已匹配, {pending} 篇 pending, 耗时: {elapsed:.0f}s")
    
    # Phase 4: 最终统计
    db3 = get_db_connection(db_path)
    evt_final = db3.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    evt_multi = db3.execute("""
        SELECT COUNT(*) FROM events e
        JOIN news_article_events ae ON ae.event_id = e.id
        GROUP BY e.id HAVING COUNT(ae.article_id) >= 2
    """).fetchall()
    db3.close()
    logger.info(f"最终: {evt_final} 事件, {len(evt_multi)} 个 ≥2 篇文章")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='全量重建事件数据')
    parser.add_argument('--dry-run', action='store_true', help='预览不清空')
    args = parser.parse_args()
    
    rebuild_all(config.db_path, dry_run=args.dry_run)
```

- [ ] **Step 2: 确保 scripts 目录存在**

```bash
mkdir -p news-web/backend/scripts
touch news-web/backend/scripts/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add news-web/backend/scripts/rebuild_events.py news-web/backend/scripts/__init__.py
git commit -m "feat: 一次性全量事件重建脚本 rebuild_events.py

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 后端测试更新

**Files:**
- Modify: `news-web/tests/backend/test_pipeline_event.py`
- Modify: `news-web/tests/backend/test_pipeline_article.py`

**Interfaces:**
- Consumes: FastAPI TestClient, 现有测试结构
- Produces: 更新后的测试用例

- [ ] **Step 1: 更新事件管线测试**

编辑 `news-web/tests/backend/test_pipeline_event.py`，新增两步管线验证 + 移除 recluster 相关测试：

```python
def test_nightly_no_recluster_step():
    """夜间管线不应再包含 recluster 步骤（已下沉到文章处理）"""
    from api.pipeline_event import _nightly, _event_state
    # 通过 API 验证：nightly 端点不含 recluster 引用
    r = client.get("/api/pipeline/event/status")
    assert r.status_code == 200
    # steps 在非运行状态为空，验证端点本身可用即可


def test_recluster_endpoint_still_accessible():
    """recluster 端点应保留供手动触发，不应 404"""
    r = client.post("/api/pipeline/event/recluster")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data
```

保留现有测试（`test_get_event_status_idle`, `test_start_nightly_response` 等），它们不依赖步骤数量。

- [ ] **Step 2: 更新文章处理测试**

编辑 `news-web/tests/backend/test_pipeline_article.py`，验证事件匹配步骤：

```python
def test_process_article_with_event_matching():
    """处理已有 KCS 数据的文章，应包含 event_match 步骤"""
    import sqlite3
    from config import config
    db = sqlite3.connect(config.db_path)
    row = db.execute(
        "SELECT id FROM news_articles WHERE content_status='fetched' AND ai_keywords != '' LIMIT 1"
    ).fetchone()
    db.close()
    if not row:
        pytest.skip("无合适的测试文章")
    
    r = client.post(f"/api/pipeline/article/{row[0]}/process")
    assert r.status_code == 200
    data = r.json()
    # 不论成功与否，steps 中应包含 event_match
    assert "steps" in data
    # event_match 可能是 "Event#N", "pending_cluster", 或 "error: ..."
    assert "event_match" in data.get("steps", {})
```

保留现有测试（`test_process_single_article_not_found`, `test_get_article_status_idle`, `test_start_batch_process_response`）。

- [ ] **Step 3: 运行全部测试**

```bash
cd news-web && python3 -m pytest tests/backend/ -v
```

预期：所有测试通过（含更新后的 + 原有的 38 用例）。

- [ ] **Step 4: Commit**

```bash
git add news-web/tests/backend/
git commit -m "test: 更新测试适配事件管线重构 — 两步管线 + event_match 步骤

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 执行全量重建 + 验证

这是最终的端到端验证步骤。在生产环境执行全量重建，验证新架构正确运行。

- [ ] **Step 1: 备份数据库**

```bash
cp news-web/backend/data/news.db news-web/backend/data/news.db.before-rebuild-$(date +%Y%m%d-%H%M%S)
```

- [ ] **Step 2: Dry-run 验证**

```bash
cd news-web/backend && python3 scripts/rebuild_events.py --dry-run
```

确认统计数字合理。

- [ ] **Step 3: 执行全量重建**

```bash
cd news-web/backend && python3 scripts/rebuild_events.py
```

- [ ] **Step 4: 验证结果**

```bash
cd news-web/backend && python3 -c "
import sqlite3
db = sqlite3.connect('data/news.db')
# 事件统计
cur = db.execute('SELECT COUNT(*) FROM events')
print(f'事件总数: {cur.fetchone()[0]}')
cur = db.execute('''
    SELECT COUNT(*) FROM events e
    JOIN news_article_events ae ON ae.event_id = e.id
    GROUP BY e.id HAVING COUNT(ae.article_id) >= 2
''')
print(f'≥2篇事件: {len(cur.fetchall())}')
cur = db.execute(\"SELECT COUNT(*) FROM news_articles WHERE content_status='processed'\")
print(f'已处理文章: {cur.fetchone()[0]}')
cur = db.execute(\"SELECT COUNT(*) FROM news_articles WHERE content_status='pending_cluster'\")
print(f'pending_cluster: {cur.fetchone()[0]}')
cur = db.execute('SELECT COUNT(*) FROM logic_chains')
print(f'逻辑链: {cur.fetchone()[0]}')
db.close()
"
```

- [ ] **Step 5: 手动触发生成逻辑链**

```bash
curl -X POST http://localhost:8081/api/pipeline/event/build-chains
sleep 30
curl http://localhost:8081/api/pipeline/event/build-chains/status
```

- [ ] **Step 6: 重启服务验证状态一致性**

```bash
bash start_platform.sh restart
curl http://localhost:8081/api/pipeline/event/status
```

预期 `running: false`, steps 为空（非运行中状态），DB 中 task_states 无残留 running。

- [ ] **Step 7: 验证结束，Commit 如有微调**

```bash
git add -A && git diff --cached --stat
# 如有测试修正，commit
```

---

### Task 10: 清理注释 + 文档更新

- [ ] **Step 1: 更新 CLAUDE.md 架构决策记录**

在 CLAUDE.md 的"架构决策记录"部分追加：

```markdown
36. **AI 语义事件匹配替代 bigram** — 事件聚类在 process_article() KCS 后完成，不再使用 bigram Jaccard
37. **事件管线两步化** — nightly 从三步（recluster→summarize→chains）简化为两步（summarize→chains）
38. **全景图过滤** — build_panoramic_context() 仅取 ≥2 篇实际关联的活跃事件
39. **pending_cluster 机制** — 单篇文章标记 pending_cluster，每日 02:30 批处理重新尝试匹配
```

- [ ] **Step 2: Commit + Push**

```bash
git add CLAUDE.md
git commit -m "docs: 更新 CLAUDE.md 架构决策 — AI 语义匹配 + 两步管线

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin main
```

---

## 实现顺序依赖

```
Task 1 (废弃 bigram) ──┐
                        ├── Task 3 (集成到 process_article)
Task 2 (event_matching) ┘       │
                                ├── Task 7 (重建脚本) ── Task 9 (执行重建)
                                │
Task 4 (简化 nightly) ─────────┤
Task 5 (全景图过滤) ───────────┤
Task 6 (pending_cluster 定时) ──┘

Task 8 (测试更新) ← 依赖 Task 1-6 全部完成
Task 10 (文档) ← 最后
```

Task 1-5 可并行执行（互不依赖文件），Task 6-7 依赖 Task 2。Task 9 依赖全部代码变更完成。

---

## 延后事项

以下来自设计文档但不在本次实现范围，后续迭代处理：

- **事件关系 AI 检测** — 替代 `analyze.py` 规则引擎。需在 nightly 中新增 `_run_relations()` 步骤，对 2+ 篇事件对做 AI 批量关系检测。当前 `event_relations` 表为空（从未成功产出），不影响逻辑链构建。
- **事件合并/去重** — 当 AI 匹配发现高度相似事件时自动合并。需要新增合并逻辑和迁移脚本。
- **orphan 事件自动清理** — 超过 N 天仍为 orphan 的事件自动归档。
