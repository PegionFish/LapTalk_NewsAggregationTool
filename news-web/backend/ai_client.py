"""
OpenAI 兼容 API 客户端封装。
当前默认面向 SiliconFlow DeepSeek V3.2，支持 160K 上下文、深度思考与结构化 JSON 输出。
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from config import config
from utils.text import extract_text_from_html


def _prepare_content(text: str) -> str:
    """将 HTML 正文提取纯文本，去除标签后大幅降低 token 占用。"""
    if not text:
        return ""
    return extract_text_from_html(text)


_DEEP_THINKING_INSTRUCTION = (
    "思考流程（仅用于内部推理，不要输出中间推理）："
    "1. 先从原文逐条抽取可验证事实、时间、主体、动作、数字和限定条件；"
    "2. 再区分事实、背景、影响与推测，证据不足时明确标注；"
    "3. 最后只按用户要求的最终格式输出，保持中文、具体、可执行。"
)


def get_client() -> OpenAI:
    """获取 AI 分析专用 OpenAI 兼容客户端。"""
    return OpenAI(
        base_url=config.openai_base_url,
        api_key=config.openai_api_key or 'sk-placeholder',
        timeout=300.0,
    )


def _thinking_enabled(enable_thinking: bool | None) -> bool:
    """判断本次请求是否启用 SiliconFlow enable_thinking。"""
    if enable_thinking is None:
        return config.ai_enable_thinking
    return bool(enable_thinking)


def _thinking_budget(thinking_budget: int | None) -> int | None:
    """读取本次请求的思维预算；配置关闭时不传参。"""
    if not _thinking_enabled(None):
        return None
    return thinking_budget if thinking_budget is not None else config.ai_thinking_budget


def _json_response_format(response_format: dict[str, Any] | None) -> dict[str, Any] | None:
    """启用 JSON object 输出，减少结构化任务解析失败。"""
    if response_format is not None:
        return response_format
    if config.ai_json_response_format:
        return {"type": "json_object"}
    return None


def _request_options(
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    enable_thinking: bool | None,
    thinking_budget: int | None,
    response_format: dict[str, Any] | None,
) -> dict[str, Any]:
    """组装 Chat Completions 请求参数。"""
    options: dict[str, Any] = {
        "model": config.openai_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    enabled = _thinking_enabled(enable_thinking)
    budget = _thinking_budget(thinking_budget)
    extra_body: dict[str, Any] = {}
    if enabled:
        extra_body["enable_thinking"] = True
        if budget is not None:
            extra_body["thinking_budget"] = budget
    if extra_body:
        options["extra_body"] = extra_body

    # 仅当调用方显式传入 response_format 时才施加 JSON 格式；
    # chat() 不传此参数，回归纯文本输出，避免分析摘要等被强制 JSON 化。
    if response_format is not None:
        options["response_format"] = response_format

    return options


def chat(
    prompt: str,
    system_prompt: str = "你是有帮助的助手。",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    enable_thinking: bool | None = None,
    thinking_budget: int | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    """发送单轮聊天请求并返回助手文本。"""
    from utils.rate_limiter import ai_rate_limiter as _rl

    # 估算 token 消耗（输入 + 输出上限）
    estimated = _rl.estimate_tokens(prompt + system_prompt) + max_tokens
    _rl.wait_if_needed(estimated)

    client = get_client()
    resp = client.chat.completions.create(
        **_request_options(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
            response_format=response_format,
        )
    )
    # 从响应中记录真实 token 消耗
    try:
        usage = resp.usage
        actual = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)
        _rl.record(actual)
    except Exception:
        _rl.record(estimated)

    return resp.choices[0].message.content or ""


def _strip_json(raw: str) -> str:
    """去除模型可能返回的 markdown 代码块包裹。"""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _ai_json(
    prompt: str,
    system_prompt: str,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    enable_thinking: bool | None = None,
    thinking_budget: int | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict | list | None:
    """调用 AI 并解析 JSON 返回；失败时返回 None。"""
    # 若未显式传入格式且全局开关开启，自动启用 JSON object 输出。
    if response_format is None and config.ai_json_response_format:
        response_format = {"type": "json_object"}
    try:
        from utils.rate_limiter import ai_rate_limiter as _rl

        estimated = _rl.estimate_tokens(prompt + system_prompt) + max_tokens
        _rl.wait_if_needed(estimated)

        client = get_client()
        resp = client.chat.completions.create(
            **_request_options(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
                response_format=response_format,
            )
        )
        # 记录真实 token 消耗
        try:
            usage = resp.usage
            actual = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)
            _rl.record(actual)
        except Exception:
            _rl.record(estimated)

        raw = (resp.choices[0].message.content or "").strip()
        return json.loads(_strip_json(raw))
    except Exception:
        return None


def _with_deep_thinking(prompt: str) -> str:
    """为高质量分析任务追加内部深思指令。"""
    return f"{prompt}\n\n{_DEEP_THINKING_INSTRUCTION}"


def summarize_events(articles_text: str) -> str:
    """基于一组文章标题生成简洁准确的事件名称。"""
    return chat(
        _with_deep_thinking(
            f"以下是关于同一话题的多篇新闻标题。请生成一个简洁准确的事件名称（20 字以内），覆盖所有标题的核心内容：\n\n{articles_text}"
        ),
        system_prompt=(
            "你是资深科技新闻编辑。只输出事件名称，不输出解释或 markdown。"
            "名称应具体可识别（包含关键产品名/公司名/技术名），避免模糊标签。"
        ),
        max_tokens=256,
        temperature=0.1,
    )


def build_chain_title(events_text: str) -> str:
    """为共享关键词的一组事件生成逻辑链标题。"""
    return chat(
        _with_deep_thinking(
            f"以下是一组相关科技事件，请生成一个概括性主题名称（20 字以内，中文）：\n\n{events_text}"
        ),
        system_prompt=(
            "你是资深科技新闻编辑。请基于事件列表提炼一个简洁准确的主题名称。"
            "主题应涵盖所有事件的核心共同点，具体可识别（包含关键产品名/公司名/技术名）。"
            "只输出主题名称，不要解释。"
        ),
        max_tokens=256,
        temperature=0.2,
    )


def analyze_article(title: str, text: str) -> str:
    """对单篇科技新闻文章生成中文分析摘要。HTML 提取纯文本后传入 160K 上下文。"""
    content = _prepare_content(text)
    return chat(
        _with_deep_thinking(
            f"请深入分析以下科技新闻，输出结构化摘要（800-1200 字，必要时可更长）：\n\n"
            f"标题：{title}\n"
            f"正文：{content}\n\n"
            f"输出格式：\n"
            f"📌要点：核心事实（5-8 条要点，优先保留原文中的数字、产品、公司、技术名）\n"
            f"🔬背景：技术/行业背景与来龙去脉\n"
            f"📊影响：对行业、市场、消费者、供应链或监管的潜在影响\n"
            f"🏷️关键实体：涉及的公司、产品、人物、技术\n"
            f"⚠️不确定性：正文未说明或证据不足的部分"
        ),
        system_prompt=(
            "你是资深科技新闻分析师。用中文输出，深入、准确、有洞察。"
            "技术名词、产品名、公司名、代码库保留英文原文。"
            "基于正文实际内容进行分析，不要凭空推测。"
            "如果信息不足，明确标注「暂无相关信息」或「正文未提及」。"
        ),
        max_tokens=config.ai_deep_thinking_max_tokens,
        temperature=0.2,
    )


def clean_article_content(html: str) -> str:
    """将文章 HTML 送入 LLM，提取纯净正文（去广告/导航/侧栏/弹窗/评论）。

    利用 DeepSeek V3.2 160K 上下文直接处理完整 HTML 结构，
    保留标题、段落、链接、图片、引用、列表等核心内容标签。
    返回仅含文章正文的 HTML 片段，不包含 <html>/<head>/<body>。
    """
    # 截断超长 HTML，为 prompt 和响应留出余量（160K tokens ≈ 480K chars）
    MAX_HTML_CHARS = 120000
    if len(html) > MAX_HTML_CHARS:
        html = html[:MAX_HTML_CHARS]

    system_prompt = (
        "你是一个新闻文章内容提取专家。"
        "从提供的 HTML 中仅提取文章正文主体。"
        "移除以下所有非正文元素："
        "导航栏、侧边栏、相关文章推荐/小组件、Cookie 横幅、"
        "广告、社交分享按钮、评论区、页脚链接、订阅表单、"
        "弹出窗口、以及任何页面框架/装饰性内容。"
        "移除空元素、损坏的图片（无有效 src 或 src 为空）、"
        "以及明显是追踪像素的图片。修复明显的 HTML 嵌套错误。"
        "仅返回清洗后的文章正文 HTML，不要包裹在 markdown 代码块中，"
        "不要添加解释说明。不要包含 <html>/<head>/<body> 标签。"
    )

    prompt = (
        "从以下 HTML 页面中提取文章正文内容。\n"
        "保留的 HTML 标签：标题 (h1-h6)、段落 (p)、带 href 的链接 (a)、"
        "带有效 src 和 alt 的图片 (img)、引用块 (blockquote)、"
        "有序/无序列表 (ul/ol/li)、行内格式 (strong/b, em/i, code)、"
        "代码块 (pre/code)、图表及其标题 (figure/figcaption)、"
        "表格 (table/thead/tbody/tr/td/th) 如果包含正文数据。\n"
        "如果文章包含作者和日期信息，保留它们。\n\n"
        f"{html}"
    )

    return chat(
        prompt,
        system_prompt=system_prompt,
        max_tokens=16384,       # 足够长的文章输出
        temperature=0.05,       # 低温度确保确定性提取
    )


# ══════════════════════════════════════════════════════════════
# AI 接管规则 — 替代 news_db.py 硬编码逻辑
# ══════════════════════════════════════════════════════════════


def extract_keywords_ai(title: str, text: str = "", source: str = "") -> list[str]:
    """AI 从标题+正文中提取技术关键词。text 为空时仅用标题。"""
    content = _prepare_content(text)
    user_prompt = f"标题：{title}\n来源：{source}\n"
    if content:
        user_prompt += f"正文：{content}\n\n"
    else:
        user_prompt += "\n"
    user_prompt += "提取 5-15 个技术关键词，返回 JSON 数组。关键词应覆盖：产品名、公司名、技术名、核心概念。"
    result = _ai_json(
        _with_deep_thinking(user_prompt),
        "你是科技新闻关键词提取引擎。只输出 JSON 数组，如 [\"GPU\",\"NVIDIA\",\"Blackwell\",\"AI训练\"]。"
        "技术名词、产品名、公司名保留英文原文。关键词按重要性排序。",
        max_tokens=512,
        temperature=0.05,
    )
    if isinstance(result, list) and len(result) > 0:
        return [str(k) for k in result if isinstance(k, str)]
    if isinstance(result, dict):
        kws = result.get("keywords") or result.get("关键词")
        if isinstance(kws, list) and len(kws) > 0:
            return [str(k) for k in kws if isinstance(k, str)]
        if len(result) > 0:
            return list(result.keys())
    return None


def classify_article_ai(title: str, text: str) -> dict | None:
    """AI 分类文章主题。HTML 提取纯文本后传入 160K 上下文。"""
    content = _prepare_content(text)
    result = _ai_json(
        _with_deep_thinking(
            f"标题：{title}\n正文：{content}\n\n"
            "请输出 JSON："
            '{"category":"细分领域（AI/LLM, PC/Hardware, Mobile, Gaming, Security, Semiconductors, Enterprise, Automotive, Space, Chip/Wafer, OpenSource, Regulation, Other）",'
            '"tags":["标签1","标签2","标签3","标签4","标签5"],'
            '"score":0.1-1.0（综合重要性评估，考虑技术突破性、行业影响、时效性）}'
        ),
        "你是科技新闻分类引擎。只输出 JSON，不输出其他内容。技术名词保留英文原文。",
        max_tokens=512,
        temperature=0.05,
    )
    if isinstance(result, dict) and "category" in result:
        return result
    return None


def score_priority_ai(title: str, text: str, source: str, days_old: int = 0) -> dict | None:
    """AI 评估文章优先级（百分制 0~100）。HTML 提取纯文本后传入 160K 上下文。"""
    content = _prepare_content(text)
    result = _ai_json(
        _with_deep_thinking(
            f"标题：{title}\n来源：{source}\n发布天数：{days_old}\n正文：{content}\n\n"
            f"请输出 JSON：{{"
            f'"score":0-100 的整数（百分制综合评分：来源权威性30% + 内容重要性40% + 时效性30%），'
            f'"label":"high/medium/low（高/中/低优先级。high:>=70, medium:35-69, low:<35）",'
            f'"reason":"30字以内理由，说明核心判断依据"}}'
        ),
        "你是科技新闻优先级评估引擎。考虑技术突破性、行业影响范围、信息稀缺性。只输出 JSON。",
        max_tokens=512,
        temperature=0.05,
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
        _with_deep_thinking(
            prompt + f"\n\n请输出 JSON：{{"
            f'"similar":true/false（是否报道同一事件），'
            f'"confidence":0.0-1.0（置信度），'
            f'"reason":"20字以内理由（可选）"}}'
        ),
        "你是新闻事件聚类专家。判断两篇文章是否指同一具体事件（同一产品发布、同一漏洞披露、同一收购等）。只输出 JSON。",
        max_tokens=512,
        temperature=0.05,
    )
    if isinstance(result, dict) and "similar" in result:
        return result
    return None


def match_article_to_events_ai(article_title: str, events: list[tuple[int, str]]) -> dict | None:
    """将一篇文章与多个候选事件比对，返回最佳匹配。

    Args:
        article_title: 文章标题
        events: [(event_id, event_title), ...] 候选事件列表（建议 ≤50）

    Returns:
        {'event_id': int|None, 'confidence': float, 'reason': str} 或 None（API 失败）
    """
    if not events:
        return {'event_id': None, 'confidence': 0.0, 'reason': '无候选事件'}

    events_text = "\n".join(f"[#{eid}] {etitle}" for eid, etitle in events)
    result = _ai_json(
        _with_deep_thinking(
            f"文章标题：{article_title}\n\n"
            f"候选事件列表：\n{events_text}\n\n"
            f"请判断这篇文章最可能属于哪个事件（如有匹配的话）。"
            f"输出 JSON：{{"
            f'"event_id":最匹配的事件ID或null（无匹配时）,'
            f'"confidence":0.0-1.0（置信度）,'
            f'"reason":"20字以内理由（可选）"}}'
        ),
        "你是新闻事件聚类专家。判断文章是否属于已有事件，只输出 JSON。",
        max_tokens=512,
        temperature=0.05,
    )
    if isinstance(result, dict) and "event_id" in result:
        return result
    return None


def suggest_event_relation_ai(title1: str, title2: str) -> dict | None:
    """AI 推断两事件之间的关系类型。返回 {relation, confidence, reason}。"""
    result = _ai_json(
        _with_deep_thinking(
            f"事件A：{title1}\n事件B：{title2}\n\n"
            f"请判定事件A与事件B的关系并输出 JSON：{{"
            f'"relation":"before/after/update/spawn/related/unrelated（A相对于B的关系：before=先于B发生，after=后于B发生，update=对B的更新/补充，spawn=导致/催生B，related=一般相关，unrelated=无关）",'
            f'"confidence":0.0-1.0（置信度），'
            f'"reason":"30字以内理由（必填，说明判断依据）"}}'
        ),
        "你是新闻事件关系分析专家。仔细分析因果关系和时间先后。只输出 JSON。",
        max_tokens=512,
        temperature=0.05,
    )
    if isinstance(result, dict) and "relation" in result:
        return result
    return None


def generate_event_summary_ai(titles_block: str) -> str:
    """AI 为一组事件文章生成综合摘要。"""
    return chat(
        _with_deep_thinking(
            f"以下是一组关于同一事件的文章标题。请生成一段中文综合摘要（150-250 字），概括核心内容和不同角度的报道侧重：\n\n{titles_block}"
        ),
        system_prompt=(
            "你是资深科技新闻编辑。用中文输出简洁全面的摘要，覆盖事件核心事实和不同报道角度。"
            "技术名词、产品名、公司名保留英文原文。"
            "只输出摘要，不要标题或解释。"
        ),
        max_tokens=768,
        temperature=0.1,
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
        summary_str = f" | 摘要: {summary[:300]}" if summary else ""
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
        _with_deep_thinking(
            f"以下是当前所有活跃科技事件的全景图：\n\n{context}\n\n"
            "请对所有事件按综合重要性排序（从最重要到最不重要），输出 JSON 数组：\n"
            '[{"id":事件ID,"rank":排名(从1开始),"reason":"15字以内排序理由"}]\n\n'
            "排序标准：技术突破性 > 行业影响范围 > 多源覆盖度 > 时效性。\n"
            "同一家公司/产品的连续报道应整体排高。已有关系的事件组应相邻排列。"
        ),
        "你是资深科技新闻编辑，负责全局事件优先级排序。只输出 JSON 数组，不输出其他内容。",
        max_tokens=8192,
        temperature=0.1,
    )
    if isinstance(result, list):
        return result
    return None


def build_chains_panoramic(context: str) -> list[dict] | None:
    """基于全景图识别应构筑逻辑链的事件分组。返回 [{events:[id...], title:"链标题", reason:"理由"}]。"""
    result = _ai_json(
        _with_deep_thinking(
            f"以下是当前所有活跃科技事件的全景图：\n\n{context}\n\n"
            "请识别应该构筑为逻辑链的事件分组。逻辑链是指一组有因果、时间先后、"
            "或同一产品/公司发展脉络关联的事件序列。\n\n"
            "输出 JSON 数组：\n"
            '[{"events":[事件ID列表],"title":"20字以内链标题","reason":"15字以内分组理由"}]\n\n'
            "规则：\n"
            "1. 每组至少 2 个事件\n"
            "2. 同一事件可以出现在多个链中\n"
            "3. 关注因果链（A导致B导致C）、时间线（同一产品迭代）、竞争对比\n"
            "4. 仅标题相似但无实质关联的事件不要强行分组"
        ),
        "你是资深科技新闻编辑，擅长识别事件之间的深层关联。只输出 JSON 数组，不输出其他内容。",
        max_tokens=8192,
        temperature=0.1,
    )
    if isinstance(result, list):
        return result
    return None
