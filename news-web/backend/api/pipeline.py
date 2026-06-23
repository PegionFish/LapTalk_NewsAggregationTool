"""
批量 AI 处理 API — 遍历数据库，对未处理文章执行翻译或分析。
后台异步执行，立即返回待处理数量。

全局锁: 同一时间只能运行一个 AI/管道任务。
状态持久化: 所有状态同步写入 DB，刷新后可恢复。
"""
import os, sqlite3, time, logging, threading
from datetime import datetime
from fastapi import APIRouter, HTTPException

from config import config
from utils.text import FULL_TEXT_MAX_LENGTH
from utils.task_lock import task_lock
from utils.task_state import task_state
from utils.db import get_db_connection, safe_commit

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)

# ── 进度追踪（内存 + DB 双写）───────────────────────────────
def _log(state, msg: str, task_type: str = ''):
    ts = datetime.now().strftime('%H:%M:%S')
    state["log"].append(f"[{ts}] {msg}")
    if task_type:
        task_state.update(task_type, log_msg=msg)

def _sync_state(state: dict, task_type: str):
    """将内存状态同步到 DB。"""
    task_state.update(task_type,
        running=state.get('running', False),
        total=state.get('total', 0),
        done=state.get('done', 0),
        failed=state.get('failed', 0),
        current=state.get('current', ''),
    )

def _is_request_timeout_error(exc: Exception) -> bool:
    return "request timed out" in str(exc).lower()

def _queue_timeout_retry(state, item_id, retry_counts, max_retries=4, task_type=''):
    count = retry_counts.get(item_id, 0) + 1
    retry_counts[item_id] = count
    if count <= max_retries:
        _log(state, f"#{item_id} Request Timed Out, retry ({count}/{max_retries + 1})", task_type)
        _log(state, f"#{item_id} 已排到队列末尾重试", task_type)
        return True
    return False

def _new_state() -> dict:
    """创建后台任务进度状态。"""
    return {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}


# 模块级状态初始化
_translate_state = _new_state()
_analyze_state  = _new_state()


def _check_and_lock(task_type: str) -> tuple[bool, str]:
    """检查并获取任务锁。返回 (ok, message)。"""
    ok, reason = task_lock.acquire(task_type)
    if not ok:
        return False, f"无法启动: {reason}"
    return True, ''


def _unlock(task_type: str):
    """释放任务锁。"""
    task_lock.release(task_type)


def _conn():
    """创建带超时配置的数据库连接，防止 WAL 并发写锁导致数据丢失。"""
    return get_db_connection(config.db_path)


# ═════════════════════════════════════════════════════════
# 批量翻译
# ═════════════════════════════════════════════════════════

