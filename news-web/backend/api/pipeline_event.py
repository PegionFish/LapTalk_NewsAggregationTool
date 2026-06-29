"""事件级管线 API — 聚类→摘要→逻辑链。凌晨 1:00 定时 / 管理员手动触发。"""
import threading, logging, time
from datetime import datetime
from fastapi import APIRouter

from config import config
from utils.task_lock import task_lock
from utils.task_state import task_state
from utils.db import get_db_connection, safe_commit
from api.dashboard import DashboardStream

router = APIRouter(prefix="/api/pipeline/event", tags=["pipeline-event"])
logger = logging.getLogger(__name__)

_event_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "",
                "log": [], "steps": [], "cancelled": False}
_recl_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "cancelled": False}
_es_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "cancelled": False}
_chain_state = {"running": False, "total_groups": 0, "chains_created": 0, "current": "", "log": [], "cancelled": False}


def _nightly():
    """线性执行两个阶段：摘要 → 逻辑链。
    事件聚类已在文章处理时完成（process_article 内 AI 语义匹配）。
    """
    global _event_state, _es_state, _chain_state

    steps = [
        ("事件摘要", _run_summarize, _es_state, 'summarize_events'),
        ("逻辑链构建", _run_build_chains, _chain_state, 'build_chains'),
    ]

    _event_state["running"] = True
    _event_state["steps"] = [{"name": name, "status": "pending"} for name, _, _, _ in steps]
    _event_state["total"] = len(steps)
    _event_state["log"] = []
    any_failed = False

    try:
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
                    # 同步子步骤进度到步骤显示
                    _event_state["steps"][i]["done"] = st.get("done", 0)
                    _event_state["steps"][i]["total"] = st.get("total", 0)
                    _event_state["steps"][i]["current"] = st.get("current", "")
                    DashboardStream.publish("event_step", {
                        "step": name, "status": "running",
                        "done": st.get("done", 0), "total": st.get("total", 0),
                        "current": st.get("current", "")
                    })
                    time.sleep(2)
                _event_state["steps"][i]["status"] = "done"
                _event_state["steps"][i]["done"] = st.get("done", 0)
                _event_state["steps"][i]["total"] = st.get("total", 0)
                _event_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {name} 完成 ({st.get('done', 0)}/{st.get('total', 0)})")
            except Exception as e:
                _event_state["steps"][i]["status"] = "failed"
                _event_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {name}: {e}")
                logger.error(f"nightly {name}: {e}")
                any_failed = True
    finally:
        DashboardStream.publish("event_done", {"steps": _event_state["steps"]})
        _event_state["running"] = False
        _event_state["current"] = "完成"
        task_lock.release('event')
        task_state.finish('event', success=not any_failed)


