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

def _queue_retry(state, item_id, retry_counts, reason: str = '', max_retries: int = 4, task_type: str = '') -> bool:
    """通用重试队列：超时、空返回、异常都回池子，最多重试 max_retries 次。"""
    count = retry_counts.get(item_id, 0) + 1
    retry_counts[item_id] = count
    if count <= max_retries:
        label = f"{reason}，" if reason else ""
        _log(state, f"#{item_id} {label}排入重试队列 ({count}/{max_retries + 1})", task_type)
        return True
    _log(state, f"#{item_id} 已达最大重试次数 ({count})，放弃", task_type)
    return False


# 兼容旧名
def _queue_timeout_retry(state, item_id, retry_counts, max_retries=4, task_type=''):
    return _queue_retry(state, item_id, retry_counts, reason='Request Timed Out', max_retries=max_retries, task_type=task_type)

def _new_state() -> dict:
    """创建后台任务进度状态。"""
    return {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": [],
            "cancelled": False}


def _check_cancelled(state: dict) -> bool:
    """检查任务是否被取消，如已取消则更新状态。"""
    if state.get("cancelled"):
        state["running"] = False
        state["current"] = "已取消"
        return True
    return False


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


def _force_reset(task_type: str, state: dict) -> dict:
    """强制重置卡住的任务状态 — 清除内存状态、锁、DB 持久化。

    用于任务线程已死亡但状态未清理的场景（进程崩溃恢复、未捕获异常等）。
    返回操作结果信息。
    """
    import json
    was_running = state.get("running", False)
    state["running"] = False
    state["current"] = "已强制重置"
    state.setdefault("log", []).append(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ 管理员强制重置")
    task_lock.release(task_type)
    task_state.clear(task_type)
    logger.warning(f"[ForceReset] Task '{task_type}' force-reset (was_running={was_running})")
    return {"ok": True, "message": f"任务 '{task_type}' 已强制重置", "was_running": was_running}


def _reset_state(state: dict, **extra) -> dict:
    """就地重置任务状态 dict，保持引用不丢失（避免 _batch_ai_full 的 st 悬空）。"""
    state.clear()
    state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": [],
                  "cancelled": False})
    if extra:
        state.update(extra)
    return state

def _conn():
    """创建带超时配置的数据库连接，防止 WAL 并发写锁导致数据丢失。"""
    return get_db_connection(config.db_path)


# ═════════════════════════════════════════════════════════
# 批量翻译
# ═════════════════════════════════════════════════════════

def _batch_translate():
    global _translate_state
    _reset_state(_translate_state)

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
            if _check_cancelled(_translate_state):
                _log(_translate_state, "🛑 翻译任务已取消")
                break
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
                # translated_content 也填入原文，避免下次循环重复扫描
                db2.execute("UPDATE news_articles SET text_content=?, translated_content=?, content_lang=? WHERE id=?",
                           (html, html, lang, aid))
                safe_commit(db2)
                db2.close()
                _log(_translate_state, f"#{aid} ⏭️ 非英文，标记已处理")
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
    _reset_state(_analyze_state)

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
            if _check_cancelled(_analyze_state):
                _log(_analyze_state, "🛑 分析任务已取消")
                break
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
    _reset_state(_chain_state, total_groups=0, chains_created=0)

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
    _reset_state(_rank_state)
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
    # 在启动线程前设置运行状态，避免前端轮询时拿到 running=false 提前停止轮询
    _translate_state["running"] = True
    _translate_state["total"] = pending
    _translate_state["current"] = "启动中..."
    _translate_state["running"] = True
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
        db.close()
        return {"running": True, "total": total,
                "done": _translate_state.get("done", 0),
                "failed": _translate_state.get("failed", 0),
                "current": _translate_state["current"], "log": _translate_state["log"],
                "cancelled": _translate_state.get("cancelled", False)}
    return dict(_translate_state)


@router.post("/batch-translate/cancel")
def cancel_batch_translate():
    """取消正在运行的批量翻译任务。"""
    global _translate_state
    if not _translate_state.get("running"):
        return {"ok": False, "message": "没有正在运行的翻译任务"}
    _translate_state["cancelled"] = True
    _log(_translate_state, "🛑 收到取消请求 — 完成当前文章后停止")
    return {"ok": True, "message": "翻译任务已取消"}


