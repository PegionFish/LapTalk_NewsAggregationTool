"""
OpenAI-compatible API client wrapper.
Supports OpenAI, DeepSeek, Ollama, or any compatible endpoint.
"""
from openai import OpenAI
from config import config


def get_client() -> OpenAI:
    return OpenAI(
        base_url=config.openai_base_url,
        api_key=config.openai_api_key or 'sk-placeholder',
        timeout=30.0,
    )


def chat(prompt: str, system_prompt: str = "You are a helpful assistant.", max_tokens: int = 4096) -> str:
    """Simple chat completion. Returns the response text."""
    client = get_client()
    resp = client.chat.completions.create(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def summarize_events(articles_text: str) -> str:
    """基于一组文章标题生成简洁准确的事件名称。"""
    return chat(
        f"以下是关于同一话题的多篇新闻标题。请生成一个简洁准确的事件名称（20 字以内），覆盖所有标题的核心内容：\n\n{articles_text}",
        system_prompt=(
            "你是资深科技新闻编辑。只输出事件名称，不输出解释或 markdown。"
            "名称应具体可识别（包含关键产品名/公司名/技术名），避免模糊标签。"
        ),
        max_tokens=100,
    )


def build_chain_title(events_text: str) -> str:
    """为共享关键词的一组事件生成逻辑链标题。输入仅事件标题列表，极短上下文。"""
    client = get_client()
    resp = client.chat.completions.create(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": (
                "你是资深科技新闻编辑。请基于事件列表提炼一个简洁准确的主题名称。"
                "主题应涵盖所有事件的核心共同点，具体可识别（包含关键产品名/公司名/技术名）。"
                "只输出主题名称，不要解释。"
            )},
            {"role": "user", "content": f"以下是一组相关科技事件，请生成一个概括性主题名称（20 字以内，中文）：\n\n{events_text}"},
        ],
        temperature=0.5,
        max_tokens=100,
    )
    return resp.choices[0].message.content or ""


def analyze_article(title: str, text: str) -> str:
    """对单篇科技新闻文章生成中文分析摘要。直接传入完整正文，利用 DeepSeek V3.2 160K 上下文。"""
    return chat(
        f"请深入分析以下科技新闻，输出结构化摘要（300 字以内）：\n\n"
        f"标题：{title}\n"
        f"正文：{text}\n\n"
        f"输出格式：\n"
        f"📌要点：核心事实（3-5 条要点）\n"
        f"🔬背景：技术/行业背景与来龙去脉\n"
        f"📊影响：对行业、市场、消费者的潜在影响\n"
        f"🏷️关键实体：涉及的公司、产品、人物、技术",
        system_prompt=(
            "你是资深科技新闻分析师。用中文输出，深入、准确、有洞察。"
            "技术名词、产品名、公司名、代码库保留英文原文。"
            "对信息不足的维度明确标注「暂无相关信息」。"
            "基于正文实际内容进行分析，不要凭空推测。"
        ),
        max_tokens=2048,
    )


# ══════════════════════════════════════════════════════════════
# AI 接管规则 — 替代 news_db.py 硬编码逻辑
# ══════════════════════════════════════════════════════════════

def _ai_json(prompt: str, system_prompt: str, max_tokens: int = 1024) -> dict | list | None:
    """调用 AI 并解析 JSON 返回。失败时返回 None。"""
    import json
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=config.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # 去除可能的 markdown 代码块包裹
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw)
    except Exception:
        return None


def extract_keywords_ai(title: str, text: str, source: str = "") -> list[str]:
    """AI 从标题+正文中提取技术关键词。直接传入完整正文。返回关键词列表，失败返回 None。"""
    result = _ai_json(
        f"标题：{title}\n来源：{source}\n正文：{text}\n\n"
        f"提取 5-15 个技术关键词，返回 JSON 数组。关键词应覆盖：产品名、公司名、技术名、核心概念。",
        "你是科技新闻关键词提取引擎。只输出 JSON 数组，如 [\"GPU\",\"NVIDIA\",\"Blackwell\",\"AI训练\"]。"
        "技术名词、产品名、公司名保留英文原文。关键词按重要性排序。",
        300,
    )
    if isinstance(result, list) and len(result) > 0:
        return [str(k) for k in result if isinstance(k, str)]
    return None


