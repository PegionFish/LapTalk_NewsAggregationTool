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


def analyze_article(title: str, text: str) -> str:
    """对单篇科技新闻文章生成中文分析摘要。

    返回结构化的分析文本，包含：
    • 文章要点（2-3 句）
    • 技术背景（如有）
    • 行业影响（如有）
    """
    # 截取前 4000 字符，平衡上下文和成本
    snippet = text[:4000]
    return chat(
        f"请用中文分析以下科技新闻文章，输出简洁的结构化摘要（200 字以内）：\n\n"
        f"【标题】{title}\n\n"
        f"【正文】{snippet}\n\n"
        f"输出格式：\n"
        f"📌 要点：\n"
        f"🔬 背景：\n"
        f"📊 影响：\n",
        system_prompt=(
            "你是资深科技新闻分析师。用中文输出，简洁准确。"
            "保留技术名词、产品名、公司名的英文原文。"
            "如果文章信息不足以支撑某部分，标注「暂无」即可。"
        ),
    )
