# 设计文档：articles 表拆分为 news_articles + trending_items

## 元信息

- **日期**：2026-06-22
- **状态**：设计已批准，待实施
- **关联**：PR #1 数据库拆表 → PR #2 后端替换 → PR #3 前端适配 → PR #4 文件化存储

## 上下文

### 问题

`articles` 单表混合了三种完全不同生命周期的实体：

| 类型 | 数量 | 生命周期 | 需要 HTML 缓存 | 需要 AI 分析 | 需要事件关联 |
|------|------|---------|:---:|:---:|:---:|
| RSS 新闻 | 2262 | 长期存储 | ✓ | ✓ | ✓ |
| 平台热搜 | 1863 | 按天滚动 | ✗ | ✗ | ✗ |
| B站视频 | 1831 | 无需缓存 | ✗ | ✗ | ✗ |

这导致：
1. 代码中散落 **40+ 处** `category NOT IN ('platform_hotlists', 'bilibili_videos')` 补丁
2. 每个需要读文件的操作都必须手动排除热搜/B站
3. 内容清洗等批量操作因遗漏过滤，hit 到 4600 条 metadata_only 文章，大量"文件不存在"错误且无限循环
4. JOIN 查询被污染（事件关联、统计都要先过滤 category）
5. 前端 API 语义不清，`ArticleSearch` 也要手动排除

### 目标

将 `articles` 拆为 `news_articles` 和 `trending_items` 两张独立表，从根本上消除所有 `category` 补丁。

### 原则

- 一刀切迁移，不留兼容层
- 数据零丢失，迁移前后自动校验
- 全固定列设计，不用 JSON 扩展列
- 完全独立 API 路由
- 文件化存储纳入设计但作为后续 PR

---

## 一、数据库 Schema

### news_articles 表

```sql
CREATE TABLE news_articles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    source           TEXT DEFAULT '',
    url              TEXT DEFAULT '',
    category         TEXT DEFAULT 'rss_news',
    published_date   TEXT,
    fetched_at       TEXT,

    -- 内容缓存
    local_path       TEXT DEFAULT '',             -- HTML 磁盘路径
    text_content     TEXT DEFAULT '',             -- 原始 HTML（PR #4 改为文件路径）
    content_lang     TEXT DEFAULT '',             -- en/zh
    content_status   TEXT DEFAULT 'pending',      -- pending/fetched/translated/dead
    content_fetched_at TEXT,
    retry_count      INTEGER DEFAULT 0,

    -- AI 处理结果
    ai_filtered      INTEGER DEFAULT 0,           -- 0=未筛选 1=通过 -1=拒绝
    ai_cleaned_content TEXT DEFAULT '',           -- 清洗后正文（PR #4 改为 cleaned_path）
    translated_content TEXT DEFAULT '',           -- 译文（PR #4 改为 translated_path）
    translated_at    TEXT,
    ai_summary       TEXT DEFAULT '',
    ai_analyzed      INTEGER DEFAULT 0,
    ai_keywords      TEXT DEFAULT '',
    ai_category      TEXT DEFAULT '',
    ai_priority_score REAL DEFAULT 0.0,
    priority_score   REAL DEFAULT 0.0,
    priority_label   TEXT DEFAULT '',

    -- 人工标注
    human_tags       TEXT DEFAULT '',
    human_processed  INTEGER DEFAULT 0,
    human_verified   INTEGER DEFAULT 0,
    keywords         TEXT DEFAULT '',
    metadata         TEXT DEFAULT '{}'
);

CREATE INDEX idx_news_status ON news_articles(content_status);
CREATE INDEX idx_news_source ON news_articles(source);
CREATE INDEX idx_news_fetched ON news_articles(fetched_at);
CREATE INDEX idx_news_published ON news_articles(published_date);
```

### trending_items 表

```sql
CREATE TABLE trending_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    platform         TEXT NOT NULL,               -- weibo/zhihu/douyin/toutiao/bilibili
    trend_type       TEXT NOT NULL DEFAULT 'hotlist',  -- hotlist / bilibili_video
    url              TEXT DEFAULT '',
    rank             INTEGER DEFAULT 0,
    heat_score       TEXT DEFAULT '',             -- 字符串（微博热度"123万"格式）

    -- B站视频特有字段（热搜为 NULL）
    video_desc       TEXT DEFAULT '',
    author           TEXT DEFAULT '',             -- UP主
    play_count       INTEGER DEFAULT 0,
    danmaku_count    INTEGER DEFAULT 0,
    cover_url        TEXT DEFAULT '',

    -- 通用
    fetched_at       TEXT NOT NULL,
    published_date   TEXT,
    metadata         TEXT DEFAULT '{}',
    text_content     TEXT DEFAULT ''              -- 标题+排名拼接文本
);

CREATE INDEX idx_trending_platform ON trending_items(platform);
CREATE INDEX idx_trending_type ON trending_items(trend_type);
CREATE INDEX idx_trending_fetched ON trending_items(fetched_at);
```