def _batch_translate():
    global _translate_state
    _translate_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}

    try:
        cache_dir = config.content_cache_path
        if not os.path.isdir(cache_dir):
            _translate_state["running"] = False
            return

        # 找出有 HTML 缓存但未翻译的文章
        db = _conn()
        rows = db.execute("""
            SELECT id, title, local_path
            FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
              AND (translated_content IS NULL OR translated_content = '')
            ORDER BY id DESC
        """).fetchall()
        db.close()

        if not rows:
            _translate_state["running"] = False
            return

        _translate_state["total"] = len(rows)
        _log(_translate_state, f"待处理 {len(rows)} 篇 — HTML 直传 LLM 翻译")

        from utils.text import extract_text_from_html, detect_language
        from translation_client import translate_html

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str]] = []

        for idx, (aid, title, local_path) in enumerate(rows, 1):
            html_path = os.path.join(cache_dir, os.path.basename(local_path))
            if not os.path.isfile(html_path):
                _log(_translate_state, f"#{aid} ⚠️ HTML 文件不存在")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                # 写入标记避免下次重复查询，陷入无限循环
                db2 = _conn()
                db2.execute("UPDATE news_articles SET translated_content='[ERR:FILE_MISSING]' WHERE id=?", (aid,))
                safe_commit(db2)
                db2.close()
                continue

            _translate_state["current"] = f"#{aid} {title[:50]}"

            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    html = f.read()
            except Exception:
                _log(_translate_state, f"#{aid} ❌ 文件读取失败")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                db2 = _conn()
                db2.execute("UPDATE news_articles SET translated_content='[ERR:READ_FAILED]' WHERE id=?", (aid,))
                safe_commit(db2)
                db2.close()
                continue

            if len(html) < 100:
                _log(_translate_state, f"#{aid} ⚠️ HTML 过短 ({len(html)} 字节)")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                db2 = _conn()
                db2.execute("UPDATE news_articles SET translated_content='[ERR:HTML_TOO_SHORT]' WHERE id=?", (aid,))
                safe_commit(db2)
                db2.close()
                continue

            # 仅提取纯文本用于语言检测，翻译和存储均使用原始 HTML
            text_for_lang = extract_text_from_html(html, max_length=5000)
            if len(text_for_lang) < 50:
                _log(_translate_state, f"#{aid} ⚠️ 文本内容过短 ({len(text_for_lang)} 字)")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            lang = detect_language(text_for_lang)
            _log(_translate_state, f"#{aid} 语言: {lang} | HTML {len(html)//1024}KB")

            if lang != 'en':
                db2 = _conn()
                db2.execute("UPDATE news_articles SET text_content=?, content_lang=? WHERE id=?",
                           (html, lang, aid))
                safe_commit(db2)
                db2.close()
                _log(_translate_state, f"#{aid} ⏭️ 非英文，存入 HTML")
                _translate_state["done"] += 1
                continue

            # HTML 直传 LLM 翻译，保留全部标签结构
            try:
                _log(_translate_state, f"#{aid} 📡 翻译中... (HTML {len(html)//1024}KB, 模型: {config.translation_model})")
                translation = translate_html(html)
                if translation and len(translation) > 20:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE news_articles SET text_content=?, translated_content=?, content_status='translated', content_lang='en', translated_at=? WHERE id=?",
                        (html, translation, datetime.now().isoformat(timespec='seconds'), aid)
                    )
                    safe_commit(db2)
                    db2.close()
                    _log(_translate_state, f"#{aid} ✅ 翻译完成 ({len(translation)} 字)")
                else:
                    _log(_translate_state, f"#{aid} ⚠️ API 返回空结果")
                    _translate_state["failed"] += 1
                    _translate_state["done"] += 1
                    continue
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(
                    _translate_state, aid, retry_counts
                ):
                    retry_queue.append((aid, title, html))
                    continue
                _log(_translate_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            _translate_state["done"] += 1

            if idx < len(rows):
                time.sleep(0.1)  # 速率限制由 RateLimiter 统一管理

        for aid, title, html in retry_queue:
            _translate_state["current"] = f"#{aid} {title[:50]}"
            _log(_translate_state, f"#{aid} 🔄 重试翻译请求...")
            try:
                translation = translate_html(html)
                if translation and len(translation) > 20:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE news_articles SET text_content=?, translated_content=?, content_status='translated', content_lang='en', translated_at=? WHERE id=?",
                        (html, translation, datetime.now().isoformat(timespec='seconds'), aid)
                    )
                    safe_commit(db2)
                    db2.close()
                    _log(_translate_state, f"#{aid} ✅ 翻译完成 ({len(translation)} 字)")
                else:
                    _log(_translate_state, f"#{aid} ⚠️ API 返回空结果")
                    _translate_state["failed"] += 1
                    _translate_state["done"] += 1
                    continue
            except Exception as e:
                if _is_request_timeout_error(e):
                    _log(_translate_state, f"#{aid} ❌ API 调用失败: Request Timed Out（重试后仍超时）")
                else:
                    _log(_translate_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue
            _translate_state["done"] += 1

    except Exception as e:
        logger.error(f"Batch translate error: {e}")
    finally:
        _translate_state["running"] = False
        _unlock('translate')
        task_state.finish('translate', success=True)


# ═════════════════════════════════════════════════════════
# 批量分析
# ═════════════════════════════════════════════════════════

def _batch_analyze():
    global _analyze_state
    _analyze_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}

    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title, text_content
            FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
              AND (ai_analyzed IS NULL OR ai_analyzed = 0 OR ai_summary IS NULL OR ai_summary = '')
            ORDER BY id DESC
        """).fetchall()
        db.close()

        if not rows:
            _analyze_state["running"] = False
            return

        _analyze_state["total"] = len(rows)
        _log(_analyze_state, f"待分析 {len(rows)} 篇文章 (模型: {config.openai_model})")

        from ai_client import analyze_article as ai_analyze

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str]] = []

        for idx, (aid, title, text) in enumerate(rows, 1):
            _analyze_state["current"] = f"#{aid} {title[:50]}"
            _log(_analyze_state, f"#{aid} 📡 发送分析请求... ({len(text)} 字，{len(text)/1024:.1f}KB 正文)")

            try:
                analysis = ai_analyze(title, text)
                if analysis:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE news_articles SET ai_summary=?, ai_analyzed=1 WHERE id=?",
                        (analysis, aid)
                    )
                    safe_commit(db2)
                    db2.close()
                    _log(_analyze_state, f"#{aid} ✅ 分析完成 ({len(analysis)} 字)")
                else:
                    _log(_analyze_state, f"#{aid} ⚠️ AI 返回空结果")
                    _analyze_state["failed"] += 1
                    _analyze_state["done"] += 1
                    continue
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(
                    _analyze_state, aid, retry_counts
                ):
                    retry_queue.append((aid, title, text))
                    continue
                _log(_analyze_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _analyze_state["failed"] += 1
                _analyze_state["done"] += 1
                continue

            _analyze_state["done"] += 1

            if idx < len(rows):
                time.sleep(0.1)  # 速率限制由 RateLimiter 统一管理

        for aid, title, text in retry_queue:
            _analyze_state["current"] = f"#{aid} {title[:50]}"
            _log(_analyze_state, f"#{aid} 🔄 重试分析请求...")
            try:
                analysis = ai_analyze(title, text)
                if analysis:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE news_articles SET ai_summary=?, ai_analyzed=1 WHERE id=?",
                        (analysis, aid)
                    )
                    safe_commit(db2)
                    db2.close()
                    _log(_analyze_state, f"#{aid} ✅ 分析完成 ({len(analysis)} 字)")
                else:
                    _log(_analyze_state, f"#{aid} ⚠️ AI 返回空结果")
                    _analyze_state["failed"] += 1
                    _analyze_state["done"] += 1
                    continue
            except Exception as e:
                if _is_request_timeout_error(e):
                    _log(_analyze_state, f"#{aid} ❌ API 调用失败: Request Timed Out（重试后仍超时）")
                else:
                    _log(_analyze_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _analyze_state["failed"] += 1
                _analyze_state["done"] += 1
                continue
            _analyze_state["done"] += 1

    except Exception as e:
        logger.error(f"Batch analyze error: {e}")
    finally:
        _analyze_state["running"] = False
        _unlock('analyze')
        task_state.finish('analyze', success=True)


# ═════════════════════════════════════════════════════════
# 全景图批处理 — 利用 160K 上下文做全局推理
# ═════════════════════════════════════════════════════════

_chain_state = {"running": False, "total_groups": 0, "chains_created": 0, "current": "", "log": []}
_rank_state  = _new_state()


def _build_logic_chains():
    """基于全景图识别逻辑链分组，一次 API 调用替代逐组 Jaccard 聚类。"""
    global _chain_state
    _chain_state = {"running": True, "total_groups": 0, "chains_created": 0, "current": "", "log": []}

    try:
        db = _conn()
        from ai_client import build_panoramic_context, build_chains_panoramic

        context = build_panoramic_context(db)
        _log(_chain_state, f"全景图已构建，请求 AI 识别逻辑链...")

        groups = build_chains_panoramic(context)
        if not groups or not isinstance(groups, list):
            _log(_chain_state, "⚠️ AI 未返回有效的事件分组")
            db.close()
            _chain_state["running"] = False
            return

        _chain_state["total_groups"] = len(groups)
        _log(_chain_state, f"AI 识别出 {len(groups)} 个逻辑链分组")

        from datetime import datetime

        for idx, group in enumerate(groups, 1):
            event_ids = group.get("events", [])
            chain_title = group.get("title", "")
            reason = group.get("reason", "")

            if len(event_ids) < 2 or not chain_title:
                continue

            _chain_state["current"] = f"第 {idx}/{len(groups)} 组: {chain_title}"

            # 验证事件 ID 存在
            valid_ids = []
            for eid in event_ids:
                r = db.execute("SELECT id FROM events WHERE id=? AND status='active'", (eid,)).fetchone()
                if r:
                    valid_ids.append(eid)
            if len(valid_ids) < 2:
                continue

            # 检查是否已有链覆盖这些事件
            existing = db.execute(
                f"SELECT DISTINCT chain_id FROM chain_events WHERE event_id IN ({','.join('?'*len(valid_ids))})",
                valid_ids
            ).fetchall()
            if existing:
                _log(_chain_state, f"第 {idx} 组已有链覆盖，跳过")
                continue

            now = datetime.now().isoformat(timespec='seconds')
            cur = db.execute(
                "INSERT INTO logic_chains (title, description, created_at, updated_at, created_by) VALUES (?, ?, ?, ?, 'auto')",
                (chain_title[:100], f"AI 全景推理 — {reason}", now, now)
            )
            chain_id = cur.lastrowid
            for pos, eid in enumerate(valid_ids):
                db.execute(
                    "INSERT INTO chain_events (chain_id, event_id, position) VALUES (?, ?, ?)",
                    (chain_id, eid, pos)
                )

            _chain_state["chains_created"] += 1
            _log(_chain_state, f"✅ 创建链: {chain_title} ({len(valid_ids)} 个事件) — {reason}")

        safe_commit(db)
        db.close()

    except Exception as e:
        logger.error(f"Build chains error: {e}")
    finally:
        _chain_state["running"] = False
        _unlock('build_chains')
        task_state.finish('build_chains', success=True)


def _batch_ai_rank_events():
    """基于全景图对所有事件做全局优先级排序。"""
    global _rank_state
    _rank_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        from ai_client import build_panoramic_context, rank_events_panoramic

        context = build_panoramic_context(db)
        _log(_rank_state, "全景图已构建，请求 AI 全局排序...")

        result = rank_events_panoramic(context)
        if not result or not isinstance(result, list):
            _log(_rank_state, "⚠️ AI 未返回有效排序结果")
            _rank_state["running"] = False
            return

        _rank_state["total"] = len(result)
        _log(_rank_state, f"AI 返回 {len(result)} 个事件排序")

        import json
        for item in result:
            eid = item.get("id")
            rank = item.get("rank", 999)
            reason = item.get("reason", "")
            if not eid:
                continue
            # rank → priority_label: 前 20% high, 中间 50% medium, 后 30% low
            total = len(result)
            if total > 0:
                pct = rank / total
                if pct <= 0.2:
                    label = "high"
                elif pct <= 0.7:
                    label = "medium"
                else:
                    label = "low"
            else:
                label = "medium"
            db.execute("UPDATE events SET priority_label=? WHERE id=?", (label, eid))
            _rank_state["done"] += 1
            _log(_rank_state, f"#{eid} → {label} (排名 {rank}/{total}) — {reason}")

        safe_commit(db)
        db.close()

    except Exception as e:
        logger.error(f"Batch rank events error: {e}")
    finally:
        _rank_state["running"] = False
        _unlock('rank_events')
        task_state.finish('rank_events', success=True)


# ═════════════════════════════════════════════════════════
# API 端点
# ═════════════════════════════════════════════════════════

@router.post("/batch-translate")
def start_batch_translate():
    """启动批量翻译 — 遍历所有有 HTML 缓存但未翻译的英文文章。"""
    global _translate_state
    if _translate_state.get("running"):
        return {"ok": False, "message": "翻译任务已在运行中", "state": _translate_state}

    ok, msg = _check_and_lock('translate')
    if not ok:
        return {"ok": False, "message": msg}

    # 预计算待处理数量
    db = _conn()
    pending = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
          AND (translated_content IS NULL OR translated_content = '')
    """).fetchone()[0]
    db.close()

    task_state.init_state('translate', total=pending)
    threading.Thread(target=_batch_translate, daemon=True).start()
    return {"ok": True, "message": f"启动批量翻译，预计 {pending} 篇", "pending": pending}