def classify_article_ai(title: str, text: str) -> dict | None:
    """AI 分类文章主题。直接传入完整正文。返回 {category, tags, score}，失败返回 None。"""
    result = _ai_json(
        f"标题：{title}\n正文：{text}\n\n请输出 JSON："
        f'{{"category":"细分领域（AI/LLM, PC/Hardware, Mobile, Gaming, Security, Semiconductors, Enterprise, Automotive, Space, Chip/Wafer, OpenSource, Regulation, Other）",'
        f'"tags":["标签1","标签2","标签3","标签4","标签5"],'
        f'"score":0.1-1.0（综合重要性评估，考虑技术突破性、行业影响、时效性）}}',
        "你是科技新闻分类引擎。只输出 JSON，不输出其他内容。技术名词保留英文原文。",
        400,
    )
    if isinstance(result, dict) and "category" in result:
        return result
    return None


def score_priority_ai(title: str, text: str, source: str, days_old: int = 0) -> dict | None:
    """AI 评估文章优先级。直接传入完整正文。返回 {score, label, reason}。"""
    result = _ai_json(
        f"标题：{title}\n来源：{source}\n发布天数：{days_old}\n正文：{text}\n\n"
        f"请输出 JSON：{{"
        f'"score":0.0-1.0（综合评分：来源权威性30% + 内容重要性40% + 时效性30%），'
        f'"label":"high/medium/low（高/中/低优先级。high:>=0.7, medium:0.35-0.7, low:<0.35）",'
        f'"reason":"30字以内理由，说明核心判断依据"}}',
        "你是科技新闻优先级评估引擎。考虑技术突破性、行业影响范围、信息稀缺性。只输出 JSON。",
        400,
    )
    if isinstance(result, dict) and "score" in result:
        return result
    return None


def assess_event_similarity_ai(title1: str, title2: str, kw1: str = "", kw2: str = "") -> dict | None:
    """AI 判定两篇文章是否为同一事件。返回 {similar, confidence}。"""
    prompt = f"文章A：{title1}\n文章B：{title2}"
    if kw1 or kw2:
        prompt += f"\nA关键词：{kw1}\nB关键词：{kw2}"
    result = _ai_json(
        prompt + f"\n\n请输出 JSON：{{"
        f'"similar":true/false（是否报道同一事件），'
        f'"confidence":0.0-1.0（置信度），'
        f'"reason":"20字以内理由（可选）"}}',
        "你是新闻事件聚类专家。判断两篇文章是否指同一具体事件（同一产品发布、同一漏洞披露、同一收购等）。只输出 JSON。",
        300,
    )
    if isinstance(result, dict) and "similar" in result:
        return result
    return None


def suggest_event_relation_ai(title1: str, title2: str) -> dict | None:
    """AI 推断两事件之间的关系类型。返回 {relation, confidence, reason}。"""
    result = _ai_json(
        f"事件A：{title1}\n事件B：{title2}\n\n"
        f"请判定事件A与事件B的关系并输出 JSON：{{"
        f'"relation":"before/after/update/spawn/related/unrelated（A相对于B的关系：before=先于B发生，after=后于B发生，update=对B的更新/补充，spawn=导致/催生B，related=一般相关，unrelated=无关）",'
        f'"confidence":0.0-1.0（置信度），'
        f'"reason":"30字以内理由（必填，说明判断依据）"}}',
        "你是新闻事件关系分析专家。仔细分析因果关系和时间先后。只输出 JSON。",
        400,
    )
    if isinstance(result, dict) and "relation" in result:
        return result
    return None


def generate_event_summary_ai(titles_block: str) -> str:
    """AI 为一组事件文章生成综合摘要。"""
    return chat(
        f"以下是一组关于同一事件的文章标题。请生成一段中文综合摘要（150 字以内），概括核心内容和不同角度的报道侧重：\n\n{titles_block}",
        system_prompt=(
            "你是资深科技新闻编辑。用中文输出简洁全面的摘要，覆盖事件核心事实和不同报道角度。"
            "技术名词、产品名、公司名保留英文原文。"
            "只输出摘要，不要标题或解释。"
        ),
        max_tokens=512,
    )


# ══════════════════════════════════════════════════════════════
# 蒸馏数据全景图 — 利用 160K 上下文做全局推理
# ══════════════════════════════════════════════════════════════

