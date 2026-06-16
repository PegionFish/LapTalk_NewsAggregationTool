"""
翻译客户端 — 独立于主 AI 分析的翻译 API 封装。
默认指向硅基流动 DeepSeek V3.2（成本约 ¥1/百万 token）。

翻译策略：
- translate_html(html) — 从 HTML 提取正文后翻译为纯文本
- translate_to_chinese(text) — 纯文本翻译（兼容旧调用）

正文提取后 token 数大幅下降（1.7MB HTML → ~50-100KB 文本），
超长文本自动按 4000 字分段。
"""
from openai import OpenAI
from config import config
from utils.text import extract_text_from_html

# 纯文本分段上限（字符数）
_TEXT_CHUNK_SIZE = 4000


def get_client() -> OpenAI:
    """获取翻译专用 OpenAI 兼容客户端。"""
    return OpenAI(
        base_url=config.translation_base_url,
        api_key=config.translation_api_key or 'sk-placeholder',
        timeout=300.0,
    )


def _call_translate(client: OpenAI, content: str, system_prompt: str) -> str:
    """单次 API 调用。"""
    resp = client.chat.completions.create(
        model=config.translation_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        temperature=0.05,
        max_tokens=65536,
        top_p=0.95,
    )
    return resp.choices[0].message.content or ""


_TRANSLATE_SYSTEM_PROMPT = (
    "你是一名资深科技新闻翻译。将以下英文科技新闻译成自然流畅的中文。"
    "保留技术名词、产品名、公司名的英文原文（如 GPU、API、NVIDIA、TSMC）。"
    "人名使用中文通用译名。只输出译文，不要解释。"
)


def translate_html(html: str) -> str:
    """从 HTML 提取正文后翻译为中文。

    流程：HTML → extract_text_from_html → 分段翻译 → 拼接返回纯文本。
    不再保留 HTML 标签结构（前端通过 iframe 显示原始 HTML，翻译仅作阅读参考）。
    """
    if not config.translation_api_key:
        return ""
    if not html or len(html.strip()) < 100:
        return ""

    text = extract_text_from_html(html)
    if not text or len(text.strip()) < 50:
        return ""

    return translate_to_chinese(text)


def translate_to_chinese(text: str) -> str:
    """纯文本翻译 — 超长文本自动分段，每段 ≤4000 字。"""
    if not config.translation_api_key:
        return ""
    if not text or len(text.strip()) < 10:
        return ""

    client = get_client()

    if len(text) <= _TEXT_CHUNK_SIZE:
        return _call_translate(client, text, _TRANSLATE_SYSTEM_PROMPT)

    chunks = [text[i:i + _TEXT_CHUNK_SIZE] for i in range(0, len(text), _TEXT_CHUNK_SIZE)]
    parts: list[str] = []
    for chunk in chunks:
        parts.append(_call_translate(client, chunk, _TRANSLATE_SYSTEM_PROMPT))
    return '\n'.join(parts)
