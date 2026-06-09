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