@router.get("/batch-translate/status")
def get_batch_translate_status():
    """查询批量翻译进度 — running/current/log 来自内存，统计从 DB 派生。"""
    if _translate_state.get("running"):
        db = _conn()
        total = db.execute("""
            SELECT COUNT(*) FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
              AND (translated_content IS NULL OR translated_content = '')
        """).fetchone()[0]
        done = db.execute("""
            SELECT COUNT(*) FROM news_articles
            WHERE translated_content != ''
        """).fetchone()[0]
        db.close()
        return {"running": True, "total": total, "done": done, "failed": 0,
                "current": _translate_state["current"], "log": _translate_state["log"]}
    return dict(_translate_state)


@router.post("/batch-analyze")
def start_batch_analyze():
    """启动批量分析 — 遍历所有有文本内容但未 AI 分析的文章。"""
    global _analyze_state
    if _analyze_state.get("running"):
        return {"ok": False, "message": "分析任务已在运行中", "state": _analyze_state}
    ok, msg = _check_and_lock('analyze')
    if not ok:
        return {"ok": False, "message": msg}
    db = _conn()
    pending = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
          AND (ai_analyzed IS NULL OR ai_analyzed = 0 OR ai_summary IS NULL OR ai_summary = '')
    """).fetchone()[0]
    db.close()
    task_state.init_state('analyze', total=pending)
    threading.Thread(target=_batch_analyze, daemon=True).start()
    return {"ok": True, "message": f"启动批量分析，预计 {pending} 篇", "pending": pending}


@router.get("/batch-analyze/status")
def get_batch_analyze_status():
    """查询批量分析进度。"""
    if _analyze_state.get("running"):
        db = _conn()
        total = db.execute("""
            SELECT COUNT(*) FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
              AND (ai_analyzed IS NULL OR ai_analyzed = 0 OR ai_summary IS NULL OR ai_summary = '')
        """).fetchone()[0]
        done = db.execute("""
            SELECT COUNT(*) FROM news_articles WHERE ai_analyzed = 1 AND ai_summary != ''
        """).fetchone()[0]
        db.close()
        return {"running": True, "total": total, "done": done, "failed": 0,
                "current": _analyze_state["current"], "log": _analyze_state["log"]}
    return dict(_analyze_state)


@router.get("/build-chains/status")
def get_build_chains_status():
    """查询逻辑链构筑进度。"""
    if _chain_state.get("running"):
        db = _conn()
        chains = db.execute("SELECT COUNT(*) FROM logic_chains WHERE created_by='auto'").fetchone()[0]
        db.close()
        return {"running": True, "total_groups": _chain_state["total_groups"],
                "chains_created": chains, "current": _chain_state["current"],
                "log": _chain_state["log"]}
    return dict(_chain_state)


@router.post("/build-chains")
def start_build_chains():
    """手动触发逻辑链构筑 — 基于事件关键词分组 + AI 命名。"""
    global _chain_state
    if _chain_state.get("running"):
        return {"ok": False, "message": "链构筑已在运行中", "state": _chain_state}
    ok, msg = _check_and_lock('build_chains')
    if not ok:
        return {"ok": False, "message": msg}
    task_state.init_state('build_chains')
    threading.Thread(target=_build_logic_chains, daemon=True).start()
    return {"ok": True, "message": "开始构筑逻辑链"}


# ═════════════════════════════════════════════════════════
# AI 接管批量端点 — 关键词 / 分类 / 评分 / 重聚类 / 事件摘要
# ═════════════════════════════════════════════════════════

_kw_state    = _new_state()
_cls_state   = _new_state()
_score_state = _new_state()
_recluster_state  = _new_state()
_evt_sum_state    = _new_state()
_filter_state     = _new_state()
_clean_state      = _new_state()


def _batch_ai_keywords():
    global _kw_state
    _kw_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        rows = db.execute("SELECT id, title, text_content, source FROM news_articles WHERE content_status IN ('fetched', 'translated') AND (ai_keywords IS NULL OR ai_keywords = '') ORDER BY id DESC").fetchall(); db.close()
        if not rows: _kw_state["running"] = False; return
        _kw_state["total"] = len(rows)
        _log(_kw_state, f"待提取关键词 {len(rows)} 篇")
        from ai_client import extract_keywords_ai
        import json as _json

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str, str]] = []

        for idx, (aid, title, text, source) in enumerate(rows, 1):
            _kw_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_kw_state, f"#{aid} ⏭️ 人工已处理"); _kw_state["done"] += 1; continue
            try:
                kws = extract_keywords_ai(title, text, source or "")
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(_kw_state, aid, retry_counts):
                    retry_queue.append((aid, title, text, source or ""))
                    continue
                _log(_kw_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _kw_state["failed"] += 1; _kw_state["done"] += 1
                continue
            if kws:
                db2 = _conn()
                db2.execute("UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?", (_json.dumps(kws, ensure_ascii=False), _json.dumps(kws, ensure_ascii=False), aid))
                safe_commit(db2); db2.close()
                _log(_kw_state, f"#{aid} ✅ {len(kws)} 个关键词: {', '.join(kws[:5])}")
            else:
                _log(_kw_state, f"#{aid} ⚠️ AI 返回空"); _kw_state["failed"] += 1
            _kw_state["done"] += 1
            time.sleep(0.1) if idx < len(rows) else None  # 速率限制由 RateLimiter 统一管理

        for aid, title, text, source in retry_queue:
            _kw_state["current"] = f"#{aid} {title[:50]}"
            _log(_kw_state, f"#{aid} 🔄 重试关键词提取...")
            try:
                kws = extract_keywords_ai(title, text, source)
                if kws:
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?", (_json.dumps(kws, ensure_ascii=False), _json.dumps(kws, ensure_ascii=False), aid))
                    safe_commit(db2); db2.close()
                    _log(_kw_state, f"#{aid} ✅ {len(kws)} 个关键词: {', '.join(kws[:5])}")
                else:
                    _log(_kw_state, f"#{aid} ⚠️ AI 返回空"); _kw_state["failed"] += 1
            except Exception as e:
                if _is_request_timeout_error(e):
                    _log(_kw_state, f"#{aid} ❌ API 调用失败: Request Timed Out（重试后仍超时）")
                else:
                    _log(_kw_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _kw_state["failed"] += 1
            _kw_state["done"] += 1
    except Exception as e: logger.error(f"batch-keywords: {e}")
    finally:
        _kw_state["running"] = False
        _unlock('keywords')
        task_state.finish('keywords', success=True)


def _batch_ai_classify():
    global _cls_state
    _cls_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        rows = db.execute("SELECT id, title, text_content FROM news_articles WHERE content_status IN ('fetched', 'translated') AND (ai_category IS NULL OR ai_category = '') ORDER BY id DESC").fetchall(); db.close()
        if not rows: _cls_state["running"] = False; return
        _cls_state["total"] = len(rows)
        _log(_cls_state, f"待分类 {len(rows)} 篇")
        from ai_client import classify_article_ai
        import json as _json

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str]] = []

        for idx, (aid, title, text) in enumerate(rows, 1):
            _cls_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_cls_state, f"#{aid} ⏭️ 人工已处理"); _cls_state["done"] += 1; continue
            try:
                r = classify_article_ai(title, text)
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(_cls_state, aid, retry_counts):
                    retry_queue.append((aid, title, text))
                    continue
                _log(_cls_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _cls_state["failed"] += 1; _cls_state["done"] += 1
                continue
            if r:
                db2 = _conn()
                db2.execute("UPDATE news_articles SET ai_category=?, ai_tags=? WHERE id=?", (r.get("category",""), _json.dumps(r.get("tags",[]), ensure_ascii=False), aid))
                safe_commit(db2); db2.close()
                _log(_cls_state, f"#{aid} ✅ {r.get('category','?')} — {', '.join(r.get('tags',[])[:3])}")
            else:
                _log(_cls_state, f"#{aid} ⚠️ AI 返回空"); _cls_state["failed"] += 1
            _cls_state["done"] += 1
            time.sleep(0.1) if idx < len(rows) else None  # 速率限制由 RateLimiter 统一管理

        for aid, title, text in retry_queue:
            _cls_state["current"] = f"#{aid} {title[:50]}"
            _log(_cls_state, f"#{aid} 🔄 重试分类...")
            try:
                r = classify_article_ai(title, text)
                if r:
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_category=?, ai_tags=? WHERE id=?", (r.get("category",""), _json.dumps(r.get("tags",[]), ensure_ascii=False), aid))
                    safe_commit(db2); db2.close()
                    _log(_cls_state, f"#{aid} ✅ {r.get('category','?')} — {', '.join(r.get('tags',[])[:3])}")
                else:
                    _log(_cls_state, f"#{aid} ⚠️ AI 返回空"); _cls_state["failed"] += 1
            except Exception as e:
                if _is_request_timeout_error(e):
                    _log(_cls_state, f"#{aid} ❌ API 调用失败: Request Timed Out（重试后仍超时）")
                else:
                    _log(_cls_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _cls_state["failed"] += 1
            _cls_state["done"] += 1
    except Exception as e: logger.error(f"batch-classify: {e}")
    finally:
        _cls_state["running"] = False
        _unlock('classify')
        task_state.finish('classify', success=True)


def _batch_ai_score():
    global _score_state
    _score_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        rows = db.execute("SELECT id, title, text_content, source, fetched_at FROM news_articles WHERE content_status IN ('fetched', 'translated') AND (ai_priority_score IS NULL OR ai_priority_score = 0.0) ORDER BY id DESC").fetchall(); db.close()
        if not rows: _score_state["running"] = False; return
        _score_state["total"] = len(rows)
        _log(_score_state, f"待评分 {len(rows)} 篇")
        from ai_client import score_priority_ai
        from datetime import datetime as _dt

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str, str, str]] = []

        for idx, (aid, title, text, source, fetched_at) in enumerate(rows, 1):
            _score_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_score_state, f"#{aid} ⏭️ 人工已处理"); _score_state["done"] += 1; continue
            try:
                days = max(0, (_dt.now() - _dt.fromisoformat(fetched_at)).days) if fetched_at else 0
            except Exception:
                days = 0
            try:
                r = score_priority_ai(title, text, source or "Unknown", days)
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(_score_state, aid, retry_counts):
                    retry_queue.append((aid, title, text, source or "Unknown", fetched_at or ""))
                    continue
                _log(_score_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _score_state["failed"] += 1; _score_state["done"] += 1
                continue
            if r:
                db2 = _conn()
                db2.execute("UPDATE news_articles SET priority_score=?, priority_label=?, ai_priority_score=? WHERE id=?", (r["score"], r.get("label","medium"), r["score"], aid))
                safe_commit(db2); db2.close()
                _log(_score_state, f"#{aid} ✅ {r.get('label','medium')}({r['score']:.0f}) — {r.get('reason','')}")
            else:
                _log(_score_state, f"#{aid} ⚠️ AI 返回空"); _score_state["failed"] += 1
            _score_state["done"] += 1
            time.sleep(0.1) if idx < len(rows) else None  # 速率限制由 RateLimiter 统一管理

        for aid, title, text, source, fetched_at in retry_queue:
            _score_state["current"] = f"#{aid} {title[:50]}"
            _log(_score_state, f"#{aid} 🔄 重试评分...")
            try:
                days = max(0, (_dt.now() - _dt.fromisoformat(fetched_at)).days) if fetched_at else 0
            except Exception:
                days = 0
            try:
                r = score_priority_ai(title, text, source, days)
                if r:
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET priority_score=?, priority_label=?, ai_priority_score=? WHERE id=?", (r["score"], r.get("label","medium"), r["score"], aid))
                    safe_commit(db2); db2.close()
                    _log(_score_state, f"#{aid} ✅ {r.get('label','medium')}({r['score']:.0f}) — {r.get('reason','')}")
                else:
                    _log(_score_state, f"#{aid} ⚠️ AI 返回空"); _score_state["failed"] += 1
            except Exception as e:
                if _is_request_timeout_error(e):
                    _log(_score_state, f"#{aid} ❌ API 调用失败: Request Timed Out（重试后仍超时）")
                else:
                    _log(_score_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _score_state["failed"] += 1
            _score_state["done"] += 1
    except Exception as e: logger.error(f"batch-score: {e}")
    finally:
        _score_state["running"] = False
        _unlock('score')
        task_state.finish('score', success=True)


def _batch_ai_recluster():
    global _recluster_state
    _recluster_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        unlinked = db.execute("SELECT a.id, a.title FROM news_articles a LEFT JOIN news_article_events ae ON a.id=ae.article_id WHERE ae.article_id IS NULL AND a.content_status IN ('fetched', 'translated')").fetchall()
        events  = db.execute("SELECT id, title FROM events WHERE status='active'").fetchall()
        db.close()
        if not unlinked: _recluster_state["running"] = False; return
        _recluster_state["total"] = len(unlinked)
        _log(_recluster_state, f"待聚类 {len(unlinked)} 篇 → {len(events)} 个活跃事件")
        from ai_client import match_article_to_events_ai

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str]] = []
        MAX_CANDIDATES = 50  # 每次 API 调用最多比对的候选事件数

        for idx, (aid, art_title) in enumerate(unlinked, 1):
            _recluster_state["current"] = f"#{aid} {art_title[:50]}"

            # 用标题拼音相似度预筛候选事件（top50），减少 AI 调用 token 消耗
            from db.news_db import title_similarity
            scored_events = [(title_similarity(art_title, etitle), eid, etitle)
                             for eid, etitle in events]
            scored_events.sort(key=lambda x: x[0], reverse=True)
            candidates = [(eid, etitle) for _, eid, etitle in scored_events[:MAX_CANDIDATES]]

            try:
                r = match_article_to_events_ai(art_title, candidates)
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(_recluster_state, aid, retry_counts):
                    retry_queue.append((aid, art_title))
                    continue
                _log(_recluster_state, f"#{aid} ❌ AI 聚类失败: {str(e)[:300]}")
                _recluster_state["failed"] += 1
                _recluster_state["done"] += 1
                continue

            if r and r.get("event_id") and r.get("confidence", 0) > 0.5:
                best_id = r["event_id"]
                best_conf = r["confidence"]
                # 验证事件 ID 存在
                if any(eid == best_id for eid, _ in events):
                    db2 = _conn()
                    db2.execute("INSERT OR IGNORE INTO news_article_events (article_id, event_id, relevance) VALUES (?, ?, ?)",
                               (aid, best_id, round(best_conf, 2)))
                    db2.execute("UPDATE events SET article_count=article_count+1 WHERE id=?", (best_id,))
                    safe_commit(db2); db2.close()
                    _log(_recluster_state, f"#{aid} ✅ -> 事件#{best_id} (置信度 {best_conf:.2f}) — {r.get('reason', '')}")
                else:
                    # AI 返回了无效事件 ID，创建新事件
                    _log(_recluster_state, f"#{aid} ➕ 创建新事件（AI 返回无效事件ID）")
                    from datetime import datetime as _dt
                    now = _dt.now().isoformat(timespec='seconds')
                    db2 = _conn()
                    cur = db2.execute("INSERT INTO events (title, first_seen, last_seen, status) VALUES (?,?,?,'active')",
                                     (art_title[:80], now[:10], now[:10]))
                    db2.execute("INSERT INTO news_article_events (article_id, event_id) VALUES (?,?)", (aid, cur.lastrowid))
                    safe_commit(db2); db2.close()
            else:
                _log(_recluster_state, f"#{aid} ➕ 创建新事件")
                from datetime import datetime as _dt
                now = _dt.now().isoformat(timespec='seconds')
                db2 = _conn()
                cur = db2.execute("INSERT INTO events (title, first_seen, last_seen, status) VALUES (?,?,?,'active')",
                                 (art_title[:80], now[:10], now[:10]))
                db2.execute("INSERT INTO news_article_events (article_id, event_id) VALUES (?,?)", (aid, cur.lastrowid))
                safe_commit(db2); db2.close()
            _recluster_state["done"] += 1
            time.sleep(0.1)  # 速率限制由 RateLimiter 统一管理

        for aid, art_title in retry_queue:
            _recluster_state["current"] = f"#{aid} {art_title[:50]}"
            _log(_recluster_state, f"#{aid} 🔄 重试聚类...")
            try:
                scored_events = [(title_similarity(art_title, etitle), eid, etitle)
                                 for eid, etitle in events]
                scored_events.sort(key=lambda x: x[0], reverse=True)
                candidates = [(eid, etitle) for _, eid, etitle in scored_events[:MAX_CANDIDATES]]
                r = match_article_to_events_ai(art_title, candidates)
                if r and r.get("event_id") and r.get("confidence", 0) > 0.5 and any(eid == r["event_id"] for eid, _ in events):
                    db2 = _conn()
                    db2.execute("INSERT OR IGNORE INTO news_article_events (article_id, event_id, relevance) VALUES (?, ?, ?)",
                               (aid, r["event_id"], round(r["confidence"], 2)))
                    db2.execute("UPDATE events SET article_count=article_count+1 WHERE id=?", (r["event_id"],))
                    safe_commit(db2); db2.close()
                    _log(_recluster_state, f"#{aid} ✅ -> 事件#{r['event_id']} (置信度 {r['confidence']:.2f})")
                else:
                    _log(_recluster_state, f"#{aid} ➕ 创建新事件")
                    from datetime import datetime as _dt
                    now = _dt.now().isoformat(timespec='seconds')
                    db2 = _conn()
                    cur = db2.execute("INSERT INTO events (title, first_seen, last_seen, status) VALUES (?,?,?,'active')",
                                     (art_title[:80], now[:10], now[:10]))
                    db2.execute("INSERT INTO news_article_events (article_id, event_id) VALUES (?,?)", (aid, cur.lastrowid))
                    safe_commit(db2); db2.close()
            except Exception as e:
                if _is_request_timeout_error(e):
                    _log(_recluster_state, f"#{aid} ❌ API 调用失败: Request Timed Out（重试后仍超时）")
                else:
                    _log(_recluster_state, f"#{aid} ❌ API 调用失败: {str(e)[:300]}")
                _recluster_state["failed"] += 1
            _recluster_state["done"] += 1
    except Exception as e: logger.error(f"batch-recluster: {e}")
    finally:
        _recluster_state["running"] = False
        _unlock('recluster')
        task_state.finish('recluster', success=True)


def _batch_ai_summarize_events():
    global _evt_sum_state
    _evt_sum_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        events = db.execute("SELECT id, article_count FROM events WHERE article_count >= 2 AND (ai_summary IS NULL OR ai_summary = '')").fetchall(); db.close()
        if not events: _evt_sum_state["running"] = False; return
        _evt_sum_state["total"] = len(events)
        _log(_evt_sum_state, f"待生成摘要 {len(events)} 个事件")
        from ai_client import generate_event_summary_ai

        retry_counts: dict[int, int] = {}
        retry_queue: list[int] = []

        for idx, (evt_id, _) in enumerate(events, 1):
            _evt_sum_state["current"] = f"事件#{evt_id}"
            db2 = _conn()
            titles = [r[0] for r in db2.execute("SELECT a.title FROM news_articles a JOIN news_article_events ae ON ae.article_id=a.id WHERE ae.event_id=?", (evt_id,)).fetchall()]
            db2.close()
            if len(titles) < 2: _evt_sum_state["done"] += 1; continue
            block = "\n".join(f"- {t}" for t in titles[:15])
            try:
                summary = generate_event_summary_ai(block)
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(_evt_sum_state, evt_id, retry_counts):
                    retry_queue.append(evt_id)
                    continue
                _log(_evt_sum_state, f"#{evt_id} ❌ API 调用失败: {str(e)[:300]}")
                _evt_sum_state["failed"] += 1; _evt_sum_state["done"] += 1
                continue
            if summary:
                db2 = _conn()
                db2.execute("UPDATE events SET ai_summary=? WHERE id=?", (summary, evt_id))
                safe_commit(db2); db2.close()
                _log(_evt_sum_state, f"#{evt_id} ✅ {len(summary)} 字")
            else:
                _log(_evt_sum_state, f"#{evt_id} ⚠️ AI 返回空"); _evt_sum_state["failed"] += 1
            _evt_sum_state["done"] += 1
            time.sleep(0.1) if idx < len(events) else None  # 速率限制由 RateLimiter 统一管理

        for evt_id in retry_queue:
            _evt_sum_state["current"] = f"事件#{evt_id}"
            _log(_evt_sum_state, f"#{evt_id} 🔄 重试摘要生成...")
            db2 = _conn()
            titles = [r[0] for r in db2.execute("SELECT a.title FROM news_articles a JOIN news_article_events ae ON ae.article_id=a.id WHERE ae.event_id=?", (evt_id,)).fetchall()]
            db2.close()
            if len(titles) < 2: _evt_sum_state["done"] += 1; continue
            block = "\n".join(f"- {t}" for t in titles[:15])
            try:
                summary = generate_event_summary_ai(block)
                if summary:
                    db2 = _conn()
                    db2.execute("UPDATE events SET ai_summary=? WHERE id=?", (summary, evt_id))
                    safe_commit(db2); db2.close()
                    _log(_evt_sum_state, f"#{evt_id} ✅ {len(summary)} 字")
                else:
                    _log(_evt_sum_state, f"#{evt_id} ⚠️ AI 返回空"); _evt_sum_state["failed"] += 1
            except Exception as e:
                if _is_request_timeout_error(e):
                    _log(_evt_sum_state, f"#{evt_id} ❌ API 调用失败: Request Timed Out（重试后仍超时）")
                else:
                    _log(_evt_sum_state, f"#{evt_id} ❌ API 调用失败: {str(e)[:300]}")
                _evt_sum_state["failed"] += 1
            _evt_sum_state["done"] += 1
    except Exception as e: logger.error(f"batch-summarize-events: {e}")
    finally:
        _evt_sum_state["running"] = False
        _unlock('summarize_events')
        task_state.finish('summarize_events', success=True)


# ═════════════════════════════════════════════════════════
# AI 预筛选 — 标题批量判断，筛掉不需要的文章
# ═════════════════════════════════════════════════════════

def _batch_ai_filter():
    """对未筛选的文章标题批量调用 AI，标记通过/拒绝。"""
    global _filter_state
    _filter_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title, source FROM news_articles
            WHERE content_status = 'pending'
              AND (ai_filtered = 0)
            ORDER BY fetched_at DESC
        """).fetchall()
        db.close()

        if not rows:
            _filter_state["running"] = False
            return

        _filter_state["total"] = len(rows)
        _log(_filter_state, f"待筛选 {len(rows)} 篇标题")

        from pipeline.ai_filter import filter_batch

        BATCH = 30
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            _filter_state["current"] = f"批次 {i // BATCH + 1} ({len(batch)} 篇)"
            batch_ids = filter_batch(batch)

            if batch_ids is None:
                # API 调用失败 — 保持 ai_filtered=0，等待下次重试
                _log(_filter_state, f"⚠️ 批次 {i // BATCH + 1} API 失败，跳过，保持待筛选状态")
                time.sleep(1.0)
                continue

            db2 = _conn()
            for aid, title, source in batch:
                if aid in batch_ids:
                    db2.execute("UPDATE news_articles SET ai_filtered=1 WHERE id=?", (aid,))
                    _filter_state["done"] += 1
                else:
                    db2.execute("UPDATE news_articles SET ai_filtered=-1 WHERE id=?", (aid,))
                    _filter_state["done"] += 1
                    _filter_state["failed"] += 1
            safe_commit(db2); db2.close()

            approved = _filter_state["done"] - _filter_state["failed"]
            rejected = _filter_state["failed"]
            _log(_filter_state, f"[{_filter_state['done']}/{len(rows)}] 通过={approved} 拒绝={rejected}")
            time.sleep(0.1)  # 速率限制由 RateLimiter 统一管理

    except Exception as e:
        logger.error(f"batch-ai-filter: {e}")
    finally:
        _filter_state["running"] = False
        _unlock('ai_filter')
        task_state.finish('ai_filter', success=True)