@router.post("/batch-translate/force-reset")
def force_reset_batch_translate():
    """强制重置卡住的翻译任务。"""
    global _translate_state
    return _force_reset('translate', _translate_state)


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
    _analyze_state["running"] = True
    _analyze_state["total"] = pending
    _analyze_state["current"] = "启动中..."
    _analyze_state["running"] = True
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
        db.close()
        return {"running": True, "total": total,
                "done": _analyze_state.get("done", 0),
                "failed": _analyze_state.get("failed", 0),
                "current": _analyze_state["current"], "log": _analyze_state["log"],
                "cancelled": _analyze_state.get("cancelled", False)}
    return dict(_analyze_state)


@router.post("/batch-analyze/cancel")
def cancel_batch_analyze():
    """取消正在运行的批量分析任务。"""
    global _analyze_state
    if not _analyze_state.get("running"):
        return {"ok": False, "message": "没有正在运行的分析任务"}
    _analyze_state["cancelled"] = True
    _log(_analyze_state, "🛑 收到取消请求 — 完成当前文章后停止")
    return {"ok": True, "message": "分析任务已取消"}


@router.post("/batch-analyze/force-reset")
def force_reset_batch_analyze():
    """强制重置卡住的分析任务。"""
    global _analyze_state
    return _force_reset('analyze', _analyze_state)


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
    _chain_state["running"] = True
    _chain_state["current"] = "初始分组中..."
    _chain_state["running"] = True
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
    _reset_state(_kw_state)
    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title,
                   COALESCE(NULLIF(ai_cleaned_content, ''), text_content) as content,
                   source
            FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
              AND (ai_keywords IS NULL OR ai_keywords = '')
            ORDER BY id DESC
        """).fetchall(); db.close()
        if not rows: _kw_state["running"] = False; return
        _kw_state["total"] = len(rows)
        _log(_kw_state, f"待提取关键词 {len(rows)} 篇")
        from ai_client import extract_keywords_ai
        import json as _json

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str, str]] = []

        for idx, (aid, title, text, source) in enumerate(rows, 1):
            if _check_cancelled(_kw_state):
                _log(_kw_state, "🛑 关键词提取已取消")
                break
            _kw_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_kw_state, f"#{aid} ⏭️ 人工已处理"); _kw_state["done"] += 1; continue
            try:
                kws = extract_keywords_ai(title, text, source or "", model=config.simple_model)
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
                if _queue_retry(_kw_state, aid, retry_counts, reason='AI 返回空', task_type='keywords'):
                    retry_queue.append((aid, title, text, source or ""))
                else:
                    _kw_state["failed"] += 1
            _kw_state["done"] += 1
            time.sleep(0.1) if idx < len(rows) else None

        for aid, title, text, source in retry_queue:
            _kw_state["current"] = f"#{aid} {title[:50]}"
            _log(_kw_state, f"#{aid} 🔄 重试关键词提取...")
            try:
                kws = extract_keywords_ai(title, text, source, model=config.simple_model)
                if kws:
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET keywords=?, ai_keywords=? WHERE id=?", (_json.dumps(kws, ensure_ascii=False), _json.dumps(kws, ensure_ascii=False), aid))
                    safe_commit(db2); db2.close()
                    _log(_kw_state, f"#{aid} ✅ {len(kws)} 个关键词: {', '.join(kws[:5])}")
                else:
                    if _queue_retry(_kw_state, aid, retry_counts, reason='重试后仍空', task_type='keywords'):
                        retry_queue.append((aid, title, text, source or ""))
                    else:
                        _kw_state["failed"] += 1
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
    _reset_state(_cls_state)
    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title,
                   COALESCE(NULLIF(ai_cleaned_content, ''), text_content) as content
            FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
              AND (ai_category IS NULL OR ai_category = '')
            ORDER BY id DESC
        """).fetchall(); db.close()
        if not rows: _cls_state["running"] = False; return
        _cls_state["total"] = len(rows)
        _log(_cls_state, f"待分类 {len(rows)} 篇")
        from ai_client import classify_article_ai
        import json as _json

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str]] = []

        for idx, (aid, title, text) in enumerate(rows, 1):
            if _check_cancelled(_cls_state):
                _log(_cls_state, "🛑 分类任务已取消")
                break
            _cls_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_cls_state, f"#{aid} ⏭️ 人工已处理"); _cls_state["done"] += 1; continue
            try:
                r = classify_article_ai(title, text, model=config.simple_model)
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
                if _queue_retry(_cls_state, aid, retry_counts, reason='AI 返回空', task_type='classify'):
                    retry_queue.append((aid, title, text))
                else:
                    _cls_state["failed"] += 1
            _cls_state["done"] += 1
            time.sleep(0.1) if idx < len(rows) else None

        for aid, title, text in retry_queue:
            _cls_state["current"] = f"#{aid} {title[:50]}"
            _log(_cls_state, f"#{aid} 🔄 重试分类...")
            try:
                r = classify_article_ai(title, text, model=config.simple_model)
                if r:
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_category=?, ai_tags=? WHERE id=?", (r.get("category",""), _json.dumps(r.get("tags",[]), ensure_ascii=False), aid))
                    safe_commit(db2); db2.close()
                    _log(_cls_state, f"#{aid} ✅ {r.get('category','?')} — {', '.join(r.get('tags',[])[:3])}")
                else:
                    if _queue_retry(_cls_state, aid, retry_counts, reason='重试后仍空', task_type='classify'):
                        retry_queue.append((aid, title, text))
                    else:
                        _cls_state["failed"] += 1
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
    _reset_state(_score_state)
    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title,
                   COALESCE(NULLIF(ai_cleaned_content, ''), text_content) as content,
                   source, fetched_at
            FROM news_articles
            WHERE content_status IN ('fetched', 'translated')
              AND (ai_priority_score IS NULL OR ai_priority_score = 0.0)
            ORDER BY id DESC
        """).fetchall(); db.close()
        if not rows: _score_state["running"] = False; return
        _score_state["total"] = len(rows)
        _log(_score_state, f"待评分 {len(rows)} 篇")
        from ai_client import score_priority_ai
        from datetime import datetime as _dt

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str, str, str]] = []

        for idx, (aid, title, text, source, fetched_at) in enumerate(rows, 1):
            if _check_cancelled(_score_state):
                _log(_score_state, "🛑 评分任务已取消")
                break
            _score_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_score_state, f"#{aid} ⏭️ 人工已处理"); _score_state["done"] += 1; continue
            try:
                days = max(0, (_dt.now() - _dt.fromisoformat(fetched_at)).days) if fetched_at else 0
            except Exception:
                days = 0
            try:
                r = score_priority_ai(title, text, source or "Unknown", days, model=config.simple_model)
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
                if _queue_retry(_score_state, aid, retry_counts, reason='AI 返回空', task_type='score'):
                    retry_queue.append((aid, title, text, source or "Unknown", fetched_at or ""))
                else:
                    _score_state["failed"] += 1
            _score_state["done"] += 1
            time.sleep(0.1) if idx < len(rows) else None

        for aid, title, text, source, fetched_at in retry_queue:
            _score_state["current"] = f"#{aid} {title[:50]}"
            _log(_score_state, f"#{aid} 🔄 重试评分...")
            try:
                days = max(0, (_dt.now() - _dt.fromisoformat(fetched_at)).days) if fetched_at else 0
            except Exception:
                days = 0
            try:
                r = score_priority_ai(title, text, source, days, model=config.simple_model)
                if r:
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET priority_score=?, priority_label=?, ai_priority_score=? WHERE id=?", (r["score"], r.get("label","medium"), r["score"], aid))
                    safe_commit(db2); db2.close()
                    _log(_score_state, f"#{aid} ✅ {r.get('label','medium')}({r['score']:.0f}) — {r.get('reason','')}")
                else:
                    if _queue_retry(_score_state, aid, retry_counts, reason='重试后仍空', task_type='score'):
                        retry_queue.append((aid, title, text, source, fetched_at))
                    else:
                        _score_state["failed"] += 1
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
    _reset_state(_recluster_state)
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
    _reset_state(_evt_sum_state)
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
    _reset_state(_filter_state)
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
    _filter_state["running"] = True
    _filter_state["total"] = n
    _filter_state["current"] = "启动中..."
    _af_state["running"] = True
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
    _kw_state["running"] = True
    _kw_state["total"] = n
    _kw_state["current"] = "启动中..."
    _kw_state["running"] = True
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
    _cls_state["running"] = True
    _cls_state["total"] = n
    _cls_state["current"] = "启动中..."
    _cls_state["running"] = True
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
    _score_state["running"] = True
    _score_state["total"] = n
    _score_state["current"] = "启动中..."
    _score_state["running"] = True
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
    _recluster_state["running"] = True
    _recluster_state["total"] = n
    _recluster_state["current"] = "启动中..."
    _recluster_state["running"] = True
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
    _evt_sum_state["running"] = True
    _evt_sum_state["total"] = n
    _evt_sum_state["current"] = "启动中..."
    _evt_sum_state["running"] = True
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
    _rank_state["running"] = True
    _rank_state["current"] = "启动中..."
    _rank_state["running"] = True
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
    _reset_state(_clean_state)
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
        import os, time

        cache_dir = config.content_cache_path

        retry_counts: dict[int, int] = {}
        retry_queue: list[tuple[int, str, str]] = []

        for idx, (aid, title, local_path) in enumerate(rows, 1):
            if _check_cancelled(_clean_state):
                _log(_clean_state, "🛑 任务已取消")
                break
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

            # 直接将原始 HTML 传给 AI — AI 的 system prompt 已明确要求移除
            # 脚本/广告/导航等非正文元素，本地预清理反而破坏结构、浪费算力
            # Nex-N2-Pro 不支持 SSE 流式，改用前后日志记录耗时
            _log(_clean_state, f"#{aid} 📡 AI 清洗中... (HTML {len(html)//1024}KB)")
            try:
                t0 = time.time()
                cleaned = clean_article_content(html)
                elapsed = time.time() - t0
                if cleaned and len(cleaned) > 100:
                    _log(_clean_state, f"#{aid} 📡 完成 ({elapsed:.0f}s, 输出 {len(cleaned)//1024}KB)")
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (cleaned, aid))
                    db2.commit()
                    db2.close()
                    _log(_clean_state, f"#{aid} ✅ {title[:40]} [{len(cleaned)//1024}KB]")
                    _clean_state["done"] += 1
                else:
                    _log(_clean_state, f"#{aid} ⚠️ AI 返回空 ({elapsed:.0f}s)")
                    if _queue_retry(_clean_state, aid, retry_counts, reason='AI 返回空', task_type='clean'):
                        retry_queue.append((aid, title, html))
                    else:
                        _clean_state["failed"] += 1
            except Exception as e:
                reason = 'Request Timed Out' if _is_request_timeout_error(e) else type(e).__name__
                if _queue_retry(_clean_state, aid, retry_counts, reason=reason, task_type='clean'):
                    retry_queue.append((aid, title, html))
                else:
                    _log(_clean_state, f"#{aid} ❌ {str(e)[:120]}")
                    _clean_state["failed"] += 1

            if idx < len(rows):
                time.sleep(5)

        # 重试队列：超时 / 空返回 / 异常统一回池，while 循环支持重新入队
        while retry_queue:
            if _check_cancelled(_clean_state):
                break
            aid, title, html = retry_queue.pop(0)
            _clean_state["current"] = f"#{aid} {title[:50]}"
            _log(_clean_state, f"#{aid} 🔄 重试清洗...")
            try:
                cleaned = clean_article_content(html)
                if cleaned and len(cleaned) > 100:
                    db2 = _conn()
                    db2.execute("UPDATE news_articles SET ai_cleaned_content=? WHERE id=?", (cleaned, aid))
                    db2.commit()
                    db2.close()
                    _log(_clean_state, f"#{aid} ✅ {title[:40]} [{len(cleaned)//1024}KB]")
                    _clean_state["done"] += 1
                else:
                    if _queue_retry(_clean_state, aid, retry_counts, reason='重试后仍空', task_type='clean'):
                        retry_queue.append((aid, title, html))
                    else:
                        _clean_state["failed"] += 1
            except Exception as e:
                reason = 'Request Timed Out' if _is_request_timeout_error(e) else type(e).__name__
                if _queue_retry(_clean_state, aid, retry_counts, reason=reason, task_type='clean'):
                    retry_queue.append((aid, title, html))
                else:
                    _log(_clean_state, f"#{aid} ❌ 重试耗尽: {str(e)[:120]}")
                    _clean_state["failed"] += 1
            time.sleep(5)

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
    _clean_state["running"] = True
    _clean_state["total"] = pending
    _clean_state["current"] = "启动中..."
    _clean_state["running"] = True
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
        db.close()
        return {"running": True, "total": total,
                "done": _clean_state.get("done", 0),
                "failed": _clean_state.get("failed", 0),
                "current": _clean_state["current"], "log": _clean_state["log"],
                "cancelled": _clean_state.get("cancelled", False)}
    return dict(_clean_state)


@router.post("/batch-clean/cancel")
def cancel_batch_clean():
    """取消正在运行的内容清洗任务。"""
    global _clean_state
    if not _clean_state.get("running"):
        return {"ok": False, "message": "没有正在运行的清洗任务"}
    _clean_state["cancelled"] = True
    _log(_clean_state, "🛑 收到取消请求 — 完成当前文章后停止")
    return {"ok": True, "message": "清洗任务已取消"}


@router.post("/batch-clean/force-reset")
def force_reset_batch_clean():
    """强制重置卡住的清洗任务 — 清除内存状态、锁、DB 持久化。"""
    global _clean_state
    return _force_reset('clean', _clean_state)


# ═════════════════════════════════════════════════════════
# 统一全流程 — 清洗 → 翻译 → 关键词 → 分类 → 评分 → 分析 → 聚类 → 摘要 → 链
# ═════════════════════════════════════════════════════════

_full_state = _new_state()

def _batch_ai_full():
    """三轨并行管道 — Nex(清洗) ∥ Qwen(关键/分类/评分) ∥ DeepSeek(翻译/分析/聚类/摘要/排序/链)。"""
    global _full_state
    _reset_state(_full_state, steps=[])

    # ── 三轨定义 ──────────────────────────────────────────────
    # 各轨独立速率限制，互不阻塞
    qwen_steps = [
        ("关键词提取",    _batch_ai_keywords,         _kw_state,         'keywords'),
        ("智能分类",      _batch_ai_classify,         _cls_state,        'classify'),
        ("优先级评分",    _batch_ai_score,            _score_state,      'score'),
    ]
    deepseek_steps = [
        ("翻译",          _batch_translate,           _translate_state,  'translate'),
        ("AI 分析",       _batch_analyze,             _analyze_state,    'analyze'),
        ("事件重聚类",    _batch_ai_recluster,        _recluster_state,  'recluster'),
        ("事件摘要",      _batch_ai_summarize_events, _evt_sum_state,    'summarize_events'),
        ("全景图排序",    _batch_ai_rank_events,      _rank_state,       'rank_events'),
        ("构筑逻辑链",    _build_logic_chains,        _chain_state,      'build_chains'),
    ]
    step_names = ["内容清洗"] + [nm for nm, _, _, _ in deepseek_steps] + [nm for nm, _, _, _ in qwen_steps]
    _full_state["steps"] = [{"name": nm, "status": "pending"} for nm in step_names]
    _full_state["total"] = len(step_names)
    _log(_full_state, f"🚀 三轨并行 — Nex(清洗) ∥ DSv3.2(翻译+分析+链) ∥ Qwen(关键词+分类+评分)")

    import threading as _th

    # ── 辅助：运行顺序步骤列表，清洗产出新数据后循环补入 ───────
    def _run_seq(label_prefix: str, seq: list, base_idx: int):
        idle_rounds = 0  # 连续无工作的轮数
        while not _full_state.get("cancelled") and idle_rounds < 3:
            had_work = False
            for i, (label, fn, st, lock_name) in enumerate(seq):
                si = base_idx + i
                if _check_cancelled(_full_state):
                    return
                # 执行步骤（_batch_* 无待处理项时瞬间返回）
                if _full_state["steps"]:
                    _full_state["steps"][si]["status"] = "running"
                try:
                    prev_done = st.get("done", 0)
                    fn()
                    while st.get("running"):
                        if _full_state.get("cancelled") or st.get("cancelled"):
                            st["cancelled"] = True; break
                        time.sleep(3)
                    if st.get("done", 0) > prev_done:
                        had_work = True
                    status = "skipped" if st.get("cancelled") else "done"
                    if _full_state["steps"]:
                        _full_state["steps"][si]["status"] = status
                except Exception as e:
                    _log(_full_state, f"┣ [{label_prefix}] {label} ❌ {str(e)[:120]}")
                    if _full_state["steps"]:
                        _full_state["steps"][si]["status"] = "failed"
                    try: _force_reset(lock_name, st)
                    except: pass
            # 本轮无新工作 → 等待 30s 让清洗产出新数据
            if not had_work:
                idle_rounds += 1
                if idle_rounds < 3:
                    time.sleep(30)
            else:
                idle_rounds = 0

    # ── 轨道 1: 清洗 (Nex) ───────────────────────────────────
    _full_state["steps"][0]["status"] = "running"
    ct = _th.Thread(target=_batch_clean, daemon=True)
    ct.start()
    _log(_full_state, "┣ [Nex] 内容清洗 — 已启动")

    # ── 轨道 2: DeepSeek (翻译→分析→聚类→摘要→排序→链) ─────
    ds_idx = 1  # after clean
    dt = _th.Thread(target=_run_seq, args=("DS", deepseek_steps, ds_idx), daemon=True)
    dt.start()
    _log(_full_state, "┣ [DS] 翻译+分析+聚类+摘要+排序+链 — 已启动")

    # ── 轨道 3: Qwen (关键词→分类→评分) ─────────────────────
    qw_idx = ds_idx + len(deepseek_steps)
    qt = _th.Thread(target=_run_seq, args=("Qwen", qwen_steps, qw_idx), daemon=True)
    qt.start()
    _log(_full_state, "┣ [Qwen] 关键词+分类+评分 — 已启动")

    # ── 等待所有轨道完成 ─────────────────────────────────────
    ct.join()
    if _full_state["steps"]:
        _full_state["steps"][0]["status"] = "skipped" if _clean_state.get("cancelled") else "done"
    _log(_full_state, "┣ [Nex] 清洗完成")
    dt.join()
    _log(_full_state, "┣ [DS] DeepSeek 管道完成")
    qt.join()
    _log(_full_state, "┣ [Qwen] Qwen 管道完成")

    _full_state["running"] = False
    _full_state["current"] = "全部完成"
    _full_state["done"] = len(step_names)
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
    # 在启动线程前设置运行状态，避免前端轮询时拿到 running=false 提前停止轮询
    _full_state["running"] = True
    _full_state["total"] = 10
    _full_state["current"] = "启动中..."
    _full_state["running"] = True
    threading.Thread(target=_batch_ai_full, daemon=True).start()
    return {"ok": True, "message": "启动全流程 AI 处理 — 清洗→翻译→分析→关键词→分类→评分→聚类→摘要→链"}


@router.post("/batch-ai-full/cancel")
def cancel_batch_ai_full():
    """取消全流程 — 传播到当前步骤。"""
    global _full_state, _clean_state, _translate_state, _analyze_state
    if not _full_state.get("running"):
        return {"ok": False, "message": "没有正在运行的全流程任务"}
    _full_state["cancelled"] = True
    # 传播到各步骤
    for st in [_clean_state, _translate_state, _analyze_state,
               _kw_state, _cls_state, _score_state, _recluster_state,
               _evt_sum_state, _rank_state, _chain_state]:
        st["cancelled"] = True
    _log(_full_state, "🛑 收到取消请求 — 完成当前步骤后停止")
    return {"ok": True, "message": "全流程任务已取消"}


@router.post("/batch-ai-full/force-reset")
def force_reset_batch_ai_full():
    """强制重置卡住的全流程任务 — 传播到所有步骤。"""
    global _full_state, _clean_state, _translate_state, _analyze_state
    global _kw_state, _cls_state, _score_state, _recluster_state
    global _evt_sum_state, _rank_state, _chain_state
    # 重置所有子步骤
    for task_type, st in [('clean', _clean_state), ('translate', _translate_state),
                           ('analyze', _analyze_state), ('keywords', _kw_state),
                           ('classify', _cls_state), ('score', _score_state),
                           ('recluster', _recluster_state),
                           ('summarize_events', _evt_sum_state),
                           ('rank_events', _rank_state), ('build_chains', _chain_state)]:
        _force_reset(task_type, st)
    return _force_reset('ai_full', _full_state)




@router.get("/batch-ai-full/status")
def get_batch_ai_full_status():
    return dict(_full_state)
