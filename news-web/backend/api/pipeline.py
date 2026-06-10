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
_translate_state = {"running": False, "total": 0, "done": 0, "failed": 0, "current": ""}
_analyze_state  = {"running": False, "total": 0, "done": 0, "failed": 0, "current": ""}


def _conn():
    return sqlite3.connect(config.db_path)


# ═════════════════════════════════════════════════════════
# 批量翻译
# ═════════════════════════════════════════════════════════

def _batch_translate():
    global _translate_state
    _translate_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": ""}

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

        from translation_client import translate_html

        for idx, (aid, title, local_path) in enumerate(rows, 1):
            html_path = os.path.join(cache_dir, os.path.basename(local_path))
            if not os.path.isfile(html_path):
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            _translate_state["current"] = f"#{aid} {title[:50]}"

            try:
                with open(html_path, 'r', encoding='utf-8') as f:
                    html = f.read()
            except Exception:
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            if len(html) < 100:
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            # 语言检测：仅翻译英文文章
            from utils.text import detect_language
            lang = detect_language(html[:10000])

            if lang != 'en':
                db2 = _conn()
                db2.execute("UPDATE articles SET content_lang=? WHERE id=?", (lang, aid))
                db2.commit()
                db2.close()
                _translate_state["done"] += 1
                continue

            try:
                result = translate_html(html)
                if result and len(result) > 100:
                    db2 = _conn()
                    db2.execute(
                        "UPDATE articles SET translated_content=?, content_status='translated', content_lang='en', translated_at=? WHERE id=?",
                        (result, datetime.now().isoformat(timespec='seconds'), aid)
                    )
                    db2.commit()
                    db2.close()
                else:
                    _translate_state["failed"] += 1
                    _translate_state["done"] += 1
                    continue
            except Exception as e:
                logger.warning(f"Translate failed for #{aid}: {e}")
                _translate_state["failed"] += 1
                _translate_state["done"] += 1
                continue

            _translate_state["done"] += 1

            if idx < len(rows):
                time.sleep(5)  # 篇间延迟防超限

    except Exception as e:
        logger.error(f"Batch translate error: {e}")
    finally:
        _translate_state["running"] = False


# ═════════════════════════════════════════════════════════
# 批量分析
# ═════════════════════════════════════════════════════════

def _batch_analyze():
    global _analyze_state
    _analyze_state = {"running": True, "total": 0, "done": 0, "failed": 0, "current": ""}

    try:
        db = _conn()
        # 查找有文本内容但未 AI 分析的文章
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

        from ai_client import analyze_article as ai_analyze

        for idx, (aid, title, text) in enumerate(rows, 1):
            _analyze_state["current"] = f"#{aid} {title[:50]}"

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
                else:
                    _analyze_state["failed"] += 1
                    _analyze_state["done"] += 1
                    continue
            except Exception as e:
                logger.warning(f"Analyze failed for #{aid}: {e}")
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
        # 分析完成后自动构筑逻辑链（仅在成功处理 1 篇以上时触发）
        if _analyze_state["done"] > 0 and _analyze_state["total"] > 0:
            logger.info("Batch analyze done — auto-building logic chains...")
            _build_logic_chains()


# ═════════════════════════════════════════════════════════
# 自动构筑逻辑链
# ═════════════════════════════════════════════════════════

_chain_state = {"running": False, "total_groups": 0, "chains_created": 0, "current": ""}


def _build_logic_chains():
    """基于 AI 摘要中的关键词/产品/公司实体，将事件分组并自动创建逻辑链。
    每链仅发一次 AI 请求取名，上下文极短（只含事件标题）。"""
    global _chain_state
    _chain_state = {"running": True, "total_groups": 0, "chains_created": 0, "current": ""}

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
        if not groups:
            db.close()
            _chain_state["running"] = False
            return

        from ai_client import build_chain_title
        from datetime import datetime

        for idx, (event_ids, _) in enumerate(groups, 1):
            _chain_state["current"] = f"正在处理第 {idx}/{len(groups)} 组 ({len(event_ids)} 个事件)"

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
    """查询批量翻译进度。"""
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
    return dict(_analyze_state)


@router.post("/build-chains")
def start_build_chains():
    """手动触发逻辑链构筑 — 基于事件关键词分组 + AI 命名。"""
    global _chain_state
    if _chain_state.get("running"):
        return {"ok": False, "message": "链构筑已在运行中", "state": _chain_state}

    threading.Thread(target=_build_logic_chains, daemon=True).start()
    return {"ok": True, "message": "开始构筑逻辑链"}


@router.get("/build-chains/status")
def get_build_chains_status():
    """查询逻辑链构筑进度。"""
    return dict(_chain_state)