def build_panoramic_context(conn) -> str:
    """从数据库组装蒸馏后的事件全景图：事件列表 + 关键词 + 已有关系。"""
    import json

    # 活跃事件（按文章数降序）
    events = conn.execute("""
        SELECT e.id, e.title, e.article_count, e.first_seen, e.ai_summary
        FROM events e
        WHERE e.status = 'active' AND e.article_count >= 1
        ORDER BY e.article_count DESC
    """).fetchall()

    # 每个事件的关键词聚合
    event_kws = {}
    for evt_id, _, _, _, _ in events:
        rows = conn.execute("""
            SELECT a.ai_keywords, a.keywords FROM articles a
            JOIN article_events ae ON ae.article_id = a.id
            WHERE ae.event_id = ?
        """, (evt_id,)).fetchall()
        kws = set()
        for (ai_kw, kw) in rows:
            for src in (ai_kw, kw):
                try:
                    for k in json.loads(src or '[]'):
                        if len(k) > 1 and k.lower() not in ('news', 'rss_news', 'hotlist'):
                            kws.add(k)
                except (json.JSONDecodeError, TypeError):
                    pass
        if kws:
            event_kws[evt_id] = kws

    # 已有事件关系
    relations = conn.execute("""
        SELECT r.from_event_id, r.to_event_id, r.relation
        FROM event_relations r
    """).fetchall()

    # 组装结构化文本
    lines = []
    lines.append(f"=== 事件全景图（共 {len(events)} 个活跃事件）===\n")

    for evt_id, title, count, first_seen, summary in events:
        kws = event_kws.get(evt_id, set())
        kw_str = ", ".join(sorted(kws)) if kws else "无"
        summary_str = f" | 摘要: {summary[:100]}" if summary else ""
        lines.append(f"[#{evt_id}] {title} (文章×{count}, 首次:{first_seen})")
        lines.append(f"  关键词: {kw_str}{summary_str}")

    if relations:
        lines.append(f"\n=== 已有事件关系（共 {len(relations)} 条）===")
        for from_id, to_id, rel in relations:
            lines.append(f"  #{from_id} --{rel}--> #{to_id}")

    return "\n".join(lines)


def rank_events_panoramic(context: str) -> list[dict] | None:
    """基于全景图对所有事件做全局优先级排序。返回 [{id, rank, reason}]。"""
    result = _ai_json(
        f"以下是当前所有活跃科技事件的全景图：\n\n{context}\n\n"
        f"请对所有事件按综合重要性排序（从最重要到最不重要），输出 JSON 数组：\n"
        f'[{{"id":事件ID,"rank":排名(从1开始),"reason":"15字以内排序理由"}}]\n\n'
        f"排序标准：技术突破性 > 行业影响范围 > 多源覆盖度 > 时效性。"
        f"同一家公司/产品的连续报道应整体排高。已有关系的事件组应相邻排列。",
        "你是资深科技新闻编辑，负责全局事件优先级排序。"
        "只输出 JSON 数组，不输出其他内容。",
        4096,
    )
    if isinstance(result, list):
        return result
    return None


def build_chains_panoramic(context: str) -> list[dict] | None:
    """基于全景图识别应构筑逻辑链的事件分组。返回 [{events:[id...], title:"链标题", reason:"理由"}]。"""
    result = _ai_json(
        f"以下是当前所有活跃科技事件的全景图：\n\n{context}\n\n"
        f"请识别应该构筑为逻辑链的事件分组。逻辑链是指一组有因果、时间先后、"
        f"或同一产品/公司发展脉络关联的事件序列。\n\n"
        f"输出 JSON 数组：\n"
        f'[{{"events":[事件ID列表],"title":"20字以内链标题","reason":"15字以内分组理由"}}]\n\n'
        f"规则：\n"
        f"1. 每组至少 2 个事件\n"
        f"2. 同一事件可以出现在多个链中\n"
        f"3. 关注因果链（A导致B导致C）、时间线（同一产品迭代）、竞争对比\n"
        f"4. 仅标题相似但无实质关联的事件不要强行分组",
        "你是资深科技新闻编辑，擅长识别事件之间的深层关联。"
        "只输出 JSON 数组，不输出其他内容。",
        4096,
    )
    if isinstance(result, list):
        return result
    return None