@router.post("/batch-ai-filter")
def start_batch_ai_filter():
    """启动 AI 预筛选 — 批量判断文章标题是否值得缓存。"""
    global _filter_state
    if _filter_state.get("running"):
        return {"ok": False, "message": "AI 筛选已在运行中"}
    ok, msg = _check_and_lock('ai_filter')
    if not ok:
        return {"ok": False, "message": msg}
    db = _conn()
    n = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status = 'pending'
          AND (ai_filtered = 0)
    """).fetchone()[0]
    db.close()
    task_state.init_state('ai_filter', total=n)
    threading.Thread(target=_batch_ai_filter, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 预筛选，预计 {n} 篇", "pending": n}


@router.get("/batch-ai-filter/status")
def get_batch_ai_filter_status():
    """查询 AI 预筛选进度。"""
    return dict(_filter_state)


def _hp_check(aid: int) -> bool:
    """检查文章是否人工已处理"""
    db = _conn()
    r = db.execute("SELECT human_processed FROM news_articles WHERE id=?", (aid,)).fetchone()
    db.close()
    return bool(r and r[0])


# ── 端点 ─────────────────────────────────────────

def _batch_status(state, total_label: str, done_label: str):
    """通用的批量进度查询"""
    return dict(state)

@router.post("/batch-keywords")
def start_batch_keywords():
    global _kw_state
    if _kw_state.get("running"): return {"ok": False, "message": "关键词提取已在运行中"}
    ok, msg = _check_and_lock('keywords')
    if not ok: return {"ok": False, "message": msg}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM news_articles WHERE content_status IN ('fetched', 'translated') AND (ai_keywords IS NULL OR ai_keywords='')").fetchone()[0]; db.close()
    task_state.init_state('keywords', total=n)
    threading.Thread(target=_batch_ai_keywords, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 关键词提取，预计 {n} 篇", "pending": n}

@router.post("/batch-classify")
def start_batch_classify():
    global _cls_state
    if _cls_state.get("running"): return {"ok": False, "message": "分类已在运行中"}
    ok, msg = _check_and_lock('classify')
    if not ok: return {"ok": False, "message": msg}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM news_articles WHERE content_status IN ('fetched', 'translated') AND (ai_category IS NULL OR ai_category='')").fetchone()[0]; db.close()
    task_state.init_state('classify', total=n)
    threading.Thread(target=_batch_ai_classify, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 分类，预计 {n} 篇", "pending": n}

@router.post("/batch-score")
def start_batch_score():
    global _score_state
    if _score_state.get("running"): return {"ok": False, "message": "评分已在运行中"}
    ok, msg = _check_and_lock('score')
    if not ok: return {"ok": False, "message": msg}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM news_articles WHERE content_status IN ('fetched', 'translated') AND (ai_priority_score IS NULL OR ai_priority_score=0.0)").fetchone()[0]; db.close()
    task_state.init_state('score', total=n)
    threading.Thread(target=_batch_ai_score, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 评分，预计 {n} 篇", "pending": n}

@router.post("/batch-recluster")
def start_batch_recluster():
    global _recluster_state
    if _recluster_state.get("running"): return {"ok": False, "message": "重聚类已在运行中"}
    ok, msg = _check_and_lock('recluster')
    if not ok: return {"ok": False, "message": msg}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM news_articles a LEFT JOIN news_article_events ae ON a.id=ae.article_id WHERE ae.article_id IS NULL AND a.content_status IN ('fetched', 'translated')").fetchone()[0]; db.close()
    task_state.init_state('recluster', total=n)
    threading.Thread(target=_batch_ai_recluster, daemon=True).start()
    return {"ok": True, "message": f"启动智能重聚类，预计 {n} 篇", "pending": n}

@router.post("/batch-summarize-events")
def start_batch_summarize_events():
    global _evt_sum_state
    if _evt_sum_state.get("running"): return {"ok": False, "message": "事件摘要已在运行中"}
    ok, msg = _check_and_lock('summarize_events')
    if not ok: return {"ok": False, "message": msg}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM events WHERE article_count>=2 AND (ai_summary IS NULL OR ai_summary='')").fetchone()[0]; db.close()
    task_state.init_state('summarize_events', total=n)
    threading.Thread(target=_batch_ai_summarize_events, daemon=True).start()
    return {"ok": True, "message": f"启动事件摘要，预计 {n} 个事件", "pending": n}

@router.get("/batch-keywords/status")
def get_batch_keywords_status(): return dict(_kw_state)
@router.get("/batch-classify/status")
def get_batch_classify_status(): return dict(_cls_state)
@router.get("/batch-score/status")
def get_batch_score_status(): return dict(_score_state)
@router.get("/batch-recluster/status")
def get_batch_recluster_status(): return dict(_recluster_state)
@router.get("/batch-summarize-events/status")
def get_batch_summarize_events_status(): return dict(_evt_sum_state)


@router.post("/batch-rank-events")
def start_batch_rank_events():
    global _rank_state
    if _rank_state.get("running"): return {"ok": False, "message": "事件排序已在运行中"}
    ok, msg = _check_and_lock('rank_events')
    if not ok: return {"ok": False, "message": msg}
    task_state.init_state('rank_events')
    threading.Thread(target=_batch_ai_rank_events, daemon=True).start()
    return {"ok": True, "message": "启动全景图事件优先级排序"}

@router.get("/batch-rank-events/status")
def get_batch_rank_events_status(): return dict(_rank_state)


# ═════════════════════════════════════════════════════════
# 批量 AI 内容清洗 — 提取纯净文章正文
# ═════════════════════════════════════════════════════════

def _batch_clean():
    """批量清洗所有已缓存文章，LLM 提取纯净正文（去广告/导航/侧栏）。"""
    global _clean_state
    _clean_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}
    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title, local_path FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
            AND (ai_cleaned_content IS NULL OR ai_cleaned_content = '')
            ORDER BY id DESC
        """).fetchall()
        db.close()
        if not rows:
            _clean_state["running"] = False
            _log(_clean_state, "所有文章已完成内容清洗")
            return
        _clean_state["total"] = len(rows)
        _log(_clean_state, f"待清洗 {len(rows)} 篇文章")

        from ai_client import clean_article_content
        from config import config
        from api.news import _sanitize_html
        import os, time

        cache_dir = config.content_cache_path

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str]] = []

        for idx, (aid, title, local_path) in enumerate(rows, 1):
            _clean_state["current"] = f"#{aid} {title[:50]}"
            html_path = os.path.join(cache_dir, os.path.basename(local_path))
            if not os.path.isfile(html_path):
                _log(_clean_state, f"#{aid} ⚠️ 文件不存在")
                _clean_state["done"] += 1
                # 写入标记避免下次重复查询，陷入无限循环
                db2 = _conn()
                db2.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:FILE_MISSING]' WHERE id=?", (aid,))
                db2.commit()
                db2.close()
                continue

            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    html = f.read()
            except Exception:
                _log(_clean_state, f"#{aid} ⚠️ 读取失败")
                _clean_state["done"] += 1
                db2 = _conn()
                db2.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:READ_FAILED]' WHERE id=?", (aid,))
                db2.commit()
                db2.close()
                continue

            if len(html) < 200:
                _log(_clean_state, f"#{aid} ⚠️ HTML 过短 ({len(html)} 字符)")
                _clean_state["done"] += 1
                db2 = _conn()
                db2.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:HTML_TOO_SHORT]' WHERE id=?", (aid,))
                db2.commit()
                db2.close()
                continue

            html = _sanitize_html(html)
            try:
                cleaned = clean_article_content(html)
                if cleaned and len(cleaned) > 100:
                    cleaned = _sanitize_html(cleaned)
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (cleaned, aid))
                    db2.commit()
                    db2.close()
                    _log(_clean_state, f"#{aid} ✅ {title[:40]} [{len(cleaned)//1024}KB]")
                    _clean_state["done"] += 1
                else:
                    _log(_clean_state, f"#{aid} ⚠️ AI 返回空")
                    _clean_state["done"] += 1
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:AI_EMPTY]' WHERE id=?", (aid,))
                    db2.commit()
                    db2.close()
            except Exception as e:
                if _is_request_timeout_error(e) and _queue_timeout_retry(
                    _clean_state, aid, retry_counts, task_type='clean'
                ):
                    retry_queue.append((aid, title, html))
                    continue
                _log(_clean_state, f"#{aid} ❌ {str(e)[:120]}")
                _clean_state["failed"] += 1

            if idx < len(rows):
                time.sleep(5)

        # 重试队列：处理超时的文章
        for aid, title, html in retry_queue:
            _clean_state["current"] = f"#{aid} {title[:50]}"
            _log(_clean_state, f"#{aid} 🔄 重试清洗...")
            try:
                cleaned = clean_article_content(html)
                if cleaned and len(cleaned) > 100:
                    cleaned = _sanitize_html(cleaned)
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (cleaned, aid))
                    db2.commit()
                    db2.close()
                    _log(_clean_state, f"#{aid} ✅ {title[:40]} [{len(cleaned)//1024}KB]")
                    _clean_state["done"] += 1
                else:
                    _log(_clean_state, f"#{aid} ⚠️ 重试后 AI 返回空")
                    _clean_state["done"] += 1
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_cleaned_content='[ERR:AI_EMPTY]' WHERE id=?", (aid,))
                    db2.commit()
                    db2.close()
            except Exception as e:
                _log(_clean_state, f"#{aid} ❌ 重试失败: {str(e)[:120]}")
                _clean_state["failed"] += 1
            time.sleep(3)  # 重试间短延迟

    except Exception as e:
        _log(_clean_state, f"清洗异常: {str(e)[:200]}")
    finally:
        _clean_state["running"] = False
        _clean_state["current"] = (
            f"完成: {_clean_state['done']} 成功, {_clean_state['failed']} 失败"
        )
        _unlock('clean')
        task_state.finish('clean', success=True)


