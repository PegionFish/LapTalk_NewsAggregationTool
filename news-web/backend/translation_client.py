"""
翻译客户端 — 独立于主 AI 分析的翻译 API 封装。

翻译策略：
- translate_html(html) — 从 HTML 提取正文后翻译为纯文本（兼容旧调用）
- translate_html_preserve_structure(html) — HTML 直传 LLM，保留标签结构翻译
- translate_to_chinese(text) — 纯文本翻译（兼容旧调用）

利用大上下文窗口，绝大多数文章一次调用完成翻译。
"""
import time
from openai import OpenAI
from config import config
from utils.text import extract_text_from_html

# 纯文本分段上限（字符数）— 绝大多数文章不触发分段
_TEXT_CHUNK_SIZE = 1_000_000


def get_client() -> OpenAI:
    """获取翻译专用 OpenAI 兼容客户端。"""
    return OpenAI(
        base_url=config.translation_base_url,
        api_key=config.translation_api_key or 'sk-placeholder',
        timeout=1800.0,
    )


def _call_translate(client: OpenAI, content: str, system_prompt: str, max_tokens: int = 131072) -> str:
    """单次 API 调用。遇到 429 等 60s 重试，最多 3 次。"""
    from openai import RateLimitError

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=config.translation_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                temperature=0.05,
                max_tokens=max_tokens,
                top_p=0.95,
            )
            return resp.choices[0].message.content or ""
        except RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                raise


_TRANSLATE_SYSTEM_PROMPT = (
    "你是一名资深科技新闻翻译。将以下英文科技新闻译成自然流畅的中文。"
    "保留技术名词、产品名、公司名的英文原文（如 GPU、API、NVIDIA、TSMC）。"
    "人名使用中文通用译名。只输出译文，不要解释。"
)

_TRANSLATE_HTML_SYSTEM_PROMPT = (
    "你是一名资深科技新闻翻译。将以下 HTML 中的英文科技新闻译成自然流畅的中文。"
    "重要：保留所有 HTML 标签结构不变，只翻译标签之间的文本内容。"
    "保留技术名词、产品名、公司名的英文原文（如 GPU、API、NVIDIA、TSMC）。"
    "人名使用中文通用译名。只输出翻译后的 HTML，不要解释。"
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


def translate_html_preserve_structure(html: str) -> str:
    """HTML 直传 LLM 翻译，保留标签结构。

    利用大上下文窗口，将完整 HTML 直接发送给翻译模型，要求保留所有标签
    结构不变，仅翻译标签间的文本内容。输出为保留原始标签结构的中文 HTML。

    超长 HTML 自动分段处理。
    """
    if not config.translation_api_key:
        return ""
    if not html or len(html.strip()) < 100:
        return ""

    client = get_client()

    if len(html) <= _TEXT_CHUNK_SIZE:
        return _call_translate(client, html, _TRANSLATE_HTML_SYSTEM_PROMPT)

    # 极端长 HTML 分段翻译
    chunks = [html[i:i + _TEXT_CHUNK_SIZE] for i in range(0, len(html), _TEXT_CHUNK_SIZE)]
    parts: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_prompt = f"[第 {i + 1}/{len(chunks)} 部分]\n{chunk}"
        parts.append(_call_translate(client, chunk_prompt, _TRANSLATE_HTML_SYSTEM_PROMPT))
    return '\n'.join(parts)


def translate_to_chinese(text: str) -> str:
    """纯文本翻译 — 超长文本自动分段。"""
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
