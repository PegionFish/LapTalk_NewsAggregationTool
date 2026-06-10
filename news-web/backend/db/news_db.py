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
    'BBC Technology': 0.6, 'BBC World': 0.4, 'NPR Technology': 0.6,
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
                               ('translated_at','TEXT')]:
                try:
                    conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {dtype}")
                except sqlite3.OperationalError:
                    pass
            # 迁移：给 events 表加 priority_label
            try:
                conn.execute("ALTER TABLE events ADD COLUMN priority_label TEXT DEFAULT 'medium'")
            except sqlite3.OperationalError:
                pass
            conn.commit()

    # ═══════════════════════════════════════════════════════
    # 保存
    # ═══════════════════════════════════════════════════════

    def save_articles(self, category: str, articles: list) -> int:
        if not articles:
            return 0
        now = datetime.now().isoformat(timespec='seconds')
        saved = 0
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
                except Exception:
                    continue
            conn.commit()
        return saved

    # ═══════════════════════════════════════════════════════
    # 关键词提取 + 优先级评分
    # ═══════════════════════════════════════════════════════

    def extract_keywords_for(self, article_id: int) -> list:
        """为指定文章提取关键词并更新 DB"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT title, source, category FROM articles WHERE id=?",
                (article_id,)
            ).fetchone()
            if not row:
                return []
            title, source, category = row
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
                       a.human_verified, a.category
                FROM articles a WHERE a.id=?
            """, (article_id,)).fetchone()
            if not row:
                return 0.0
            title, source, fetched_at, label, verified, category = row

            # 人工锁定 — 跳过自动计算
            if label != 'unset' and label in ('high', 'medium', 'low'):
                label_scores = {'high': 0.9, 'medium': 0.6, 'low': 0.3}
                score = label_scores.get(label, 0.5)
                conn.execute("UPDATE articles SET priority_score=? WHERE id=?",
                             (score, article_id))
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

            conn.execute("UPDATE articles SET priority_score=? WHERE id=?",
                         (final, article_id))
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
                SELECT a.id, a.title, a.fetched_at
                FROM articles a
                LEFT JOIN article_events ae ON a.id = ae.article_id
                WHERE ae.article_id IS NULL
            """).fetchall()
            if not unlinked:
                return 0
            active_events = conn.execute(
                "SELECT id, title FROM events WHERE status='active'"
            ).fetchall()
            new_events = 0
            for art_id, art_title, fetched_at in unlinked:
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
                    """, (fetched_at[:10], best_event))
                else:
                    event_title = art_title[:80]
                    today = fetched_at[:10]
                    cur = conn.execute("""
                        INSERT INTO events (title, first_seen, last_seen, status)
                        VALUES (?, ?, ?, 'active')
                    """, (event_title, today, today))
                    evt_id = cur.lastrowid
                    conn.execute("""
                        INSERT INTO article_events (article_id, event_id)
                        VALUES (?, ?)
                    """, (art_id, evt_id))
                    new_events += 1
                    active_events.append((evt_id, event_title))
            conn.commit()
            # 重算 B 维度
            for art_id, _, _ in unlinked:
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
            # 文章列表
            articles = conn.execute("""
                SELECT a.id, a.title, a.source, a.url, a.fetched_at, a.priority_score,
                       a.human_verified, a.keywords
                FROM article_events ae
                JOIN articles a ON a.id = ae.article_id
                WHERE ae.event_id=?
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
            articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            active = conn.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0]
            verified = conn.execute("SELECT COUNT(*) FROM articles WHERE human_verified!=0").fetchone()[0]
            by_cat = conn.execute(
                "SELECT category, COUNT(*) FROM articles GROUP BY category"
            ).fetchall()
            # 缓存状态统计
            cache_cached = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE content_status IN ('fetched','translated')"
            ).fetchone()[0]
            cache_pending = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE content_status='pending'"
            ).fetchone()[0]
            cache_failed = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE content_status='failed'"
            ).fetchone()[0]
            return {
                'articles': articles,
                'events': events,
                'active_events': active,
                'human_verified': verified,
                'by_category': dict(by_cat),
                'cache_cached': cache_cached,
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