@router.post("/batch-clean")
def start_batch_clean():
    """批量 AI 清洗所有已缓存文章内容。"""
    global _clean_state
    if _clean_state.get("running"):
        return {"ok": False, "message": "内容清洗已在运行中", "state": _clean_state}
    ok, msg = _check_and_lock('clean')
    if not ok:
        return {"ok": False, "message": msg}
    db = _conn()
    pending = db.execute("""
        SELECT COUNT(*) FROM news_articles
        WHERE content_status IN ('fetched', 'translated')
        AND (ai_cleaned_content IS NULL OR ai_cleaned_content = '')
    """).fetchone()[0]
    db.close()
    task_state.init_state('clean', total=pending)
    threading.Thread(target=_batch_clean, daemon=True).start()
    return {"ok": True, "message": f"启动内容清洗，预计 {pending} 篇", "pending": pending}


@router.get("/batch-clean/status")
def get_batch_clean_status():
    if _clean_state.get("running"):
        db = _conn()
        total = db.execute("""
            SELECT COUNT(*) FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
            AND (ai_cleaned_content IS NULL OR ai_cleaned_content = '')
        """).fetchone()[0]
        done = db.execute("""
            SELECT COUNT(*) FROM news_articles
            WHERE ai_cleaned_content != '' AND ai_cleaned_content IS NOT NULL
        """).fetchone()[0]
        db.close()
        return {"running": True, "total": total + done, "done": done, "failed": 0,
                "current": _clean_state["current"], "log": _clean_state["log"]}
    return dict(_clean_state)


