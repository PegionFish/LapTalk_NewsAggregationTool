"""
翻译客户端 — 独立于主 AI 分析的翻译 API 封装。
默认指向硅基流动 DeepSeek V3.2（成本约 ¥1/百万 token）。

支持两种模式：
- translate_html(html) — 原始 HTML 直传 LLM，保留全部标签结构
- translate_text(text)  — 纯文本翻译（兼容旧调用）
"""
from openai import OpenAI
from config import config


def get_client() -> OpenAI:
    """获取翻译专用 OpenAI 兼容客户端。"""
    return OpenAI(
        base_url=config.translation_base_url,
        api_key=config.translation_api_key or 'sk-placeholder',
        timeout=120.0,  # 翻译需要更长时间
    )


def translate_html(html: str) -> str:
    """将英文科技新闻 HTML 页面翻译为中文。

    直接将原始 HTML 传给 DeepSeek V3.2, LLM 自行区分 HTML 标签和实际文本。
    保留所有标签、属性、结构不变，仅翻译标签之间的可见文本内容。

    - 技术名词、产品名、公司名保留英文原文
    - 人名使用中文通用译名
    - temperature=0.05 确保翻译一致
    - DeepSeek V3.2 160K 上下文充裕，直接传入完整清洗后的 HTML
    """
    if not config.translation_api_key:
        return ""
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=config.translation_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一名资深科技新闻 HTML 翻译引擎。你的任务是：\n"
                        "1. 将输入 HTML 中所有可见的英文文本翻译为自然流畅的中文\n"
                        "2. 绝对不要修改任何 HTML 标签、属性、class、id、style、script 内容\n"
                        "3. 保留技术名词、产品名、公司名的英文原文（如 GPU、API、NVIDIA、TSMC）\n"
                        "4. 人名使用中文通用译名\n"
                        "5. 保留原始 HTML 的缩进和换行结构\n"
                        "6. 只输出翻译后的完整 HTML，不要添加任何解释或 markdown 包裹\n\n"
                        "示例：\n"
                        "输入: <p>Apple released the M4 chip today.</p>\n"
                        "输出: <p>Apple 今日发布了 M4 芯片。</p>\n\n"
                        "输入: <h1>Breaking News</h1><span class=\"date\">June 10, 2026</span>\n"
                        "输出: <h1>突发新闻</h1><span class=\"date\">2026年6月10日</span>"
                    ),
                },
                {"role": "user", "content": html},
            ],
            temperature=0.05,
            max_tokens=65536,
            top_p=0.95,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(f"Translation API error: {e}")


def translate_to_chinese(text: str) -> str:
    """纯文本翻译 — 单篇正文一次请求，充分利用 DeepSeek V3.2 160K 上下文。"""
    if not config.translation_api_key:
        return ""
    if not text or len(text.strip()) < 10:
        return ""

    return _translate_chunk(text)


def _translate_chunk(text: str) -> str:
    """翻译单个文本块。"""
    client = get_client()
    resp = client.chat.completions.create(
        model=config.translation_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一名资深科技新闻翻译。将以下英文科技新闻译成自然流畅的中文。"
                    "保留技术名词、产品名、公司名的英文原文（如 GPU、API、NVIDIA、TSMC）。"
                    "人名使用中文通用译名。只输出译文，不要解释。"
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.05,
        max_tokens=65536,
        top_p=0.95,
    )
    return resp.choices[0].message.content or ""
