#!/usr/bin/env python3
"""
新闻数据库模块 — SQLite 存储 + 事件关联 + 关键词提取 + 优先级评分 + 人工反馈

三层架构：
  1. 数据层 — articles / events / article_events
  2. 分析层 — extract_keywords / calculate_priority
  3. 反馈层 — human_feedback / event_relations / tag_propagation

用法：
  from news_db import NewsDB
  db = NewsDB()
  db.save_articles(category, articles)
  db.link_articles_to_events()
  db.calculate_priority(article_id)

Web UI 查询：
  db.get_pending_review()     # 待人工审核
  db.get_event_timeline(id)   # 事件时间线 + 关联事件
  db.get_feedback_stats()     # 反馈统计
"""

import os, json, sqlite3, re, math
from datetime import datetime, date
from typing import Optional

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hot_reports')
DB_PATH = os.path.join(DB_DIR, 'news.db')

# ══════════════════════════════════════════════════════════════
# 关键词/实体工具
# ══════════════════════════════════════════════════════════════

def title_bigrams(title: str) -> set:
    t = re.sub(r'[^\w\u4e00-\u9fff]', '', title.lower())
    return set(t[i:i+2] for i in range(len(t)-1))

def title_similarity(t1: str, t2: str) -> float:
    a, b = title_bigrams(t1), title_bigrams(t2)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def extract_entities(title: str) -> list:
    """提取标题中的实体（英文专有名词 + 中文词 + 代号）"""
    en = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', title)
    cn = re.findall(r'[\u4e00-\u9fff]{2,6}', title)
    mix = re.findall(r'\b[A-Z0-9]+\d+[A-Za-z0-9]*\b', title)
    return list(set(en + cn + mix))

def extract_keywords(title: str, source: str = '', category: str = '') -> list:
    """
    关键词提取 — 标题实体 + 来源特征 + 分类特征
    返回去重排序后的关键词列表（按权重降序）。
    """
    result = {}
    
    # 1. 标题实体 (权重 0.6)
    entities = extract_entities(title)
    for e in entities:
        result[e] = result.get(e, 0) + 0.6
    
    # 2. 来源关键词 (权重 0.2)
    source_lower = source.lower()
    source_kw_map = {
        'guru3d': ['guru3d', 'hardware'],
        'pc gamer': ['pcgamer', 'gaming', 'pc'],
        'eurogamer': ['eurogamer', 'gaming'],
        'gamespot': ['gamespot', 'gaming'],
        'nintendo everything': ['nintendo', 'gaming'],
        'vg247': ['vg247', 'gaming'],
        'rock paper shotgun': ['rockpapershotgun', 'gaming', 'pc'],
        'ithome': ['ithome', 'tech', 'china'],
        'zdnet': ['zdnet', 'tech'],
        'cnet': ['cnet', 'tech'],
        '9to5mac': ['9to5mac', 'apple'],
        'macrumors': ['macrumors', 'apple'],
        'arstechnica': ['arstechnica', 'tech'],
        'techcrunch': ['techcrunch', 'tech', 'startup'],
        'guru3d': ['guru3d', 'hardware'],
        'phoronix': ['phoronix', 'linux', 'hardware'],
        'tom\'s hardware': ['tomshardware', 'hardware'],
        'techpowerup': ['techpowerup', 'hardware', 'gpu'],
        'servethehome': ['servethehome', 'server', 'hardware'],
    }
    for pat, kws in source_kw_map.items():
        if pat in source_lower:
            for kw in kws:
                result[kw] = result.get(kw, 0) + 0.2
    
    # 3. 分类关键词 (权重 0.2)
    if category:
        result[category] = result.get(category, 0) + 0.2
        if category == 'rss_news':
            result['news'] = result.get('news', 0) + 0.1
    
    # 4. 按权重排序
    sorted_kw = sorted(result.items(), key=lambda x: -x[1])
    return [kw for kw, _ in sorted_kw[:15]]


# ══════════════════════════════════════════════════════════════
# 来源权威分 (A维度)
# ══════════════════════════════════════════════════════════════

SOURCE_TIERS = {
    'Ars Technica': 1.0, 'TechCrunch': 1.0, 'Phoronix': 1.0, 'ServeTheHome': 1.0,
    'Guru3D': 0.8, "Tom's Hardware": 0.8, 'TechPowerUp': 0.8, 'ZDNet': 0.8, 'CNET': 0.8,
    'IT之家': 0.6, '9to5Mac': 0.6, 'MacRumors': 0.6, 'PC Gamer': 0.6, 'Eurogamer': 0.6,
    'Wccftech': 0.6, 'GameSpot': 0.6, 'VG247': 0.6, 'Rock Paper Shotgun': 0.6,
    'Nintendo Everything': 0.6, 'VentureBeat': 0.6, 'Engadget': 0.6, 'Gizmodo': 0.6,
    'Digital Trends': 0.6,
    '36Kr': 0.4, '钛媒体': 0.4, '爱范儿': 0.4, '少数派': 0.4,
    '机器之心': 0.4, '雷锋网': 0.4, 'Solidot': 0.4,
    'BBC Technology': 0.6, 'NPR Technology': 0.6,
    'Liliputing': 0.6, 'Android Police': 0.6, 'XDA Developers': 0.6,
    'MIT Tech Review': 0.8, 'The Decoder': 0.6, 'AI News': 0.4, 'MarkTechPost': 0.4,
    'VentureBeat AI': 0.6,
}

# 内容主题分 (C维度)
TOPIC_SCORES = [
    (['nvidia', 'amd', 'intel', 'gpu', 'cpu', 'chip', 'semiconductor', 'nova lake',
      'radeon', 'ddr5', 'nvme', 'ssd', 'lga', 'socket', 'transistor', '光刻', '封装',
      '数据中心', 'server', 'workstation', 'hpc', 'ai pc', '算力',
      'robotaxi', '自动驾驶', 'spacex', 'nasa', '卫星', 'starship', 'artemis',
      'phoronix', 'servethehome', 'techpowerup', 'linux', '开源'],
     1.0, 'PC/Hardware'),
    (['ai ', 'ai)', 'ai,', 'ai.', 'llm', 'gpt', 'claude', 'gemini', 'openai',
      'deepseek', 'anthropic', 'siri', '机器学习', '大模型', '人工智',
      'copilot', 'chatgpt', 'ipo'],
     0.9, 'AI/LLM'),
    (['review', 'preview', 'trailer', 'gameplay', 'dlc', 'expansion', 'early access',
     '1.0', '新作', '预告', '公测', 'beta', 'demo',
     'guild wars', 'blade ', 'valheim', '英灵', '共鸣',
     'square enix', 'capcom', 'fromsoftware', 'microsoft', 'activision', 'ubisoft',
     'tifa', 'street fighter'],
     0.8, 'Game/New'),
    (['game pass', 'subscriber', 'xbox ', 'playstation', 'nintendo', 'switch',
      '主机', '订阅', 'million'],
     0.4, 'Game/Platform'),
    (['iphone', 'android', 'pixel', 'foldable', '折叠屏', 'smartphone', '手机',
     'ipad', 'tablet', 'airpods', 'apple watch', 'watchos'],
     0.3, 'Mobile'),
    (['推出', '上架', '开售', '预售', '发布', '首发', 'launch', 'unveil', 'debut',
      'available', 'shipping', '戴尔', '神舟', '中兴', 'gpd', '小米上线'],
     0.2, 'Product Launch'),
]


