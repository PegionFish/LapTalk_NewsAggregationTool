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
    """对单篇科技新闻文章生成中文分析摘要。

    返回结构化的分析文本，包含：
    • 文章要点（2-3 句）
    • 技术背景（如有）
    • 行业影响（如有）
    """
    # 截取前 2000 字符，控制上下文长度
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
