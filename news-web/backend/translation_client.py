"""
翻译客户端 — 独立于主 AI 分析的翻译 API 封装。
默认指向硅基流动 DeepSeek V3.2（成本约 ¥1/百万 token）。
"""
from openai import OpenAI
from config import config


def get_client() -> OpenAI:
    """获取翻译专用 OpenAI 兼容客户端。"""
    return OpenAI(
        base_url=config.translation_base_url,
        api_key=config.translation_api_key or 'sk-placeholder',
    )


def translate_to_chinese(text: str) -> str:
    """将英文科技新闻翻译为自然流畅的中文。

    - 保留技术名词、产品名、公司名原文（如 GPU、API、NVIDIA、TSMC）
    - 人名使用中文通用译名
    - temperature=0.05 确保翻译稳定一致
    - 最长 30000 字符（DeepSeek V3.2 128K 上下文充裕）
    """
    if not config.translation_api_key:
        return ""
    # 截断过长的文本
    text = text[:30000]
    try:
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
            max_tokens=8192,
            top_p=0.95,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(f"Translation API error: {e}")