### 关联表变更

```sql
-- article_events → news_article_events
CREATE TABLE news_article_events (
    article_id INTEGER NOT NULL REFERENCES news_articles(id),
    event_id   INTEGER NOT NULL REFERENCES events(id),
    PRIMARY KEY (article_id, event_id)
);

-- article_comments 增加 content_type
ALTER TABLE article_comments ADD COLUMN content_type TEXT DEFAULT 'news';
-- 值: 'news' | 'trending'
```

### 删除

- `DROP TABLE articles`
- `DROP TABLE article_events`（已迁移到 news_article_events）

---

## 二、迁移策略

### 迁移前

1. 文件级备份：`cp news.db news.db.pre_migration_backup`
2. 记录迁移前行数用于校验

### 迁移步骤（v5，幂等）

```python
def migrate_v5(db_path):
    conn = sqlite3.connect(db_path)
    
    # 1. 创建新表
    conn.executescript(NEWS_ARTICLES_DDL)
    conn.executescript(TRENDING_ITEMS_DDL)
    
    # 2. 数据迁移
    conn.execute("""
        INSERT INTO news_articles (id, title, source, url, category, ...)
        SELECT id, title, source, url, category, ...
        FROM articles
        WHERE category NOT IN ('platform_hotlists', 'bilibili_videos')
    """)
    
    conn.execute("""
        INSERT INTO trending_items (id, title, platform, trend_type, url, ...)
        SELECT id, title,
            CASE WHEN category = 'platform_hotlists'
                THEN COALESCE(json_extract(metadata, '$.platform'), 'unknown')
                ELSE 'bilibili' END,
            CASE WHEN category = 'platform_hotlists'
                THEN 'hotlist' ELSE 'bilibili_video' END,
            url, ...
        FROM articles
        WHERE category IN ('platform_hotlists', 'bilibili_videos')
    """)
    
    # 3. 迁移关联表
    conn.execute("""
        INSERT INTO news_article_events (article_id, event_id)
        SELECT ae.article_id, ae.event_id FROM article_events ae
        INNER JOIN news_articles na ON ae.article_id = na.id
    """)
    
    # 4. article_comments 加列
    conn.execute("ALTER TABLE article_comments ADD COLUMN content_type TEXT DEFAULT 'news'")
    
    # 5. 删除旧表
    conn.execute("DROP TABLE article_events")
    conn.execute("DROP TABLE articles")
    
    # 6. 记录版本
    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (5)")
    conn.commit()
```

### 迁移后校验（自动执行，失败则抛异常阻止删旧表）

```python
def validate_migration(conn, backup_path):
    bak = sqlite3.connect(backup_path)
    
    # 校验 1：总行数
    old_total = bak.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    new_total = conn.execute("""
        SELECT (SELECT COUNT(*) FROM news_articles) +
               (SELECT COUNT(*) FROM trending_items)
    """).fetchone()[0]
    assert old_total == new_total, f"行数不匹配: {old_total} vs {new_total}"
    
    # 校验 2：抽样逐字段比对（100 行）
    sample = bak.execute("SELECT id FROM articles ORDER BY RANDOM() LIMIT 100").fetchall()
    for (aid,) in sample:
        old = bak.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        new = conn.execute("SELECT * FROM news_articles WHERE id=?", (aid,)).fetchone()
        if new is None:
            new = conn.execute("SELECT * FROM trending_items WHERE id=?", (aid,)).fetchone()
        assert old is not None and new is not None, f"ID {aid} 在新表中缺失"
    
    # 校验 3：关联表完整性
    orphans = conn.execute("""
        SELECT article_id FROM news_article_events
        WHERE article_id NOT IN (SELECT id FROM news_articles)
    """).fetchall()
    assert len(orphans) == 0, f"news_article_events 中有 {len(orphans)} 条孤立记录"
    
    bak.close()
```

### 回滚

如果校验失败：
1. 不执行 `DROP TABLE articles`
2. 记录错误日志
3. 手动恢复：`cp news.db.pre_migration_backup news.db`

---

## 三、API 路由设计

### 新闻路由 `/api/news`（从 api/articles.py 拆出）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/news` | 新闻列表（分页+筛选+搜索，无 category 过滤） |
| GET | `/api/news/{id}` | 单篇详情 |
| PUT | `/api/news/{id}` | 更新（人工标注） |
| POST | `/api/news/{id}/analyze` | 单篇 AI 分析 |
| POST | `/api/news/{id}/clean` | 单篇内容清洗 |
| GET | `/api/news/{id}/html` | 获取原始 HTML |
| GET | `/api/news/status` | 缓存状态统计 |

