# 事件管线架构重构设计

**日期**: 2026-06-24  
**状态**: 已确认  
**范围**: 文章处理完成后的全部逻辑 — 事件聚类 / 摘要 / 关系检测 / 逻辑链构建

---

## 1. 现状分析

### 1.1 当前流程

```
抓取 → AI预筛选 → HTML缓存 → process_article(清洗→翻译→KCS)
                                    ↓
                            link_articles_to_events()
                            (bigram Jaccard, 阈值0.35)
                                    ↓
                            3866 事件 (85% 单篇, 55% 零关联)
                                    ↓
                            _nightly(): recluster → summarize → build_chains
                                    ↓
                            build_panoramic_context(全部3866) → 926K chars
                                    ↓
                            AI 返回 dict 非 array (json_object 冲突) → 0 链
```

### 1.2 根因诊断

| 问题 | 根因 | 影响 |
|------|------|------|
| 3866 个事件, 85% 单篇 | `link_articles_to_events()` 使用 bigram Jaccard 做事件聚类 | 垃圾事件爆炸 |
| 中英文事件完全断裂 | bigram 无法跨语言匹配 (sim=0.000) | 同一事件的英/中报道分裂为独立事件 |
| 0 条逻辑链 | `build_chains_panoramic()` 因 `json_object` 格式冲突返回 None | 管线白跑 |
| 锁泄漏 + 状态不更新 | `_nightly()` 缺少 try/finally 保护 | 服务重启后状态卡死 |

bigram 相似度实测：

```
"iOS 27 Siri AI 防沉迷" vs "iOS 27 地图"     → 0.102  (阈值 0.35 远达不到)
"iOS 27 Siri AI 防沉迷" vs "CarPlay in iOS 27" → 0.000  (中英文完全不通)
```

### 1.3 P0/P1 修复 (已完成)

- `_ai_json()` 异常记录日志
- `build_chains_panoramic()` / `rank_events_panoramic()` 显式 `response_format=None`
- `_nightly()` try/finally 锁保护
- `start_platform.sh` 表名 `articles` → `news_articles`

---

## 2. 新架构

### 2.1 核心原则

1. **事件聚类下沉** — 文章处理时完成语义匹配，不依赖后置批处理
2. **事件定义** — 采用分层模型：单篇文章标记 `pending_cluster`，≥2 篇交叉验证才创建事件
3. **事件管线轻量化** — 聚类已完成，管线只做摘要 + 关系 + 逻辑链
4. **增量处理** — 新文章匹配已有事件，已有数据不重算
5. **全量全景图过滤** — 只对 `article_count >= 2` 的事件构建全景图

### 2.2 新流程

```
文章处理 (process_article)                  事件管线 (_nightly)
═══════════════════════════════             ══════════════════════════
                                           
清洗 → 翻译 → KCS (含 category + keywords)  
        ↓                                   
语义事件匹配 (NEW — 替换 bigram)             
 ├─ 候选: 同 category + 关键词交集 + 30天内  
 ├─ AI: match_article_to_events_ai()        
 ├─ 匹配 → INSERT news_article_events       
 │          UPDATE events.article_count      
 │          content_status = 'processed'     
 ├─ 不确定 → content_status = 'pending_cluster'
 │          (每日定时批处理再尝试)           
 └─ 新事件: 仅当 ≥2 篇同源确认             
    (不在此阶段创建单篇事件)                 
                                           
                                           事件管线 (_nightly, 轻量)
                                           ══════════════════════════
                                           ① 事件摘要 (增量)
                                             仅处理新增/更新的 2+ 事件
                                           
                                           ② 事件关系检测
                                             AI 批量检测 2+ 事件对
                                           
                                           ③ 逻辑链构建
                                             panorama (仅 2+ 事件)
                                             AI 识别分组 → 写 logic_chains
```

### 2.3 数据模型变化