def source_authority(source: str) -> float:
    """A维度: 来源权威分 0.0~1.0"""
    return SOURCE_TIERS.get(source, 0.3)


def topic_score(title: str) -> tuple:
    """C维度: 内容主题分 + 标签。返回 (score, label)"""
    t = title.lower()
    for patterns, score, label in TOPIC_SCORES:
        for pat in patterns:
            if pat.lower() in t:
                return score, label
    return 0.1, 'Other'


# ══════════════════════════════════════════════════════════════
# 数据库操作
# ══════════════════════════════════════════════════════════════

class NewsDB:
    DB_PATH = DB_PATH

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    url TEXT DEFAULT '',
                    category TEXT NOT NULL,
                    published_date TEXT DEFAULT '',
                    fetched_at TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    keywords TEXT DEFAULT '[]',
                    priority_score REAL DEFAULT 0.0,
                    priority_label TEXT DEFAULT 'unset',
                    human_verified INTEGER DEFAULT 0,
                    human_tags TEXT DEFAULT '[]',
                    UNIQUE(title, source, url)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    first_seen DATE NOT NULL,
                    last_seen DATE NOT NULL,
                    article_count INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'active',
                    priority_label TEXT DEFAULT 'medium'
                );

                CREATE TABLE IF NOT EXISTS article_events (
                    article_id INTEGER REFERENCES articles(id),
                    event_id INTEGER REFERENCES events(id),
                    relevance REAL DEFAULT 1.0,
                    PRIMARY KEY (article_id, event_id)
                );

                CREATE TABLE IF NOT EXISTS human_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER REFERENCES articles(id),
                    field TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    created_at TEXT NOT NULL,
                    applied INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS event_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_event_id INTEGER NOT NULL REFERENCES events(id),
                    to_event_id INTEGER NOT NULL REFERENCES events(id),
                    relation TEXT NOT NULL
                        CHECK(relation IN ('before','after','update','spawn','related')),
                    created_by TEXT DEFAULT 'human',
                    created_at TEXT NOT NULL,
                    UNIQUE(from_event_id, to_event_id, relation)
                );

                CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(fetched_at);
                CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);
                CREATE INDEX IF NOT EXISTS idx_articles_verified ON articles(human_verified);
                CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
                CREATE INDEX IF NOT EXISTS idx_evrel_from ON event_relations(from_event_id);
                CREATE INDEX IF NOT EXISTS idx_evrel_to ON event_relations(to_event_id);
            """)
            # 迁移：给 articles 表加列（如已有则忽略）
            for col, dtype in [('keywords','TEXT DEFAULT \'[]\''),
                               ('priority_score','REAL DEFAULT 0.0'),
                               ('priority_label','TEXT DEFAULT \'unset\''),
                               ('human_verified','INTEGER DEFAULT 0'),
                               ('human_tags','TEXT DEFAULT \'[]\''),
                               ('local_path','TEXT DEFAULT \'\''),
                               ('content_fetched_at','TEXT'),
                               # 内容下载 + 翻译迁移列
                               ('text_content','TEXT DEFAULT \'\''),
                               ('translated_content','TEXT DEFAULT \'\''),
                               ('content_lang','TEXT DEFAULT \'\''),
                               ('content_status','TEXT DEFAULT \'pending\''),
                               ('translated_at','TEXT'),
                               # AI 摘要缓存 + 标注状态
                               ('ai_summary','TEXT DEFAULT \'\''),
                               ('ai_analyzed','INTEGER DEFAULT 0'),
                               ('human_processed','INTEGER DEFAULT 0'),
                               # AI 语义字段
                               ('ai_keywords','TEXT DEFAULT \'\''),
                               ('ai_category','TEXT DEFAULT \'\''),
                               ('ai_tags','TEXT DEFAULT \'\''),
                               ('ai_priority_score','REAL DEFAULT 0.0'),
                               # AI 预筛选：0=未筛选, 1=通过, -1=拒绝
                               ('ai_filtered','INTEGER DEFAULT 0'),
                               # 主题分类（硬件/AI/游戏/移动/发布/其他）
                               ('topic_category','TEXT DEFAULT \'\'')]:
                try:
                    conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {dtype}")
                except sqlite3.OperationalError:
                    pass
            # 迁移：给 events 表加 ai_summary
            for col, dtype in [('ai_summary','TEXT DEFAULT \'\'')]:
                try:
                    conn.execute(f"ALTER TABLE events ADD COLUMN {col} {dtype}")
                except sqlite3.OperationalError:
                    pass
            # 迁移：给 events 表加 priority_label
            try:
                conn.execute("ALTER TABLE events ADD COLUMN priority_label TEXT DEFAULT 'medium'")
            except sqlite3.OperationalError:
                pass
            # 新增：评语表 + 点赞表
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS article_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                    user_id INTEGER,
                    username TEXT DEFAULT 'anonymous',
                    parent_id INTEGER REFERENCES article_comments(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS comment_likes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id INTEGER NOT NULL REFERENCES article_comments(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(comment_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_comments_article ON article_comments(article_id);
                CREATE INDEX IF NOT EXISTS idx_comments_parent ON article_comments(parent_id);
                CREATE INDEX IF NOT EXISTS idx_comment_likes_comment ON comment_likes(comment_id);
            """)
            conn.commit()

    # ═══════════════════════════════════════════════════════
    # 保存
    # ═══════════════════════════════════════════════════════

    def save_articles(self, category: str, articles: list) -> tuple:
        """保存文章列表到数据库。返回 (saved: 新增数, skipped: 重复跳过数)。"""
        if not articles:
            return (0, 0)
        now = datetime.now().isoformat(timespec='seconds')
        saved = 0
        skipped = 0
        with self._conn() as conn:
            for art in articles:
                title = art.get('title', '').strip()
                source = art.get('source', '')
                url = art.get('url', '')
                if isinstance(art.get('urls'), list) and art['urls']:
                    url = art['urls'][0]
                pub_date = art.get('metadata', {}).get('published', '') if isinstance(art.get('metadata'), dict) else ''
                if not pub_date:
                    pub_date = art.get('published_date', '')
                meta = json.dumps(art.get('metadata', {}), ensure_ascii=False)
                keywords = json.dumps(extract_keywords(title, source, category), ensure_ascii=False)
                try:
                    # 同平台同标题去重：检查是否已有相同标题+来源的文章（不论 URL）
                    existing = conn.execute(
                        "SELECT id, url, ai_filtered FROM articles WHERE title=? AND source=? LIMIT 1",
                        (title, source)
                    ).fetchone()
                    if existing:
                        # 如果现有文章无 URL 或被拒绝，但新文章有 URL，则更新
                        eid, eurl, eaf = existing
                        if url and (not eurl or eaf == -1):
                            conn.execute("UPDATE articles SET url=?, ai_filtered=0 WHERE id=?", (url[:500], eid))
                            saved += 1
                        else:
                            skipped += 1
                        continue
                    # 无重复 — 正常插入
                    conn.execute("""
                        INSERT OR IGNORE INTO articles
                            (title, source, url, category, published_date, fetched_at, metadata, keywords)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (title, source, url[:500], category, str(pub_date)[:20], now, meta, keywords))
                    if conn.total_changes > 0:
                        saved += 1
                        # 对新文章计算优先级
                        new_id = conn.execute(
                            "SELECT id FROM articles WHERE title=? AND source=? AND url=?",
                            (title, source, url[:500])
                        ).fetchone()
                        if new_id:
                            self.calculate_priority(new_id[0], conn)
                    else:
                        skipped += 1
                        # 记录跳过的重复文章标题（截取前 50 字）
                        import logging
                        logging.getLogger(__name__).debug(
                            f"   ⏭️ 跳过重复: [{source}] {title[:60]}"
                        )
                except Exception:
                    continue
            conn.commit()
        return (saved, skipped)

    def fill_trend_text(self) -> int:
        """为热榜/B站视频条目直接填充 text_content（标题+元数据），
        无需走 fetch_content 下载 HTML。返回填充数量。"""
        updated = 0
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT id, title, metadata, source
                FROM articles
                WHERE category IN ('platform_hotlists', 'bilibili_videos')
                  AND (text_content IS NULL OR text_content = '')
            """).fetchall()
            for aid, title, meta_json, source in rows:
                try:
                    meta = json.loads(meta_json) if meta_json else {}
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                # 拼接标题和有用的元数据
                parts = [f"标题：{title}"]
                parts.append(f"来源：{source}")
                if meta.get('rank') is not None:
                    parts.append(f"排名：第{meta['rank']}位")
                if meta.get('heat'):
                    parts.append(f"热度：{meta['heat']}")
                if meta.get('views'):
                    parts.append(f"播放量：{meta['views']}")
                if meta.get('author'):
                    parts.append(f"作者：{meta['author']}")
                if meta.get('answer_count'):
                    parts.append(f"回答数：{meta['answer_count']}")
                if meta.get('excerpt'):
                    parts.append(f"摘要：{meta['excerpt']}")
                if meta.get('description'):
                    parts.append(f"描述：{meta['description']}")
                if meta.get('video_count'):
                    parts.append(f"相关视频：{meta['video_count']}个")
                text = '\n'.join(parts)
                from datetime import datetime
                conn.execute("""
                    UPDATE articles SET
                        local_path='[N/A:trend]',
                        content_fetched_at=?,
                        text_content=?,
                        content_lang='zh',
                        content_status='metadata_only'
                    WHERE id=?
                """, (datetime.now().isoformat(timespec='seconds'), text, aid))
                updated += 1
            conn.commit()
        return updated

    # ═══════════════════════════════════════════════════════
    # 关键词提取 + 优先级评分
    # ═══════════════════════════════════════════════════════

    def extract_keywords_for(self, article_id: int) -> list:
        """为指定文章提取关键词并更新 DB。人工已处理则跳过覆写。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT title, source, category, human_processed, keywords FROM articles WHERE id=?",
                (article_id,)
            ).fetchone()
            if not row:
                return []
            title, source, category, hp, existing_kws = row
            # 人工已处理 → 保留人工标注，不覆写
            if hp:
                try:
                    return json.loads(existing_kws) if existing_kws else []
                except (json.JSONDecodeError, TypeError):
                    return []
        kws = extract_keywords(title, source, category)
        with self._conn() as conn:
            conn.execute("UPDATE articles SET keywords=? WHERE id=?",
                         (json.dumps(kws, ensure_ascii=False), article_id))
            conn.commit()
        return kws

    def calculate_priority(self, article_id: int, conn: Optional[sqlite3.Connection] = None) -> float:
        """
        五维优先级评分 (0.0~1.0)
        A: 来源权威 (0.20)
        B: 多源覆盖 (0.15) — 所属事件的文章数
        C: 内容主题 (0.40)
        D: 时效性   (0.10)
        E: 人工反馈 (0.15)
        """
        close = conn is None
        if close:
            conn = self._conn()
        try:
            row = conn.execute("""
                SELECT a.title, a.source, a.fetched_at, a.priority_label,
                       a.human_verified, a.category, a.human_processed
                FROM articles a WHERE a.id=?
            """, (article_id,)).fetchone()
            if not row:
                return 0.0
            title, source, fetched_at, label, verified, category, hp = row

            # 人工已处理 — 保留人工评分/标签，跳过自动计算
            if hp or (label != 'unset' and label in ('high', 'medium', 'low')):
                label_scores = {'high': 0.9, 'medium': 0.6, 'low': 0.3}
                score = label_scores.get(label, 0.5)
                _, c_label = topic_score(title)
                tc = self.TOPIC_CATEGORY_MAP.get(c_label, '其他')
                conn.execute("UPDATE articles SET priority_score=?, topic_category=? WHERE id=?",
                             (score, tc, article_id))
                if close:
                    conn.commit()
                return score

            # A: 来源权威
            a_score = source_authority(source)

            # B: 多源覆盖（所属事件的文章数）
            b_score = 0.0
            evt = conn.execute("""
                SELECT e.article_count FROM events e
                JOIN article_events ae ON ae.event_id = e.id
                WHERE ae.article_id=?
            """, (article_id,)).fetchone()
            if evt:
                b_score = min(evt[0], 5) / 5.0

            # C: 内容主题
            c_score, c_label = topic_score(title)

            # D: 时效性
            try:
                days_old = (datetime.now() - datetime.fromisoformat(fetched_at)).days
            except:
                days_old = 0
            d_score = max(0.0, 1.0 - days_old * 0.2)

            # E: 人工反馈
            e_score = 0.0
            feedbacks = conn.execute("""
                SELECT field, new_value FROM human_feedback
                WHERE article_id=? AND applied=1
            """, (article_id,)).fetchall()
            for field, val in feedbacks:
                if field == 'priority_label' and val == 'high':
                    e_score += 0.3
                elif field == 'priority_label' and val == 'excluded':
                    e_score -= 0.5
            # 同类反馈漂移
            drift = self._get_source_topic_drift(source, c_label, conn)
            e_score += drift

            final = round(a_score * 0.20 + b_score * 0.15 + c_score * 0.40 + d_score * 0.10 + max(0, e_score) * 0.15, 4)
            final = max(0.0, min(1.0, final))

            # 同步写入 topic_category
            tc = self.TOPIC_CATEGORY_MAP.get(c_label, '其他')

            conn.execute("UPDATE articles SET priority_score=?, topic_category=? WHERE id=?",
                         (final, tc, article_id))
            if close:
                conn.commit()
            return final
        finally:
            if close:
                conn.close()

    def _get_source_topic_drift(self, source: str, topic_label: str,
                                conn: sqlite3.Connection) -> float:
        """E维度的源+主题漂移"""
        if not topic_label:
            return 0.0
        # 统计该源+该主题下的人工标记分布
        row = conn.execute("""
            SELECT
                SUM(CASE WHEN hf.new_value='high' THEN 1 ELSE 0 END),
                SUM(CASE WHEN hf.new_value='excluded' THEN 1 ELSE 0 END),
                COUNT(*)
            FROM human_feedback hf
            JOIN articles a ON a.id = hf.article_id
            WHERE hf.field='priority_label' AND a.source=? AND a.category=?
        """, (source, topic_label)).fetchone()
        if not row or row[2] < 5:  # 少于5条反馈不漂移
            return 0.0
        high_count, excluded_count, total = row
        drift = 0.0
        if total > 0:
            if high_count / total > 0.6:
                drift += 0.1
            if excluded_count / total > 0.4:
                drift -= 0.1
        return drift

    def update_all_priorities(self) -> int:
        """全量重算所有文章的优先级"""
        with self._conn() as conn:
            ids = conn.execute("SELECT id FROM articles").fetchall()
        for (aid,) in ids:
            self.calculate_priority(aid)
        return len(ids)

    # ═══════════════════════════════════════════════════════
    # 事件关联
    # ═══════════════════════════════════════════════════════

    def link_articles_to_events(self, threshold: float = 0.35) -> int:
        with self._conn() as conn:
            unlinked = conn.execute("""
                SELECT a.id, a.title, a.published_date, a.fetched_at
                FROM articles a
                LEFT JOIN article_events ae ON a.id = ae.article_id
                WHERE ae.article_id IS NULL
                AND a.category NOT IN ('platform_hotlists', 'bilibili_videos')
            """).fetchall()
            if not unlinked:
                return 0
            active_events = conn.execute(
                "SELECT id, title FROM events WHERE status='active'"
            ).fetchall()
            new_events = 0
            for art_id, art_title, pub_date, fetched_at in unlinked:
                # 优先使用真实发布日期，无日期时回退到抓取日期
                event_date = (pub_date or '')[:10] if pub_date else fetched_at[:10]
                best_event = None
                best_score = 0
                art_entities = extract_entities(art_title)
                for evt_id, evt_title in active_events:
                    sim = title_similarity(art_title, evt_title)
                    evt_entities = extract_entities(evt_title)
                    entity_overlap = len(set(art_entities) & set(evt_entities))
                    score = sim * 0.6 + (entity_overlap / max(len(art_entities), 1)) * 0.4
                    if score > best_score:
                        best_score = score
                        best_event = evt_id
                if best_event and best_score >= threshold:
                    conn.execute("""
                        INSERT OR IGNORE INTO article_events (article_id, event_id, relevance)
                        VALUES (?, ?, ?)
                    """, (art_id, best_event, round(best_score, 2)))
                    conn.execute("""
                        UPDATE events SET last_seen=?, article_count=article_count+1 WHERE id=?
                    """, (event_date, best_event))
                else:
                    event_title = art_title[:80]
                    cur = conn.execute("""
                        INSERT INTO events (title, first_seen, last_seen, status)
                        VALUES (?, ?, ?, 'active')
                    """, (event_title, event_date, event_date))
                    evt_id = cur.lastrowid
                    conn.execute("""
                        INSERT INTO article_events (article_id, event_id)
                        VALUES (?, ?)
                    """, (art_id, evt_id))
                    new_events += 1
                    active_events.append((evt_id, event_title))
            conn.commit()
            # 重算 B 维度
            for art_id, _, _, _ in unlinked:
                self.calculate_priority(art_id, conn)
            conn.commit()
        return new_events

    # ═══════════════════════════════════════════════════════
    # 人工反馈
    # ═══════════════════════════════════════════════════════

    def record_feedback(self, article_id: int, field: str, new_value: str,
                        old_value: str = '') -> bool:
        """
        记录人工反馈并触发后续逻辑。
        field: 'priority_label' | 'keywords' | 'excluded'
        """
        now = datetime.now().isoformat(timespec='seconds')
        with self._conn() as conn:
            if field == 'excluded':
                conn.execute("UPDATE articles SET human_verified=-1 WHERE id=?", (article_id,))
                conn.execute("""
                    INSERT INTO human_feedback (article_id, field, old_value, new_value, created_at)
                    VALUES (?, 'priority_label', ?, 'excluded', ?)
                """, (article_id, old_value, now))
            elif field == 'priority_label':
                conn.execute("UPDATE articles SET priority_label=?, human_verified=1 WHERE id=?",
                             (new_value, article_id))
                conn.execute("""
                    INSERT INTO human_feedback (article_id, field, old_value, new_value, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (article_id, field, old_value, new_value, now))
                # 重算评分
                self.calculate_priority(article_id, conn)
            elif field == 'keywords':
                conn.execute("UPDATE articles SET human_tags=? WHERE id=?",
                             (json.dumps(new_value.split(','), ensure_ascii=False), article_id))
                conn.execute("""
                    INSERT INTO human_feedback (article_id, field, old_value, new_value, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (article_id, field, old_value, new_value, now))
            conn.commit()
        return True

    def propagate_human_tags(self, threshold: float = 0.35) -> int:
        """
        层次3: 将人工标记的标签在同事件文章中传播。
        返回补充了标签的文章数。
        """
        propagated = 0
        with self._conn() as conn:
            # 获取有人工标签的事件
            tagged_events = conn.execute("""
                SELECT DISTINCT ae.event_id
                FROM article_events ae
                JOIN articles a ON a.id = ae.article_id
                WHERE a.human_tags != '[]' AND a.human_tags != '[]'
            """).fetchall()
            for (evt_id,) in tagged_events:
                # 获取该事件的所有人工标签
                human_tags = set()
                tagged_articles = conn.execute("""
                    SELECT a.human_tags FROM article_events ae
                    JOIN articles a ON a.id = ae.article_id
                    WHERE ae.event_id=?
                """, (evt_id,)).fetchall()
                for (ht,) in tagged_articles:
                    try:
                        for t in json.loads(ht):
                            human_tags.add(t)
                    except:
                        pass
                if not human_tags:
                    continue
                tags_json = json.dumps(list(human_tags), ensure_ascii=False)
                # 传播到该事件中还没有这些标签的文章
                untagged = conn.execute("""
                    SELECT a.id, a.human_tags FROM article_events ae
                    JOIN articles a ON a.id = ae.article_id
                    WHERE ae.event_id=? AND (a.human_tags='[]' OR a.human_tags='[]')
                """, (evt_id,)).fetchall()
                for aid, existing in untagged:
                    try:
                        existing_tags = set(json.loads(existing)) if existing != '[]' else set()
                    except:
                        existing_tags = set()
                    new_tags = human_tags - existing_tags
                    if new_tags:
                        merged = list(existing_tags | new_tags)
                        conn.execute("UPDATE articles SET human_tags=? WHERE id=?",
                                     (json.dumps(merged, ensure_ascii=False), aid))
                        propagated += 1
            conn.commit()
        return propagated

    # ═══════════════════════════════════════════════════════
    # 事件关系 (Event → Event)
    # ═══════════════════════════════════════════════════════

    def link_events(self, from_event_id: int, to_event_id: int,
                    relation: str, created_by: str = 'human') -> bool:
        """在事件之间建立关系"""
        now = datetime.now().isoformat(timespec='seconds')
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO event_relations
                        (from_event_id, to_event_id, relation, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (from_event_id, to_event_id, relation, created_by, now))
                # 如果存了 before，自动创建逆关系 after
                if relation == 'before':
                    conn.execute("""
                        INSERT OR IGNORE INTO event_relations
                            (from_event_id, to_event_id, relation, created_by, created_at)
                        VALUES (?, ?, 'after', ?, ?)
                    """, (to_event_id, from_event_id, created_by, now))
                conn.commit()
            return True
        except Exception:
            return False

    def unlink_events(self, relation_id: int) -> bool:
        """删除事件关系"""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT from_event_id, to_event_id, relation FROM event_relations WHERE id=?",
                    (relation_id,)
                ).fetchone()
                if row:
                    from_e, to_e, rel = row
                    conn.execute("DELETE FROM event_relations WHERE id=?", (relation_id,))
                    if rel == 'before':
                        conn.execute("""
                            DELETE FROM event_relations
                            WHERE from_event_id=? AND to_event_id=? AND relation='after'
                        """, (to_e, from_e))
                conn.commit()
            return True
        except Exception:
            return False

    def suggest_event_relations(self, max_days: int = 7,
                                entity_threshold: int = 1,
                                time_weight: float = 0.3,
                                entity_weight: float = 0.5,
                                title_weight: float = 0.2) -> int:
        """
        自动扫描所有事件对，根据实体重叠、时间接近度、标题相似度
        推荐可能的事件关系。结果写入 event_relations(created_by='auto')。
        已有关系的事件对不会重复推荐。

        Args:
            max_days: 时间接近度阈值（天）
            entity_threshold: 最少共享实体数
            time_weight: 时间接近度权重
            entity_weight: 实体重叠权重
            title_weight: 标题相似度权重

        Returns: 新推荐的关系数
        """
        with self._conn() as conn:
            # 获取所有活跃事件
            events = conn.execute("""
                SELECT id, title, first_seen, last_seen, article_count
                FROM events WHERE status='active'
                ORDER BY last_seen DESC
            """).fetchall()

            # 获取已有关系（避免重复推荐）
            existing = set()
            for r in conn.execute(
                "SELECT from_event_id, to_event_id FROM event_relations"
            ).fetchall():
                existing.add((r[0], r[1]))
                existing.add((r[1], r[0]))  # 双向标记

            suggestions = 0
            now_date = date.today()

            for i, (eid1, title1, first1, last1, cnt1) in enumerate(events):
                # 用关键词匹配代替纯实体提取
                kws1 = set(extract_keywords(title1, '', ''))
                kws1.update(e.lower() for e in extract_entities(title1)
                           if not e.isdigit() and len(e) > 1)
                for j, (eid2, title2, first2, last2, cnt2) in enumerate(events):
                    if i >= j:
                        continue
                    if (eid1, eid2) in existing:
                        continue

                    # 时间接近度
                    try:
                        d1 = datetime.strptime(last1, '%Y-%m-%d').date()
                        d2 = datetime.strptime(last2, '%Y-%m-%d').date()
                    except:
                        continue
                    day_diff = abs((d1 - d2).days)
                    if day_diff > max_days:
                        continue
                    t_score = max(0, 1.0 - day_diff / max_days)

                    # 关键词重叠
                    kws2 = set(extract_keywords(title2, '', ''))
                    kws2.update(e.lower() for e in extract_entities(title2)
                               if not e.isdigit() and len(e) > 1)
                    overlap = kws1 & kws2
                    e_score = len(overlap) / max(len(kws1 | kws2), 1)
                    if len(overlap) < entity_threshold and e_score < 0.15:
                        continue

                    # 标题相似度
                    s_score = title_similarity(title1, title2)

                    # 综合评分
                    combined = t_score * time_weight + e_score * entity_weight + s_score * title_weight

                    if combined >= 0.2:
                        # 确定关系类型
                        if s_score > 0.3 and len(overlap) >= 2:
                            rel = 'related'
                        elif day_diff <= 1:
                            rel = 'update'
                        elif len(overlap) >= 2:
                            rel = 'related'
                        else:
                            rel = 'related'

                        # 按时间顺序确定方向
                        if d1 < d2:
                            from_e, to_e = eid1, eid2
                        else:
                            from_e, to_e = eid2, eid1

                        now = datetime.now().isoformat(timespec='seconds')
                        try:
                            conn.execute("""
                                INSERT OR IGNORE INTO event_relations
                                    (from_event_id, to_event_id, relation, created_by, created_at)
                                VALUES (?, ?, ?, 'auto', ?)
                            """, (from_e, to_e, rel, now))
                            if conn.total_changes > 0:
                                suggestions += 1
                        except:
                            continue

            conn.commit()
        return suggestions

    def get_pending_relations(self, limit: int = 50) -> list:
        """
        获取待人工确认的自动推荐关系。
        返回按推荐分排序的建议列表。
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT er.id, er.from_event_id, er.to_event_id, er.relation,
                       e1.title AS from_title, e2.title AS to_title,
                       e1.first_seen AS from_first, e2.first_seen AS to_first,
                       e1.article_count AS from_count, e2.article_count AS to_count,
                       er.created_at
                FROM event_relations er
                JOIN events e1 ON e1.id = er.from_event_id
                JOIN events e2 ON e2.id = er.to_event_id
                WHERE er.created_by = 'auto'
                ORDER BY er.id DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [
            {
                'id': r[0],
                'from_event': {'id': r[1], 'title': r[4], 'first_seen': r[6], 'article_count': r[8]},
                'to_event': {'id': r[2], 'title': r[5], 'first_seen': r[7], 'article_count': r[9]},
                'relation': r[3],
                'suggested_at': r[10],
            }
            for r in rows
        ]

    def confirm_relation(self, relation_id: int) -> bool:
        """确认自动推荐的关系（标记为 human）"""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT from_event_id, to_event_id, relation FROM event_relations WHERE id=?",
                    (relation_id,)
                ).fetchone()
                if not row:
                    return False
                from_e, to_e, rel = row
                conn.execute("""
                    UPDATE event_relations SET created_by='human' WHERE id=?
                """, (relation_id,))
                # 如果是 before，也确认逆关系
                if rel == 'before':
                    conn.execute("""
                        UPDATE event_relations SET created_by='human'
                        WHERE from_event_id=? AND to_event_id=? AND relation='after'
                    """, (to_e, from_e))
                conn.commit()
            return True
        except Exception:
            return False

    def reject_relation(self, relation_id: int) -> bool:
        """拒绝自动推荐的关系（删除）"""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT from_event_id, to_event_id, relation FROM event_relations WHERE id=?",
                    (relation_id,)
                ).fetchone()
                if row:
                    from_e, to_e, rel = row
                    conn.execute("DELETE FROM event_relations WHERE id=?", (relation_id,))
                    if rel == 'before':
                        conn.execute("""
                            DELETE FROM event_relations
                            WHERE from_event_id=? AND to_event_id=? AND relation='after'
                        """, (to_e, from_e))
                conn.commit()
            return True
        except Exception:
            return False

    def get_event_timeline(self, event_id: int) -> dict:
        """
        获取事件时间线：该事件的文章列表 + 关联事件
        """
        with self._conn() as conn:
            # 文章列表（排除 AI 已拒绝的文章）
            articles = conn.execute("""
                SELECT a.id, a.title, a.source, a.url, a.fetched_at, a.priority_score,
                       a.human_verified, a.keywords
                FROM article_events ae
                JOIN articles a ON a.id = ae.article_id
                WHERE ae.event_id=? AND (a.ai_filtered IS NULL OR a.ai_filtered != -1)
                ORDER BY a.fetched_at ASC
            """, (event_id,)).fetchall()
            # 事件本身信息
            event_info = conn.execute(
                "SELECT id, title, first_seen, last_seen, article_count FROM events WHERE id=?",
                (event_id,)
            ).fetchone()
            # 关联事件
            relations_from = conn.execute("""
                SELECT er.id, er.to_event_id, er.relation, e.title, e.first_seen, e.last_seen
                FROM event_relations er
                JOIN events e ON e.id = er.to_event_id
                WHERE er.from_event_id=?
                ORDER BY e.last_seen ASC
            """, (event_id,)).fetchall()
            relations_to = conn.execute("""
                SELECT er.id, er.from_event_id, er.relation, e.title, e.first_seen, e.last_seen
                FROM event_relations er
                JOIN events e ON e.id = er.from_event_id
                WHERE er.to_event_id=?
                ORDER BY e.last_seen ASC
            """, (event_id,)).fetchall()

        return {
            'event': {
                'id': event_info[0],
                'title': event_info[1],
                'first_seen': event_info[2],
                'last_seen': event_info[3],
                'article_count': event_info[4],
            },
            'articles': [
                {'id': a[0], 'title': a[1], 'source': a[2], 'url': a[3],
                 'date': a[4], 'score': a[5], 'verified': a[6],
                 'keywords': json.loads(a[7]) if a[7] else []}
                for a in articles
            ],
            'relations': {
                'outgoing': [
                    {'id': r[0], 'target_id': r[1], 'relation': r[2],
                     'target_title': r[3], 'target_first': r[4], 'target_last': r[5]}
                    for r in relations_from
                ],
                'incoming': [
                    {'id': r[0], 'source_id': r[1], 'relation': r[2],
                     'source_title': r[3], 'source_first': r[4], 'source_last': r[5]}
                    for r in relations_to
                ],
            }
        }

    # ═══════════════════════════════════════════════════════
    # Web UI 查询
    # ═══════════════════════════════════════════════════════

    def get_pending_review(self, min_score: float = 0.0, limit: int = 50) -> list:
        """获取待人工审核的文章"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT a.id, a.title, a.source, a.url, a.published_date,
                       a.priority_score, a.priority_label, a.keywords, a.human_tags,
                       a.fetched_at
                FROM articles a
                WHERE a.human_verified=0 AND a.priority_score >= ?
                ORDER BY a.priority_score DESC, a.fetched_at DESC
                LIMIT ?
            """, (min_score, limit)).fetchall()
        return [
            {'id': r[0], 'title': r[1], 'source': r[2], 'url': r[3],
             'published': r[4], 'score': r[5], 'label': r[6],
             'keywords': json.loads(r[7]) if r[7] else [],
             'human_tags': json.loads(r[8]) if r[8] else [],
             'fetched': r[9]}
            for r in rows
        ]

    def get_feedback_stats(self) -> dict:
        """反馈统计"""
        with self._conn() as conn:
            total_feedback = conn.execute("SELECT COUNT(*) FROM human_feedback").fetchone()[0]
            by_field = conn.execute("""
                SELECT field, COUNT(*) FROM human_feedback GROUP BY field
            """).fetchall()
            recent = conn.execute("""
                SELECT hf.field, hf.new_value, a.title, a.source, hf.created_at
                FROM human_feedback hf
                JOIN articles a ON a.id = hf.article_id
                ORDER BY hf.id DESC LIMIT 10
            """).fetchall()
            drift_active = conn.execute("""
                SELECT COUNT(DISTINCT a.source || '|' || a.category)
                FROM human_feedback hf
                JOIN articles a ON a.id = hf.article_id
                WHERE hf.applied=1
            """).fetchone()[0]
        return {
            'total_feedback': total_feedback,
            'by_field': dict(by_field),
            'recent': [
                {'field': r[0], 'value': r[1], 'article': r[2], 'source': r[3], 'date': r[4]}
                for r in recent
            ],
            'drift_active_sources': drift_active,
            'articles_total': self.get_stats()['articles'],
        }

    # ═══════════════════════════════════════════════════════
    # 评语系统
    # ═══════════════════════════════════════════════════════

    TOPIC_CATEGORY_MAP = {
        'PC/Hardware': '硬件',
        'AI/LLM': 'AI',
        'Game/New': '游戏',
        'Game/Platform': '游戏',
        'Mobile': '移动',
        'Product Launch': '发布',
        'Other': '其他',
    }

    def _build_comment_tree(self, comments: list, user_id: int = 0) -> list:
        """将平评论列表构建为树形结构（含点赞数和当前用户是否点赞）。"""
        by_parent = {}
        for c in comments:
            pid = c['parent_id']
            by_parent.setdefault(pid, []).append(c)
        def _attach(children):
            for c in children:
                c['replies'] = _attach(by_parent.get(c['id'], []))
            return children
        return _attach(by_parent.get(None, []))

    def add_comment(self, article_id: int, user_id: int, username: str,
                    content: str, parent_id: int = None) -> dict:
        """添加评语。parent_id 非空时为回复。"""
        now = datetime.now().isoformat(timespec='seconds')
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO article_comments
                    (article_id, user_id, username, parent_id, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (article_id, user_id, username, parent_id, content, now, now))
            conn.commit()
            cid = cur.lastrowid
        return {'id': cid, 'article_id': article_id, 'user_id': user_id,
                'username': username, 'parent_id': parent_id, 'content': content,
                'created_at': now, 'updated_at': now, 'like_count': 0, 'liked_by_me': False}

    def get_comments(self, article_id: int, user_id: int = 0) -> list:
        """获取文章评语（树形），含点赞统计。"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT c.id, c.article_id, c.user_id, c.username, c.parent_id,
                       c.content, c.created_at, c.updated_at
                FROM article_comments c WHERE c.article_id=?
                ORDER BY c.created_at ASC
            """, (article_id,)).fetchall()
            comments = []
            for r in rows:
                like_count = conn.execute(
                    "SELECT COUNT(*) FROM comment_likes WHERE comment_id=?", (r[0],)
                ).fetchone()[0]
                liked = False
                if user_id:
                    liked = conn.execute(
                        "SELECT 1 FROM comment_likes WHERE comment_id=? AND user_id=?",
                        (r[0], user_id)
                    ).fetchone() is not None
                comments.append({
                    'id': r[0], 'article_id': r[1], 'user_id': r[2],
                    'username': r[3], 'parent_id': r[4], 'content': r[5],
                    'created_at': r[6], 'updated_at': r[7],
                    'like_count': like_count, 'liked_by_me': liked,
                })
        return self._build_comment_tree(comments, user_id)

    def edit_comment(self, comment_id: int, user_id: int, content: str) -> bool:
        """编辑评语（仅作者本人）。"""
        now = datetime.now().isoformat(timespec='seconds')
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id FROM article_comments WHERE id=?", (comment_id,)
            ).fetchone()
            if not row or row[0] != user_id:
                return False
            conn.execute(
                "UPDATE article_comments SET content=?, updated_at=? WHERE id=?",
                (content, now, comment_id)
            )
            conn.commit()
        return True

    def delete_comment(self, comment_id: int, user_id: int) -> bool:
        """删除评语（仅作者本人）。级联删除子评语由 DB ON DELETE CASCADE 处理。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id FROM article_comments WHERE id=?", (comment_id,)
            ).fetchone()
            if not row or row[0] != user_id:
                return False
            conn.execute("DELETE FROM article_comments WHERE id=?", (comment_id,))
            conn.commit()
        return True

    def toggle_comment_like(self, comment_id: int, user_id: int) -> dict:
        """点赞/取消点赞。返回 {liked: bool, count: int}。"""
        now = datetime.now().isoformat(timespec='seconds')
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM comment_likes WHERE comment_id=? AND user_id=?",
                (comment_id, user_id)
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM comment_likes WHERE id=?", (existing[0],))
                liked = False
            else:
                conn.execute(
                    "INSERT INTO comment_likes (comment_id, user_id, created_at) VALUES (?, ?, ?)",
                    (comment_id, user_id, now)
                )
                liked = True
            count = conn.execute(
                "SELECT COUNT(*) FROM comment_likes WHERE comment_id=?", (comment_id,)
            ).fetchone()[0]
            conn.commit()
        return {'liked': liked, 'count': count}

    def get_comment_stats(self, article_ids: list) -> dict:
        """批量获取文章评语数。返回 {article_id: count}。"""
        if not article_ids:
            return {}
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT article_id, COUNT(*) FROM article_comments
                WHERE article_id IN ({','.join('?' * len(article_ids))})
                GROUP BY article_id
            """, article_ids).fetchall()
        return dict(rows)

    # ═══════════════════════════════════════════════════════
    # 低分清理
    # ═══════════════════════════════════════════════════════

    def preview_cleanup(self, threshold: float = 0.2) -> dict:
        """预览将被清理的文章（不执行删除）。"""
        with self._conn() as conn:
            count = conn.execute("""
                SELECT COUNT(*) FROM articles
                WHERE priority_score < ? AND human_processed = 0 AND human_verified = 0
                  AND category NOT IN ('platform_hotlists', 'bilibili_videos')
            """, (threshold,)).fetchone()[0]
        return {'count': count, 'threshold': threshold}

    def cleanup_low_score(self, threshold: float = 0.2) -> dict:
        """删除评分低于阈值且未被人工处理的文章。返回 {deleted: int}。"""
        with self._conn() as conn:
            # 先删除关联的评语
            ids = conn.execute("""
                SELECT id FROM articles
                WHERE priority_score < ? AND human_processed = 0 AND human_verified = 0
                  AND category NOT IN ('platform_hotlists', 'bilibili_videos')
            """, (threshold,)).fetchall()
            aid_list = [r[0] for r in ids]
            if not aid_list:
                return {'deleted': 0}
            placeholders = ','.join('?' * len(aid_list))
            conn.execute(f"DELETE FROM comment_likes WHERE comment_id IN "
                         f"(SELECT id FROM article_comments WHERE article_id IN ({placeholders}))",
                         aid_list)
            conn.execute(f"DELETE FROM article_comments WHERE article_id IN ({placeholders})", aid_list)
            conn.execute(f"DELETE FROM article_events WHERE article_id IN ({placeholders})", aid_list)
            conn.execute(f"DELETE FROM human_feedback WHERE article_id IN ({placeholders})", aid_list)
            conn.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", aid_list)
            conn.commit()
        return {'deleted': len(aid_list)}

    # ═══════════════════════════════════════════════════════
    # 主题分类
    # ═══════════════════════════════════════════════════════

    def populate_topic_categories(self) -> int:
        """为所有文章填充 topic_category。返回更新数量。"""
        updated = 0
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, source, category, topic_category FROM articles "
                "WHERE topic_category = '' AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchall()
            for aid, title, source, category, _ in rows:
                _, label = topic_score(title)
                tc = self.TOPIC_CATEGORY_MAP.get(label, '其他')
                conn.execute("UPDATE articles SET topic_category=? WHERE id=?", (tc, aid))
                updated += 1
            conn.commit()
        return updated

    def get_topic_stats(self) -> dict:
        """返回各主题分类的文章数。"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT topic_category, COUNT(*) FROM articles
                WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')
                  AND topic_category != ''
                GROUP BY topic_category ORDER BY COUNT(*) DESC
            """).fetchall()
        return dict(rows)

    def get_unmatched_events(self, min_articles: int = 1) -> list:
        """获取没有事件关系的事件（孤立事件），供 UI 建议关联"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT e.id, e.title, e.first_seen, e.article_count
                FROM events e
                WHERE e.article_count >= ?
                ORDER BY e.last_seen DESC
                LIMIT 50
            """, (min_articles,)).fetchall()
        return [
            {'id': r[0], 'title': r[1], 'first_seen': r[2], 'article_count': r[3],
             'has_relations': False}
            for r in rows
        ]

    # ═══════════════════════════════════════════════════════
    # 基础查询
    # ═══════════════════════════════════════════════════════

    def get_event_context(self, today_titles: list, max_events: int = 10) -> list:
        with self._conn() as conn:
            all_entities = set()
            for t in today_titles:
                all_entities.update(extract_entities(t))
            events = conn.execute("""
                SELECT e.id, e.title, e.first_seen, e.last_seen, e.article_count
                FROM events e WHERE e.status='active'
                ORDER BY e.last_seen DESC LIMIT ?
            """, (max_events * 3,)).fetchall()
            relevant = []
            for evt_id, evt_title, first, last, count in events:
                evt_entities = extract_entities(evt_title)
                overlap = len(all_entities & set(evt_entities))
                if overlap > 0 or any(title_similarity(evt_title, t) > 0.3 for t in today_titles):
                    timeline = conn.execute("""
                        SELECT a.title, a.source, a.fetched_at, a.url
                        FROM article_events ae JOIN articles a ON a.id = ae.article_id
                        WHERE ae.event_id=? ORDER BY a.fetched_at DESC LIMIT 5
                    """, (evt_id,)).fetchall()
                    relevant.append({
                        'event_id': evt_id, 'title': evt_title,
                        'first_seen': first, 'last_seen': last, 'article_count': count,
                        'timeline': [{'title': t, 'source': s, 'date': d, 'url': u}
                                     for t, s, d, u in timeline]
                    })
            relevant.sort(key=lambda e: e['last_seen'], reverse=True)
            return relevant[:max_events]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            articles = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')"
                " AND (ai_filtered IS NULL OR ai_filtered != -1)"
            ).fetchone()[0]
            # 仅统计 RSS 文章关联的事件，排除热榜/B站视频 + AI 已拒绝的文章
            events = conn.execute("""
                SELECT COUNT(DISTINCT ae.event_id) FROM article_events ae
                JOIN articles a ON a.id = ae.article_id
                WHERE a.category NOT IN ('platform_hotlists', 'bilibili_videos')
                AND (a.ai_filtered IS NULL OR a.ai_filtered != -1)
            """).fetchone()[0]
            active = conn.execute("""
                SELECT COUNT(DISTINCT ae.event_id) FROM article_events ae
                JOIN articles a ON a.id = ae.article_id
                JOIN events e ON e.id = ae.event_id
                WHERE a.category NOT IN ('platform_hotlists', 'bilibili_videos')
                AND (a.ai_filtered IS NULL OR a.ai_filtered != -1)
                AND e.status = 'active'
            """).fetchone()[0]
            verified = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE human_verified!=0 AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchone()[0]
            by_cat = conn.execute(
                "SELECT category, COUNT(*) FROM articles WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')"
                " AND (ai_filtered IS NULL OR ai_filtered != -1) GROUP BY category"
            ).fetchall()
            # 来源分布 — 按实际媒体名统计（如 Ars Technica、36Kr、IT之家），不按 category 聚合
            by_source = conn.execute(
                "SELECT source, COUNT(*) FROM articles WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')"
                " AND (ai_filtered IS NULL OR ai_filtered != -1) GROUP BY source ORDER BY COUNT(*) DESC"
            ).fetchall()
            # 缓存状态统计 — 与 cache.py 保持一致的口径
            # HTML 已下载到磁盘（有 local_path 且非错误标记）
            cache_cached = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%' AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchone()[0]
            # 文本已提取（可从 DB 直接阅读/分析）
            cache_text = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE text_content != '' AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchone()[0]
            # 翻译已完成
            cache_translated = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE translated_content != '' AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchone()[0]
            # 下载失败
            cache_failed = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%' AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchone()[0]
            # 从未尝试下载（排除 AI 已拒绝的文章）
            cache_pending = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')"
                " AND (local_path IS NULL OR local_path = '')"
                " AND (ai_filtered IS NULL OR ai_filtered != -1)"
            ).fetchone()[0]
            return {
                'articles': articles,
                'events': events,
                'active_events': active,
                'human_verified': verified,
                'by_category': dict(by_cat),
                'by_source': dict(by_source),
                'cache_cached': cache_cached,
                'cache_text': cache_text,
                'cache_translated': cache_translated,
                'cache_pending': cache_pending,
                'cache_failed': cache_failed,
            }

    def get_recent_articles(self, limit: int = 20) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT title, source, category, fetched_at, priority_score, priority_label, human_verified
                FROM articles ORDER BY fetched_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [{'title': r[0], 'source': r[1], 'category': r[2],
                     'date': r[3], 'score': r[4], 'label': r[5], 'verified': r[6]}
                    for r in rows]

    def get_hotlists(self, date: str = "", platforms: list = None) -> dict:
        """获取热榜/B站热门数据，按平台分组。
        date: 'YYYY-MM-DD'，为空时返回最新一批数据
        platforms: 筛选指定平台列表，默认全部
        返回 {platform_id: {count, items: [{title, url, rank, heat, ...}]}}
        """
        with self._conn() as conn:
            # 未指定日期时，使用数据中最新日期
            if not date:
                latest = conn.execute(
                    "SELECT date(fetched_at) FROM articles "
                    "WHERE category IN ('platform_hotlists','bilibili_videos') "
                    "ORDER BY fetched_at DESC LIMIT 1"
                ).fetchone()
                date = latest[0] if latest else datetime.now().strftime('%Y-%m-%d')

            result = {}
            category_map = {
                'weibo': 'platform_hotlists', 'zhihu': 'platform_hotlists',
                'douyin': 'platform_hotlists', 'toutiao': 'platform_hotlists',
                'bilibili': 'bilibili_videos',
            }
            source_patterns = {
                'weibo': 'weibo_%', 'zhihu': 'zhihu_%',
                'douyin': 'douyin_%', 'toutiao': 'toutiao_%',
                'bilibili': 'bilibili_%',
            }
            target = platforms or list(source_patterns.keys())
            for pid in target:
                cat = category_map.get(pid, 'platform_hotlists')
                pattern = source_patterns.get(pid, f'{pid}_%')
                rows = conn.execute("""
                    SELECT id, title, url, source, metadata, fetched_at, priority_label
                    FROM articles
                    WHERE category = ? AND source LIKE ? AND date(fetched_at) = ?
                    ORDER BY id ASC
                """, (cat, pattern, date)).fetchall()
                items = []
                for r in rows:
                    try:
                        meta = json.loads(r[4]) if r[4] else {}
                    except Exception:
                        meta = {}
                    items.append({
                        'id': r[0], 'title': r[1], 'url': r[2],
                        'source': r[3],
                        'rank': meta.get('rank', 0),
                        'heat': meta.get('heat', meta.get('views', '')),
                        'author': meta.get('author', ''),
                        'fetched_at': r[5],
                        'priority_label': r[6],
                    })
                items.sort(key=lambda x: x['rank'])
                result[pid] = {'count': len(items), 'items': items, 'date': date}
            return result

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

            # 缓存统计 — 仅 RSS 新闻，排除热榜
            total = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchone()[0]
            cached = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE local_path != '' AND local_path NOT LIKE '[ERR:%' "
                "AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE local_path LIKE '[ERR:%' "
                "AND category NOT IN ('platform_hotlists', 'bilibili_videos')"
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
                healthy += 1
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

    def get_fetch_sources(self, source_type: str = '') -> list:
        """返回所有源的详情列表（含健康状态、缓存覆盖率）。"""
        # 已从抓取列表中移除的源，不再显示
        _REMOVED_SOURCES = {'BBC World'}
        with self._conn() as conn:
            where = "WHERE 1=1"
            params = []
            if source_type:
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
                if src_name in _REMOVED_SOURCES:
                    continue
                if category == 'rss_news':
                    stype = 'rss'
                elif category == 'bilibili_videos':
                    stype = 'bilibili'
                else:
                    stype = 'hotlist'
                recent_logs = conn.execute("""
                    SELECT status, articles_fetched, articles_new, started_at, error_msg
                    FROM fetch_logs WHERE source_name=?
                    ORDER BY started_at DESC LIMIT 5
                """, (src_name,)).fetchall()
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


# ══════════════════════════════════════════════════════════════
# CLI 自测
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    db = NewsDB()
    stats = db.get_stats()
    print(f"📊 DB: {stats['articles']} 篇文章, {stats['events']} 个事件")
    print(f"   人工审核: {stats['human_verified']} 篇")
    for cat, n in stats['by_category'].items():
        print(f"   {cat}: {n}")

    fb = db.get_feedback_stats()
    print(f"\n📝 反馈: {fb['total_feedback']} 条记录, {fb['drift_active_sources']} 个活跃漂移源")
    print(f"待审文章: {len(db.get_pending_review(min_score=0.3))} 篇 (score>=0.3)")
    print(f"数据库: {db.db_path}")