### 热搜路由 `/api/trending`（新建）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/trending` | 热搜列表（按平台/日期筛选） |
| GET | `/api/trending/{id}` | 单条详情 |
| GET | `/api/trending/platforms` | 可用平台列表 |

### Pipeline 路由 `/api/pipeline`

路径不变，内部全改为操作 `news_articles`，**移除所有 `category NOT IN` 和 `local_path` 冗余条件**，统一改为 `content_status IN ('fetched', 'translated')`。

### 抓取路由 `/api/fetch`

适配两表：
- RSS 源和重试 → 只查 `news_articles`
- overview → 两表分别统计后合并返回

### 统计路由 `/api/stats`

两表分别查询，后端合并。

### 事件路由 `/api/events`

不变。`events` 表结构不动。

---

## 四、Pipeline 简化

### 统一替换模式

```
移除: local_path != '' AND local_path NOT LIKE '[ERR:%'
      AND category NOT IN ('platform_hotlists', 'bilibili_videos')
      AND content_status NOT IN ('dead', 'metadata_only')

替换为: content_status IN ('fetched', 'translated')
```

### 涉及文件（15 处 SQL 条件替换）

| 文件 | 函数/范围 |
|------|----------|
| `api/pipeline.py` | `_batch_translate`, `_batch_clean`, `_batch_analyze`, `_batch_ai_keywords`, `_batch_ai_classify`, `_batch_ai_score`, `_batch_ai_filter`, `_batch_ai_recluster`, 及所有 `start_batch_*` / `get_batch_*_status` 计数查询 |
| `pipeline/fetch_content.py` | `archive_pages()` — `content_status = 'pending'` |
| `pipeline/clean_content.py` | `clean_articles()` |
| `pipeline/translate_content.py` | `translate_articles()` |
| `pipeline/ai_filter.py` | `filter_articles()` — `content_status = 'pending'` |
| `pipeline/analyze.py` | 关键词提取查询 |
| `api/cache.py` | `_CACHE_SCOPE` — `content_status IN ('pending','fetched','translated')` |
| `db/news_db.py` | `link_articles_to_events()` — `content_status IN ('fetched','translated')` |
| `retry_failed.py` / `retry_simple.py` | 移除冗余 `category NOT IN` |
| `api/fetch.py` | 重试查询，移除冗余 `category NOT IN` |

---

## 五、前端适配

| 页面/组件 | 改动量 | 说明 |
|----------|:---:|------|
| `api/client.ts` | 中 | 拆分 `newsApi` + `trendingApi`，移除旧 `articlesApi` |
| `ArticleSearch.tsx` | 中 | 改为 `/api/news`，移除 category 筛选 UI |
| `Dashboard.tsx` | 小 | 统计从两个端点取数，合并展示 |
| `FetchMonitor.tsx` | 小 | 适配 news_articles 字段 |
| Settings 子面板 | 小 | 缓存面板只显示新闻缓存状态 |
| `Workspace.tsx` / `ChainList.tsx` | 无 | events 表驱动，不受影响 |

---

## 六、文件化存储（PR #4，后续）

```
content/
├── raw/          ← 原始 HTML
│   └── {id}.html
├── cleaned/      ← 清洗后纯净正文
│   └── {id}.html
└── translated/   ← 翻译后中文 HTML
    └── {id}.html
```

`news_articles` 字段变更：
```
text_content       → local_path        'raw/42.html'
ai_cleaned_content → cleaned_path      'cleaned/42.html'
translated_content → translated_path   'translated/42.html'
```

`content_status` 扩展：`pending → fetched → cleaned → translated`

---

## 七、风险与回滚

| 风险 | 缓解 |
|------|------|
| 迁移中断导致数据不一致 | `BEGIN IMMEDIATE` 包裹整个迁移，失败自动回滚 |
| 迁移后校验不通过 | 不删旧表，记录详细差异日志 |
| 前端 API 变更导致页面空白 | 前端构建后先在测试环境验证 |
| Pipeline 条件替换遗漏 | 用 grep 扫描全量 `category NOT IN` 残留，确保清零 |
| 文件级备份占用磁盘 | 迁移完成后可手动清理 `.pre_migration_backup` |

### 回滚

```bash
# 恢复数据库
cp news.db.pre_migration_backup news.db
# 回退代码
git revert <migration-commit>
# 重启
bash start_platform.sh restart
```

---

## 八、分阶段实施

| PR | 内容 | 预计 |
|----|------|------|
| PR #1 | 数据库拆表 + v5 迁移 + 备份校验 | 2-3h |
| PR #2 | 后端替换：API 拆分 + Pipeline 清理 + stats/fetch 适配 | 3-4h |
| PR #3 | 前端适配：client + ArticleSearch + Dashboard + FetchMonitor | 2-3h |
| PR #4 | 文件化存储（后续单独计划） | TBD |