def _run_recluster():
    """[已废弃] 旧版事件重聚类 — 事件聚类已下沉到 process_article() 中的 AI 语义匹配。
    保留此函数供手动触发，但不参与 nightly 定时任务。
    """
    global _recl_state
    _recl_state.clear()
    _recl_state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "cancelled": False})
    try:
        from ai_client import match_article_to_events_ai
        from db.news_db import title_similarity
        db = get_db_connection(config.db_path)
        unlinked = db.execute(
            "SELECT a.id, a.title FROM news_articles a "
            "LEFT JOIN news_article_events ae ON a.id = ae.article_id "
            "WHERE ae.article_id IS NULL AND a.content_status IN ('fetched', 'translated')"
        ).fetchall()
        events = db.execute("SELECT id, title FROM events WHERE status='active'").fetchall()
        _recl_state["total"] = len(unlinked)
        _recl_state["log"].append(f"待聚类 {len(unlinked)} 篇 → {len(events)} 个活跃事件")
        db.close()
        if not unlinked:
            _recl_state["running"] = False
            return
        for aid, art_title in unlinked:
            if _recl_state.get("cancelled"):
                break
            _recl_state["current"] = f"#{aid} {art_title[:50]}"
            scored = [(title_similarity(art_title, etitle), eid, etitle) for eid, etitle in events]
            scored.sort(key=lambda x: x[0], reverse=True)
            candidates = [(eid, etitle) for _, eid, etitle in scored[:50]]
            try:
                r = match_article_to_events_ai(art_title, candidates)
                if r and r.get("event_id"):
                    db2 = get_db_connection(config.db_path)
                    db2.execute("INSERT OR IGNORE INTO news_article_events (article_id, event_id) VALUES (?,?)",
                                (aid, r["event_id"]))
                    safe_commit(db2)
                    db2.close()
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
    _es_state.clear()
    _es_state.update({"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "log": [], "cancelled": False})
    try:
        from ai_client import generate_event_summary_ai
        db = get_db_connection(config.db_path)
        # 用 JOIN 确保事件实际有 >= 2 篇文章，避免 article_count 缓存不准
        events = db.execute("""
            SELECT e.id, COUNT(ae.article_id) as cnt
            FROM events e
            JOIN news_article_events ae ON ae.event_id = e.id
            WHERE e.article_count >= 2 AND (e.ai_summary IS NULL OR e.ai_summary = '')
            GROUP BY e.id
            HAVING cnt >= 2
        """).fetchall()
        _es_state["total"] = len(events)
        logger.info(f"summarize: {len(events)} 个事件待生成摘要（≥2篇关联文章）")
        db.close()
        for (eid, _cnt) in events:
            if _es_state.get("cancelled"):
                break
            _es_state["current"] = f"事件#{eid}"
            db2 = get_db_connection(config.db_path)
            titles = [r[0] for r in db2.execute(
                "SELECT a.title FROM news_articles a "
                "JOIN news_article_events ae ON ae.article_id = a.id "
                "WHERE ae.event_id = ? LIMIT 20", (eid,)
            ).fetchall()]
            db2.close()
            if len(titles) < 2:
                _es_state["failed"] += 1  # 理论上不应到达（HAVING 已过滤），但防御性保留
                continue
            try:
                block = "\n".join(f"- {t}" for t in titles)
                summary = generate_event_summary_ai(block)
                if summary:
                    db3 = get_db_connection(config.db_path)
                    db3.execute("UPDATE events SET ai_summary=? WHERE id=?", (summary, eid))
                    safe_commit(db3)
                    db3.close()
                    _es_state["done"] += 1
                else:
                    _es_state["failed"] += 1
            except Exception as e:
                _es_state["failed"] += 1
            time.sleep(0.1)
    finally:
        _es_state["running"] = False
        logger.info(f"summarize: 完成 — {_es_state.get('done', 0)}/{_es_state.get('total', 0)} 成功, {_es_state.get('failed', 0)} 失败")
        task_lock.release('summarize_events')


def _run_build_chains():
    global _chain_state
    _chain_state.clear()
    _chain_state.update({"running": True, "total_groups": 0, "chains_created": 0, "current": "", "log": [], "cancelled": False})
    try:
        from ai_client import build_panoramic_context, build_chains_panoramic
        db = get_db_connection(config.db_path)
        context = build_panoramic_context(db)
        event_count = context.count('\n[#')
        _chain_state["log"].append(f"全景图已构建（{event_count} 个活跃事件≥2篇），请求 AI 识别逻辑链...")
        logger.info(f"build_chains: 全景图 {event_count} 个活跃事件，开始 AI 推理...")
        groups = build_chains_panoramic(context)
        if not groups:
            _chain_state["log"].append("⚠️ AI 未返回有效分组（可能原因：json_object 格式与数组输出冲突 / AI 无合适分组 / 响应解析失败）")
            logger.warning("build_chains: AI 未返回有效分组 — 无逻辑链生成。请检查 ai_json_response_format 配置与模型输出格式是否兼容。")
            db.close()
            _chain_state["running"] = False
            return
        _chain_state["total_groups"] = len(groups)
        logger.info(f"build_chains: AI 返回 {len(groups)} 个候选分组，开始验证事件有效性...")
        for group in groups:
            if _chain_state.get("cancelled"):
                break
            event_specs = group.get("events", [])
            chain_title = group.get("title", "")
            reason = group.get("reason", "")
            # 兼容旧格式 [id, ...] 和新格式 [{id, role}, ...]
            if not event_specs or len(event_specs) < 2 or not chain_title:
                continue
            valid = []
            for spec in event_specs:
                if isinstance(spec, dict):
                    eid = spec.get("id")
                    role = spec.get("role", "")
                else:
                    eid = spec
                    role = ""
                r = db.execute("SELECT id FROM events WHERE id=? AND status='active'", (eid,)).fetchone()
                if r:
                    valid.append((eid, role))
            if len(valid) < 2:
                continue
            # 增量更新：新链不覆盖已有链中的事件，但允许部分重叠（≤50%）
            valid_ids = [v[0] for v in valid]
            placeholders = ','.join('?' * len(valid_ids))
            overlap = db.execute(
                f"SELECT COUNT(DISTINCT event_id) FROM chain_events WHERE event_id IN ({placeholders})",
                valid_ids
            ).fetchone()[0]
            if overlap >= len(valid_ids):  # 完全重叠则跳过
                continue
            now = datetime.now().isoformat(timespec='seconds')
            cur = db.execute(
                "INSERT INTO logic_chains (title, description, created_at, updated_at, created_by) VALUES (?,?,?,?,'auto')",
                (chain_title[:100], f"AI 全景推理 — {reason}", now, now)
            )
            chain_id = cur.lastrowid
            for pos, (eid, role) in enumerate(valid):
                note = f"角色: {role}" if role else f"AI: {reason}"
                db.execute(
                    "INSERT INTO chain_events (chain_id, event_id, position, note) VALUES (?,?,?,?)",
                    (chain_id, eid, pos, note[:200])
                )
            _chain_state["chains_created"] += 1
            _chain_state["log"].append(f"✅ {chain_title} ({len(valid)} 事件) — {reason}")
        safe_commit(db)
        db.close()
        logger.info(f"build_chains: 完成 — {_chain_state['chains_created']}/{_chain_state['total_groups']} 条逻辑链已入库")
    except Exception as e:
        logger.error(f"build_chains: {e}")
    finally:
        _chain_state["running"] = False
        task_lock.release('build_chains')


# ── 主端点 ──

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


# ── 独立操作端点 ──

@router.post("/recluster")
def start_recluster():
    """[手动触发] 事件重聚类 — 仅在需要全量重建时使用。
    日常事件聚类已由 process_article() 自动完成。
    """
    global _recl_state
    if _recl_state.get("running"):
        return {"ok": False, "message": "重聚类已在运行中"}
    ok, msg = task_lock.acquire('recluster')
    if not ok:
        return {"ok": False, "message": msg}
    threading.Thread(target=_run_recluster, daemon=True).start()
    return {"ok": True, "message": "事件重聚类已启动"}


@router.get("/recluster/status")
def get_recluster_status():
    return dict(_recl_state)


@router.post("/summarize")
def start_summarize():
    global _es_state
    if _es_state.get("running"):
        return {"ok": False, "message": "摘要已在运行中"}
    ok, msg = task_lock.acquire('summarize_events')
    if not ok:
        return {"ok": False, "message": msg}
    threading.Thread(target=_run_summarize, daemon=True).start()
    return {"ok": True, "message": "事件摘要已启动"}


@router.get("/summarize/status")
def get_summarize_status():
    return dict(_es_state)


@router.post("/build-chains")
def start_build_chains():
    global _chain_state
    if _chain_state.get("running"):
        return {"ok": False, "message": "逻辑链构建已在运行中"}
    ok, msg = task_lock.acquire('build_chains')
    if not ok:
        return {"ok": False, "message": msg}
    threading.Thread(target=_run_build_chains, daemon=True).start()
    return {"ok": True, "message": "逻辑链构建已启动"}


@router.get("/build-chains/status")
def get_build_chains_status():
    return dict(_chain_state)