# ═════════════════════════════════════════════════════════
# 统一全流程 — 清洗 → 翻译 → 关键词 → 分类 → 评分 → 分析 → 聚类 → 摘要 → 链
# ═════════════════════════════════════════════════════════

_full_state = _new_state()

def _batch_ai_full():
    """顺序执行全部 AI 处理步骤。每步检查是否有待处理项，无则跳过。"""
    global _full_state
    _full_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "steps": []}
    step_names = ["内容清洗", "翻译", "AI 分析", "关键词提取", "智能分类", "优先级评分", "事件重聚类", "事件摘要", "全景图排序", "构筑逻辑链"]
    steps = [
        ("内容清洗", _batch_clean, _clean_state),
        ("翻译", _batch_translate, _translate_state),
        ("AI 分析", _batch_analyze, _analyze_state),
        ("关键词提取", _batch_ai_keywords, _kw_state),
        ("智能分类", _batch_ai_classify, _cls_state),
        ("优先级评分", _batch_ai_score, _score_state),
        ("事件重聚类", _batch_ai_recluster, _recluster_state),
        ("事件摘要", _batch_ai_summarize_events, _evt_sum_state),
        ("全景图排序", _batch_ai_rank_events, _rank_state),
        ("构筑逻辑链", _build_logic_chains, _chain_state),
    ]
    # 初始化所有步骤状态
    _full_state["steps"] = [{"name": nm, "status": "pending"} for nm in step_names]
    _full_state["total"] = len(steps)
    _log(_full_state, f"🚀 启动全流程 AI 处理 — 共 {len(steps)} 步")
    for idx, (label, fn, st) in enumerate(steps, 1):
        _log(_full_state, f"━━━ 步骤 {idx}/{len(steps)}: {label} ━━━")
        _full_state["current"] = f"{label} — 执行中..."
        _full_state["done"] = idx - 1
        if _full_state["steps"]:
            _full_state["steps"][idx - 1]["status"] = "running"
        try:
            fn()
            # 等待子任务完成（子任务的 running 为 False 即完成）
            while st.get("running"):
                time.sleep(5)
            _log(_full_state, f"✅ {label} 完成")
            if _full_state["steps"]:
                _full_state["steps"][idx - 1]["status"] = "done"
        except Exception as e:
            _log(_full_state, f"❌ {label} 失败: {str(e)[:100]}")
            if _full_state["steps"]:
                _full_state["steps"][idx - 1]["status"] = "failed"
        _full_state["done"] = idx
    _full_state["running"] = False
    _full_state["current"] = "全部完成"
    _unlock('ai_full')
    task_state.finish('ai_full', success=True)


@router.post("/batch-ai-full")
def start_batch_ai_full():
    """一键启动全流程 AI 处理。"""
    global _full_state
    if _full_state.get("running"):
        return {"ok": False, "message": "全流程已在运行中"}
    ok, msg = _check_and_lock('ai_full')
    if not ok:
        return {"ok": False, "message": msg}
    task_state.init_state('ai_full', total=10)
    threading.Thread(target=_batch_ai_full, daemon=True).start()
    return {"ok": True, "message": "启动全流程 AI 处理 — 清洗→翻译→分析→关键词→分类→评分→聚类→摘要→链"}


@router.get("/batch-ai-full/status")
def get_batch_ai_full_status():
    return dict(_full_state)
