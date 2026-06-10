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
        timeout=30.0,  # 30 秒超时，防止请求挂起
    )


def chat(prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
    """Simple chat completion. Returns the response text."""
    client = get_client()
    resp = client.chat.completions.create(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def summarize_events(articles_text: str) -> str:
    """Ask AI to generate a neutral event summary from a set of article titles."""
    return chat(
        f"Below are news article titles about the same topic. "
        f"Write a concise neutral event title (max 15 words) that covers all of them:\n\n{articles_text}",
        system_prompt="You are a news analysis assistant. Output only the title, no explanation."
    )


def build_chain_title(events_text: str) -> str:
    """为共享关键词的一组事件生成逻辑链标题。输入仅事件标题列表，极短上下文。"""
    client = get_client()
    resp = client.chat.completions.create(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": "你是科技新闻编辑。只输出主题名称，不要任何解释。"},
            {"role": "user", "content": f"以下是一组相关科技事件，请生成一个概括性主题名称（15 字以内，中文）：\n\n{events_text}"},
        ],
        temperature=0.5,
        max_tokens=50,
    )
    return resp.choices[0].message.content or ""


def analyze_article(title: str, text: str) -> str:
    """对单篇科技新闻文章生成中文分析摘要。"""
    snippet = text[:2000]
    return chat(
        f"请用中文分析以下科技新闻，输出结构化摘要（150 字以内）：\n\n"
        f"标题：{title}\n"
        f"正文：{snippet}\n\n"
        f"输出格式：\n"
        f"📌要点：\n"
        f"🔬背景：\n"
        f"📊影响：\n",
        system_prompt=(
            "你是科技新闻分析师。用中文输出，简洁准确。"
            "技术名词、产品名、公司名保留英文原文。"
            "信息不足标注「暂无」。"
        ),
    )


# ══════════════════════════════════════════════════════════════
# AI 接管规则 — 替代 news_db.py 硬编码逻辑
# ══════════════════════════════════════════════════════════════

def _ai_json(prompt: str, system_prompt: str, max_tokens: int = 500) -> dict | list | None:
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
    """AI 从标题+正文中提取技术关键词。返回关键词列表，失败返回 None。"""
    snippet = text[:1800]
    result = _ai_json(
        f"标题：{title}\n来源：{source}\n正文：{snippet}\n\n提取 3-8 个技术关键词，返回 JSON 数组。",
        "你是科技新闻关键词提取引擎。只输出 JSON 数组，如 [\"GPU\",\"NVIDIA\",\"Blackwell\"]。技术名词、产品名、公司名保留英文原文。",
        200,
    )
    if isinstance(result, list) and len(result) > 0:
        return [str(k) for k in result if isinstance(k, str)]
    return None


def classify_article_ai(title: str, text: str) -> dict | None:
    """AI 分类文章主题。返回 {category, tags, score}，失败返回 None。"""
    snippet = text[:1500]
    result = _ai_json(
        f"标题：{title}\n正文：{snippet}\n\n请输出 JSON："
        f'{{"category":"细分领域（如 AI/LLM, PC/Hardware, Mobile, Gaming, Security, Semiconductors, Enterprise, Automotive, Space, Other）",'
        f'"tags":["标签1","标签2","标签3"],'
        f'"score":0.1-1.0（重要程度）}}',
        "你是科技新闻分类引擎。只输出 JSON。技术名词保留英文原文。",
        250,
    )
    if isinstance(result, dict) and "category" in result:
        return result
    return None


def score_priority_ai(title: str, text: str, source: str, days_old: int = 0) -> dict | None:
    """AI 评估文章优先级。返回 {score, label, reason}。"""
    snippet = text[:1500]
    result = _ai_json(
        f"标题：{title}\n来源：{source}\n发布天数：{days_old}\n正文：{snippet}\n\n"
        f"请输出 JSON：{{"
        f'"score":0.0-1.0（综合评分，考虑来源权威、内容重要性、时效性），'
        f'"label":"high/medium/low（高/中/低优先级）",'
        f'"reason":"20字以内理由"}}',
        "你是科技新闻优先级评估引擎。只输出 JSON。",
        200,
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
        f'"confidence":0.0-1.0（置信度）}}',
        "你是新闻事件聚类专家。只输出 JSON。",
        150,
    )
    if isinstance(result, dict) and "similar" in result:
        return result
    return None


def suggest_event_relation_ai(title1: str, title2: str) -> dict | None:
    """AI 推断两事件之间的关系类型。返回 {relation, confidence, reason}。"""
    result = _ai_json(
        f"事件A：{title1}\n事件B：{title2}\n\n"
        f"请判定关系并输出 JSON：{{"
        f'"relation":"before/after/update/spawn/related/unrelated（A相对于B的关系）",'
        f'"confidence":0.0-1.0,'
        f'"reason":"30字以内理由"}}',
        "你是新闻事件关系分析专家。只输出 JSON。",
        200,
    )
    if isinstance(result, dict) and "relation" in result:
        return result
    return None


def generate_event_summary_ai(titles_block: str) -> str:
    """AI 为一组事件文章生成综合摘要。"""
    return chat(
        f"以下是一组关于同一事件的文章标题。请生成一段中文综合摘要（100 字以内），概括核心内容：\n\n{titles_block}",
        system_prompt=(
            "你是科技新闻编辑。用中文输出简洁摘要。"
            "技术名词、产品名、公司名保留英文原文。"
            "只输出摘要，不要标题或解释。"
        ),
    )
