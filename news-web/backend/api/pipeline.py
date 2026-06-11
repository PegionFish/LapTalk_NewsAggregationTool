"""
批量 AI 处理 API — 遍历数据库，对未处理文章执行翻译或分析。
后台异步执行，立即返回待处理数量。
"""
import os, sqlite3, time, logging, threading
from datetime import datetime
from fastapi import APIRouter

from config import config

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)

# ── 进度追踪（内存）───────────────────────────────────────
LOG_MAX = 80  # 单次任务最多保留日志条数，防内存膨胀

def _new_state():
    return {"running": False, "total": 0, "done": 0, "failed": 0, "current": "", "log": []}

def _log(state, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    state["log"].append(f"[{ts}] {msg}")
    if len(state["log"]) > LOG_MAX:
        state["log"] = state["log"][-LOG_MAX:]

# 模块级状态初始化
_translate_state = _new_state()
_analyze_state  = _new_state()


def _conn():
    return sqlite3.connect(config.db_path)


# ═════════════════════════════════════════════════════════
# 批量翻译
# ═════════════════════════════════════════════════════════

def _batch_translate():
    global _translate_state
    _translate_state = _new_state()
    _translate_state["running"] = True

    try:
        cache_dir = config.content_cache_path
        if not os.path.isdir(cache_dir):
            _translate_state["running"] = False
            return

        # 找出有 HTML 缓存但未翻译的文章
        db = _conn()
        rows = db.execute("""
            SELECT id, title, local_path
            FROM articles
            WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'
              AND (translated_content IS NULL OR translated_content = '')
            ORDER BY id DESC
        """).fetchall()
        db.close()

        if not rows:
            _translate_state["running"] = False
            return

        _translate_state["total"] = len(rows)
        _log(_translate_state, f"待处理 {len(rows)} 篇 — 先提取文本再翻译")

        from utils.text import extract_text_from_html, detect_language
        from translation_client import translate_to_chinese

        for idx, (aid, title, local_path) in enumerate(rows, 1):
            html_path = os.path.join(cache_dir, os.path.basename(local_path))
            if not os.path.isfile(html_path):
                _log(_translate_state, f"#{aid} ⚠️ HTML 文件不存在")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            _translate_state["current"] = f"#{aid} {title[:50]}"

            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    html = f.read()
            except Exception:
                _log(_translate_state, f"#{aid} ❌ 文件读取失败")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            if len(html) < 100:
                _log(_translate_state, f"#{aid} ⚠️ HTML 过短 ({len(html)} 字节)")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            # 从 HTML 提取纯文本
            text = extract_text_from_html(html, max_length=6000)
            if len(text) < 50:
                _log(_translate_state, f"#{aid} ⚠️ 提取文本过短 ({len(text)} 字)")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            # 语言检测
            lang = detect_language(text)
            _log(_translate_state, f"#{aid} 语言: {lang} | HTML {len(html)//1024}KB → 文本 {len(text)} 字")

            if lang != 'en':
                db2 = _conn()
                db2.execute("UPDATE articles SET text_content=?, content_lang=? WHERE id=?",
                           (text, lang, aid))
                db2.commit()
                db2.close()
                _log(_translate_state, f"#{aid} ⏭️ 非英文，仅提取文本")
                _translate_state["done"] += 1
                continue

            # 翻译文本（自动分段翻译长文，每段 ≤1800 字独立请求）
            try:
                chunks = (len(text) + 1799) // 1800
                _log(_translate_state, f"#{aid} 📡 翻译中... ({len(text)} 字, {chunks} 段, 模型: {config.translation_model})")
                translation = translate_to_chinese(text)
                if translation and len(translation) > 20:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE articles SET text_content=?, translated_content=?, content_status='translated', content_lang='en', translated_at=? WHERE id=?",
                        (text, translation, datetime.now().isoformat(timespec='seconds'), aid)
                    )
                    db2.commit()
                    db2.close()
                    _log(_translate_state, f"#{aid} ✅ 翻译完成 ({len(translation)} 字)")
                else:
                    _log(_translate_state, f"#{aid} ⚠️ API 返回空结果")
                    _translate_state["failed"] += 1
                    _translate_state["done"] += 1
                    continue
            except Exception as e:
                _log(_translate_state, f"#{aid} ❌ API 调用失败: {str(e)[:80]}")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            _translate_state["done"] += 1

            if idx < len(rows):
                time.sleep(3)  # 篇间延迟（文本翻译更快，减至 3 秒）

    except Exception as e:
        logger.error(f"Batch translate error: {e}")
    finally:
        _translate_state["running"] = False