**news_articles.content_status 新增状态**:
- `pending_cluster` — 文章已处理完成，但尚未匹配到事件
- 每日定时处理 `pending_cluster` 文章，尝试匹配此后新产生的事件

**events 表不变，但创建逻辑改变**:
- 不再由 `link_articles_to_events()` 自动为每篇文章创建事件
- 仅在 AI 确认存在 2+ 篇独立报道时创建

**废弃函数**:
- `NewsDB.link_articles_to_events()` — bigram 聚类，完全移除
- `_run_recluster()` — 聚类已在文章处理时完成，从 nightly 中移除
- `NewsDB.suggest_event_relations()` — 规则引擎被 AI 关系检测替代

---

## 3. 实现步骤

### Step 1: 清理垃圾数据

- 删除 `news_article_events` 关联数为 0 的事件 (~2,131 个)
- 将 `article_count=1` 的事件标记为 `status='orphan'` (~3,292 个)
- 对应文章的 `content_status` 设为 `'pending_cluster'`
- 清理后预计剩余 ~319 个有效事件 (2+ 篇)

### Step 2: 重写事件聚类 — AI 语义匹配

在 `process_article()` 末尾新增 `_match_article_to_event()`:

```python
def _match_article_to_event(aid, title, category, keywords):
    """AI 语义事件匹配，替代 bigram"""
    # 1. 筛选候选事件: 同 category + 关键词交集 + 30 天内
    candidates = get_candidate_events(category, keywords, days=30)
    if not candidates:
        return None  # 标记 pending_cluster
    
    # 2. AI 判断 (已有 match_article_to_events_ai)
    result = match_article_to_events_ai(title, candidates)
    
    if result and result.get('event_id'):
        return result['event_id']  # 匹配成功
    
    return None  # 不确定, 标记 pending_cluster
```

### Step 3: 简化事件管线

`_nightly()` 从三步简化为两步：

```python
steps = [
    ("事件摘要", _run_summarize, _es_state),
    ("逻辑链构建", _run_build_chains, _chain_state),
]
# 移除: ("事件聚类", _run_recluster, _recl_state)
```

### Step 4: 修复全景图过滤

`build_panoramic_context()`:

```python
# 旧: WHERE e.status = 'active' AND e.article_count >= 1
# 新: JOIN 确保实际关联 >= 2
events = conn.execute("""
    SELECT e.id, e.title, e.article_count, e.first_seen, e.last_seen, e.ai_summary
    FROM events e
    JOIN news_article_events ae ON ae.event_id = e.id
    WHERE e.status = 'active'
    GROUP BY e.id
    HAVING COUNT(ae.article_id) >= 2
    ORDER BY e.article_count DESC
""")
```

### Step 5: 定时批处理 pending_cluster

每日新增定时任务：处理 `content_status = 'pending_cluster'` 的文章，此时可能有新事件出现可匹配。

### Step 6: 添加事件关系检测 (AI)

在 nightly 中新增 AI 事件关系检测，替代现有的 `analyze.py` 规则引擎和 `suggest_event_relations()` 规则方法。对 2+ 篇的有效事件对做 AI 批量检测。

---

## 4. 影响评估

| 维度 | 变更 |
|------|------|
| 事件数 | 3866 → ~319 (减少 92%) |
| 全景图大小 | 926K → ~80K (减少 91%) |
| 文章处理耗时 | +1 次 AI 调用/篇 (match_article_to_events_ai) |
| 事件管线耗时 | 大幅减少 (移除聚类步骤，全量上下文变小) |
| API 端点 | `/recluster` 保留但降级为手动触发；`/nightly` 从三步变两步 |

---

## 5. 待确认

- [ ] `pending_cluster` 文章的定时批处理频率 (建议: 每天 1 次，在新文章处理完成后)
- [ ] 单篇"事件"是否完全删除还是保留为 orphan 状态
- [ ] `match_article_to_events_ai()` 候选事件数上限 (当前 50)