# ═════════════════════════════════════════════════════════
# 批量分析
# ═════════════════════════════════════════════════════════

def _batch_analyze():
    global _analyze_state
    _analyze_state = _new_state()
    _analyze_state["running"] = True

    try:
        db = _conn()
        rows = db.execute("""
            SELECT id, title, text_content
            FROM articles
            WHERE text_content != ''
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

        for idx, (aid, title, text) in enumerate(rows, 1):
            _analyze_state["current"] = f"#{aid} {title[:50]}"
            _log(_analyze_state, f"#{aid} 📡 发送分析请求... ({len(text)//1024}KB 正文)")

            try:
                analysis = ai_analyze(title, text)
                if analysis:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE articles SET ai_summary=?, ai_analyzed=1 WHERE id=?",
                        (analysis, aid)
                    )
                    db2.commit()
                    db2.close()
                    _log(_analyze_state, f"#{aid} ✅ 分析完成 ({len(analysis)} 字)")
                else:
                    _log(_analyze_state, f"#{aid} ⚠️ AI 返回空结果")
                    _analyze_state["failed"] += 1
                    _analyze_state["done"] += 1
                    continue
            except Exception as e:
                _log(_analyze_state, f"#{aid} ❌ API 调用失败: {str(e)[:80]}")
                _analyze_state["failed"] += 1
                _analyze_state["done"] += 1
                continue

            _analyze_state["done"] += 1

            if idx < len(rows):
                time.sleep(1)  # 篇间短暂延迟

    except Exception as e:
        logger.error(f"Batch analyze error: {e}")
    finally:
        _analyze_state["running"] = False


# ═════════════════════════════════════════════════════════
# 自动构筑逻辑链
# ═════════════════════════════════════════════════════════

_chain_state = {"running": False, "total_groups": 0, "chains_created": 0, "current": "", "log": []}


def _build_logic_chains():
    """基于 AI 摘要中的关键词/产品/公司实体，将事件分组并自动创建逻辑链。
    每链仅发一次 AI 请求取名，上下文极短（只含事件标题）。"""
    global _chain_state
    _chain_state = {"running": True, "total_groups": 0, "chains_created": 0, "current": "", "log": []}

    try:
        db = _conn()

        # 获取所有已分析的事件及其关联文章关键词
        events = db.execute("""
            SELECT e.id, e.title, e.article_count
            FROM events e
            WHERE e.status = 'active' AND e.article_count >= 1
            ORDER BY e.article_count DESC
        """).fetchall()

        if len(events) < 2:
            db.close()
            _chain_state["running"] = False
            return

        # 收集每个事件的关键词集合
        event_kws = {}  # event_id -> set of keywords
        import json
        for evt_id, _, _ in events:
            rows = db.execute("""
                SELECT a.keywords FROM articles a
                JOIN article_events ae ON ae.article_id = a.id
                WHERE ae.event_id = ?
            """, (evt_id,)).fetchall()
            kws = set()
            for (kj,) in rows:
                try:
                    for kw in json.loads(kj or '[]'):
                        if len(kw) > 1 and kw.lower() not in ('news', 'rss_news', 'hotlist'):
                            kws.add(kw.lower())
                except (json.JSONDecodeError, TypeError):
                    pass
            if kws:
                event_kws[evt_id] = kws

        # 基于关键词 Jaccard 相似度聚类
        grouped = set()  # event ids already assigned
        groups = []      # list of (event_ids, merged_keywords)

        for evt_id, kws in event_kws.items():
            if evt_id in grouped:
                continue
            cluster = {evt_id}
            merged = set(kws)
            # 找重叠 ≥ 1 个关键词的其他事件
            for other_id, other_kws in event_kws.items():
                if other_id != evt_id and other_id not in grouped:
                    if kws & other_kws:
                        cluster.add(other_id)
                        merged |= other_kws
                        grouped.add(other_id)
            grouped.add(evt_id)
            if len(cluster) >= 2:
                groups.append((sorted(cluster), merged))

        _chain_state["total_groups"] = len(groups)
        _log(_chain_state, f"发现 {len(groups)} 个可构筑链的事件组")

        if not groups:
            db.close()
            _chain_state["running"] = False
            return

        from ai_client import build_chain_title
        from datetime import datetime

        for idx, (event_ids, _) in enumerate(groups, 1):
            _chain_state["current"] = f"正在处理第 {idx}/{len(groups)} 组 ({len(event_ids)} 个事件)"
            _log(_chain_state, f"第 {idx} 组: {len(event_ids)} 个事件 — 请求 AI 命名...")

            # 收集事件标题（极短上下文）
            titles = db.execute(
                f"SELECT title FROM events WHERE id IN ({','.join('?'*len(event_ids))})",
                event_ids
            ).fetchall()
            title_block = "\n".join(f"- {t[0][:80]}" for t in titles)

            # 检查事件是否已被分配链
            already = db.execute(
                f"SELECT event_id FROM chain_events WHERE event_id IN ({','.join('?'*len(event_ids))})",
                event_ids
            ).fetchall()
            if already:
                _chain_state["current"] = f"第 {idx}/{len(groups)} 组 — 已有链，跳过"
                continue

            # AI 命名（一次短调用）
            chain_title = ""
            try:
                chain_title = build_chain_title(title_block)
            except Exception:
                chain_title = ""

            if not chain_title:
                chain_title = db.execute(
                    f"SELECT title FROM events WHERE id = ?", (event_ids[0],)
                ).fetchone()[0][:30] + " 等相关事件"

            now = datetime.now().isoformat(timespec='seconds')
            cur = db.execute(
                "INSERT INTO logic_chains (title, description, created_at, updated_at, created_by) VALUES (?, ?, ?, ?, 'auto')",
                (chain_title[:100], f"自动生成 — {len(event_ids)} 个事件", now, now)
            )
            chain_id = cur.lastrowid
            for pos, eid in enumerate(event_ids):
                db.execute(
                    "INSERT INTO chain_events (chain_id, event_id, position) VALUES (?, ?, ?)",
                    (chain_id, eid, pos)
                )

            _chain_state["chains_created"] += 1
            _log(_chain_state, f"✅ 创建链: {chain_title} ({len(event_ids)} 个事件)")
            logger.info(f"Auto chain created: {chain_title} ({len(event_ids)} events)")

            time.sleep(0.5)  # 链间微延迟

        db.commit()
        db.close()

    except Exception as e:
        logger.error(f"Build chains error: {e}")
    finally:
        _chain_state["running"] = False


# ═════════════════════════════════════════════════════════
# API 端点
# ═════════════════════════════════════════════════════════

@router.post("/batch-translate")
def start_batch_translate():
    """启动批量翻译 — 遍历所有有 HTML 缓存但未翻译的英文文章。"""
    global _translate_state
    if _translate_state.get("running"):
        return {"ok": False, "message": "翻译任务已在运行中", "state": _translate_state}

    # 预计算待处理数量
    db = _conn()
    pending = db.execute("""
        SELECT COUNT(*) FROM articles
        WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'
          AND (translated_content IS NULL OR translated_content = '')
    """).fetchone()[0]
    db.close()

    threading.Thread(target=_batch_translate, daemon=True).start()
    return {"ok": True, "message": f"启动批量翻译，预计 {pending} 篇", "pending": pending}


@router.get("/batch-translate/status")
def get_batch_translate_status():
    """查询批量翻译进度 — running/current/log 来自内存，统计从 DB 派生。"""
    if _translate_state.get("running"):
        db = _conn()
        total = db.execute("""
            SELECT COUNT(*) FROM articles
            WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'
              AND (translated_content IS NULL OR translated_content = '')
        """).fetchone()[0]
        done = db.execute("""
            SELECT COUNT(*) FROM articles
            WHERE local_path != '' AND local_path NOT LIKE '[ERR:%'
              AND translated_content != ''
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
    db = _conn()
    pending = db.execute("""
        SELECT COUNT(*) FROM articles
        WHERE text_content != ''
          AND (ai_analyzed IS NULL OR ai_analyzed = 0 OR ai_summary IS NULL OR ai_summary = '')
    """).fetchone()[0]
    db.close()
    threading.Thread(target=_batch_analyze, daemon=True).start()
    return {"ok": True, "message": f"启动批量分析，预计 {pending} 篇", "pending": pending}


@router.get("/batch-analyze/status")
def get_batch_analyze_status():
    """查询批量分析进度。"""
    if _analyze_state.get("running"):
        db = _conn()
        total = db.execute("""
            SELECT COUNT(*) FROM articles
            WHERE text_content != ''
              AND (ai_analyzed IS NULL OR ai_analyzed = 0 OR ai_summary IS NULL OR ai_summary = '')
        """).fetchone()[0]
        done = db.execute("""
            SELECT COUNT(*) FROM articles WHERE ai_analyzed = 1 AND ai_summary != ''
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


def _batch_ai_keywords():
    global _kw_state
    _kw_state = _new_state(); _kw_state["running"] = True
    try:
        db = _conn()
        rows = db.execute("SELECT id, title, text_content, source FROM articles WHERE text_content != '' AND (ai_keywords IS NULL OR ai_keywords = '') ORDER BY id DESC").fetchall(); db.close()
        if not rows: _kw_state["running"] = False; return
        _kw_state["total"] = len(rows)
        _log(_kw_state, f"待提取关键词 {len(rows)} 篇")
        from ai_client import extract_keywords_ai
        import json as _json
        for idx, (aid, title, text, source) in enumerate(rows, 1):
            _kw_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_kw_state, f"#{aid} ⏭️ 人工已处理"); _kw_state["done"] += 1; continue
            kws = extract_keywords_ai(title, text[:6000], source or "")
            if kws:
                db2 = _conn()
                db2.execute("UPDATE articles SET keywords=?, ai_keywords=? WHERE id=?", (_json.dumps(kws, ensure_ascii=False), _json.dumps(kws, ensure_ascii=False), aid))
                db2.commit(); db2.close()
                _log(_kw_state, f"#{aid} ✅ {len(kws)} 个关键词: {', '.join(kws[:5])}")
            else:
                _log(_kw_state, f"#{aid} ⚠️ AI 返回空"); _kw_state["failed"] += 1
            _kw_state["done"] += 1
            time.sleep(0.8) if idx < len(rows) else None
    except Exception as e: logger.error(f"batch-keywords: {e}")
    finally: _kw_state["running"] = False


def _batch_ai_classify():
    global _cls_state
    _cls_state = _new_state(); _cls_state["running"] = True
    try:
        db = _conn()
        rows = db.execute("SELECT id, title, text_content FROM articles WHERE text_content != '' AND (ai_category IS NULL OR ai_category = '') ORDER BY id DESC").fetchall(); db.close()
        if not rows: _cls_state["running"] = False; return
        _cls_state["total"] = len(rows)
        _log(_cls_state, f"待分类 {len(rows)} 篇")
        from ai_client import classify_article_ai
        import json as _json
        for idx, (aid, title, text) in enumerate(rows, 1):
            _cls_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_cls_state, f"#{aid} ⏭️ 人工已处理"); _cls_state["done"] += 1; continue
            r = classify_article_ai(title, text[:6000])
            if r:
                db2 = _conn()
                db2.execute("UPDATE articles SET ai_category=?, ai_tags=? WHERE id=?", (r.get("category",""), _json.dumps(r.get("tags",[]), ensure_ascii=False), aid))
                db2.commit(); db2.close()
                _log(_cls_state, f"#{aid} ✅ {r.get('category','?')} — {', '.join(r.get('tags',[])[:3])}")
            else:
                _log(_cls_state, f"#{aid} ⚠️ AI 返回空"); _cls_state["failed"] += 1
            _cls_state["done"] += 1
            time.sleep(0.8) if idx < len(rows) else None
    except Exception as e: logger.error(f"batch-classify: {e}")
    finally: _cls_state["running"] = False


def _batch_ai_score():
    global _score_state
    _score_state = _new_state(); _score_state["running"] = True
    try:
        db = _conn()
        rows = db.execute("SELECT id, title, text_content, source, fetched_at FROM articles WHERE text_content != '' AND (ai_priority_score IS NULL OR ai_priority_score = 0.0) ORDER BY id DESC").fetchall(); db.close()
        if not rows: _score_state["running"] = False; return
        _score_state["total"] = len(rows)
        _log(_score_state, f"待评分 {len(rows)} 篇")
        from ai_client import score_priority_ai
        from datetime import datetime as _dt
        for idx, (aid, title, text, source, fetched_at) in enumerate(rows, 1):
            _score_state["current"] = f"#{aid} {title[:50]}"
            if _hp_check(aid): _log(_score_state, f"#{aid} ⏭️ 人工已处理"); _score_state["done"] += 1; continue
            try:
                days = max(0, (_dt.now() - _dt.fromisoformat(fetched_at)).days) if fetched_at else 0
            except Exception:
                days = 0
            r = score_priority_ai(title, text[:6000], source or "Unknown", days)
            if r:
                db2 = _conn()
                db2.execute("UPDATE articles SET priority_score=?, priority_label=?, ai_priority_score=? WHERE id=?", (r["score"], r.get("label","medium"), r["score"], aid))
                db2.commit(); db2.close()
                _log(_score_state, f"#{aid} ✅ {r.get('label','medium')}({r['score']:.2f}) — {r.get('reason','')}")
            else:
                _log(_score_state, f"#{aid} ⚠️ AI 返回空"); _score_state["failed"] += 1
            _score_state["done"] += 1
            time.sleep(0.8) if idx < len(rows) else None
    except Exception as e: logger.error(f"batch-score: {e}")
    finally: _score_state["running"] = False


def _batch_ai_recluster():
    global _recluster_state
    _recluster_state = _new_state(); _recluster_state["running"] = True
    try:
        db = _conn()
        unlinked = db.execute("SELECT a.id, a.title FROM articles a LEFT JOIN article_events ae ON a.id=ae.article_id WHERE ae.article_id IS NULL AND a.text_content!=''").fetchall()
        events  = db.execute("SELECT id, title FROM events WHERE status='active'").fetchall()
        db.close()
        if not unlinked: _recluster_state["running"] = False; return
        _recluster_state["total"] = len(unlinked)
        _log(_recluster_state, f"待聚类 {len(unlinked)} 篇 → {len(events)} 个活跃事件")
        from ai_client import assess_event_similarity_ai
        for idx, (aid, art_title) in enumerate(unlinked, 1):
            _recluster_state["current"] = f"#{aid} {art_title[:50]}"
            best_id, best_conf = None, 0
            for evt_id, evt_title in events:
                try:
                    r = assess_event_similarity_ai(art_title, evt_title)
                    if r and r.get("similar") and r.get("confidence", 0) > best_conf:
                        best_conf = r["confidence"]; best_id = evt_id
                except Exception as cmp_err:
                    _log(_recluster_state, f"#{aid} ⚠️ 与事件#{evt_id}比对失败: {str(cmp_err)[:60]}")
            if best_id and best_conf > 0.5:
                db2 = _conn()
                db2.execute("INSERT OR IGNORE INTO article_events (article_id, event_id, relevance) VALUES (?, ?, ?)", (aid, best_id, round(best_conf, 2)))
                db2.execute("UPDATE events SET article_count=article_count+1 WHERE id=?", (best_id,))
                db2.commit(); db2.close()
                _log(_recluster_state, f"#{aid} ✅ -> 事件#{best_id} (置信度 {best_conf:.2f})")
            else:
                _log(_recluster_state, f"#{aid} ➕ 创建新事件")
                from datetime import datetime as _dt
                now = _dt.now().isoformat(timespec='seconds')
                db2 = _conn()
                cur = db2.execute("INSERT INTO events (title, first_seen, last_seen, status) VALUES (?,?,?,'active')", (art_title[:80], now[:10], now[:10]))
                db2.execute("INSERT INTO article_events (article_id, event_id) VALUES (?,?)", (aid, cur.lastrowid))
                db2.commit(); db2.close()
            _recluster_state["done"] += 1
            time.sleep(1.0) if idx < len(unlinked) else None
    except Exception as e: logger.error(f"batch-recluster: {e}")
    finally: _recluster_state["running"] = False


def _batch_ai_summarize_events():
    global _evt_sum_state
    _evt_sum_state = _new_state(); _evt_sum_state["running"] = True
    try:
        db = _conn()
        events = db.execute("SELECT id, article_count FROM events WHERE article_count >= 2 AND (ai_summary IS NULL OR ai_summary = '')").fetchall(); db.close()
        if not events: _evt_sum_state["running"] = False; return
        _evt_sum_state["total"] = len(events)
        _log(_evt_sum_state, f"待生成摘要 {len(events)} 个事件")
        from ai_client import generate_event_summary_ai
        for idx, (evt_id, _) in enumerate(events, 1):
            _evt_sum_state["current"] = f"事件#{evt_id}"
            db2 = _conn()
            titles = [r[0] for r in db2.execute("SELECT a.title FROM articles a JOIN article_events ae ON ae.article_id=a.id WHERE ae.event_id=?", (evt_id,)).fetchall()]
            db2.close()
            if len(titles) < 2: _evt_sum_state["done"] += 1; continue
            block = "\n".join(f"- {t}" for t in titles[:15])
            summary = generate_event_summary_ai(block)
            if summary:
                db2 = _conn()
                db2.execute("UPDATE events SET ai_summary=? WHERE id=?", (summary, evt_id))
                db2.commit(); db2.close()
                _log(_evt_sum_state, f"#{evt_id} ✅ {len(summary)} 字")
            else:
                _log(_evt_sum_state, f"#{evt_id} ⚠️ AI 返回空"); _evt_sum_state["failed"] += 1
            _evt_sum_state["done"] += 1
            time.sleep(0.8) if idx < len(events) else None
    except Exception as e: logger.error(f"batch-summarize-events: {e}")
    finally: _evt_sum_state["running"] = False


def _hp_check(aid: int) -> bool:
    """检查文章是否人工已处理"""
    db = _conn()
    r = db.execute("SELECT human_processed FROM articles WHERE id=?", (aid,)).fetchone()
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
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM articles WHERE text_content!='' AND (ai_keywords IS NULL OR ai_keywords='')").fetchone()[0]; db.close()
    threading.Thread(target=_batch_ai_keywords, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 关键词提取，预计 {n} 篇", "pending": n}

@router.post("/batch-classify")
def start_batch_classify():
    global _cls_state
    if _cls_state.get("running"): return {"ok": False, "message": "分类已在运行中"}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM articles WHERE text_content!='' AND (ai_category IS NULL OR ai_category='')").fetchone()[0]; db.close()
    threading.Thread(target=_batch_ai_classify, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 分类，预计 {n} 篇", "pending": n}

@router.post("/batch-score")
def start_batch_score():
    global _score_state
    if _score_state.get("running"): return {"ok": False, "message": "评分已在运行中"}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM articles WHERE text_content!='' AND (ai_priority_score IS NULL OR ai_priority_score=0.0)").fetchone()[0]; db.close()
    threading.Thread(target=_batch_ai_score, daemon=True).start()
    return {"ok": True, "message": f"启动 AI 评分，预计 {n} 篇", "pending": n}

@router.post("/batch-recluster")
def start_batch_recluster():
    global _recluster_state
    if _recluster_state.get("running"): return {"ok": False, "message": "重聚类已在运行中"}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM articles a LEFT JOIN article_events ae ON a.id=ae.article_id WHERE ae.article_id IS NULL AND a.text_content!=''").fetchone()[0]; db.close()
    threading.Thread(target=_batch_ai_recluster, daemon=True).start()
    return {"ok": True, "message": f"启动智能重聚类，预计 {n} 篇", "pending": n}

@router.post("/batch-summarize-events")
def start_batch_summarize_events():
    global _evt_sum_state
    if _evt_sum_state.get("running"): return {"ok": False, "message": "事件摘要已在运行中"}
    db = _conn(); n = db.execute("SELECT COUNT(*) FROM events WHERE article_count>=2 AND (ai_summary IS NULL OR ai_summary='')").fetchone()[0]; db.close()
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


# ═════════════════════════════════════════════════════════
# 统一全流程 — 翻译 → 关键词 → 分类 → 评分 → 分析 → 聚类 → 摘要 → 链
# ═════════════════════════════════════════════════════════

_full_state = _new_state()

def _batch_ai_full():
    """顺序执行全部 AI 处理步骤。每步检查是否有待处理项，无则跳过。"""
    global _full_state
    _full_state = _new_state(); _full_state["running"] = True
    _full_state["steps"] = []
    step_names = ["翻译", "AI 分析", "关键词提取", "智能分类", "优先级评分", "事件重聚类", "事件摘要", "构筑逻辑链"]
    steps = [
        ("翻译", _batch_translate, _translate_state),
        ("AI 分析", _batch_analyze, _analyze_state),
        ("关键词提取", _batch_ai_keywords, _kw_state),
        ("智能分类", _batch_ai_classify, _cls_state),
        ("优先级评分", _batch_ai_score, _score_state),
        ("事件重聚类", _batch_ai_recluster, _recluster_state),
        ("事件摘要", _batch_ai_summarize_events, _evt_sum_state),
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
                time.sleep(2)
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


@router.post("/batch-ai-full")
def start_batch_ai_full():
    """一键启动全流程 AI 处理。"""
    global _full_state
    if _full_state.get("running"):
        return {"ok": False, "message": "全流程已在运行中"}
    threading.Thread(target=_batch_ai_full, daemon=True).start()
    return {"ok": True, "message": "启动全流程 AI 处理 — 翻译→分析→关键词→分类→评分→聚类→摘要→链"}


@router.get("/batch-ai-full/status")
def get_batch_ai_full_status():
    return dict(_full_state)
