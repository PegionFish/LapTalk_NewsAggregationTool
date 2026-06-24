"""
OpenAI 兼容 API 客户端封装。
支持大上下文窗口、深度思考与结构化 JSON 输出。
超长 HTML 自动在块级元素边界拆分后分别处理。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import OpenAI, RateLimitError

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
    global _active_client
    client = OpenAI(
        base_url=config.openai_base_url,
        api_key=config.openai_api_key or 'sk-placeholder',
        timeout=1800.0,  # 30 分钟 — 适配慢速模型 token 生成
    )
    _active_client = client
    return client


_active_client: OpenAI | None = None


def close_active_client() -> None:
    """关闭当前活跃的 AI 客户端底层 HTTP 连接，立即中断正在进行的 API 调用。

    取消批量任务时调用此函数，可让阻塞在 chat() 中的线程立即抛出
    APIConnectionError，从而在秒级内响应取消请求。
    """
    global _active_client
    if _active_client is not None:
        try:
            _active_client.close()
        except Exception:
            pass
        finally:
            _active_client = None


def _thinking_enabled(enable_thinking: bool | None) -> bool:
    """判断本次请求是否启用深度思考。"""
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
    model: str | None = None,  # 覆写模型，None 使用全局 openai_model
) -> dict[str, Any]:
    """组装 Chat Completions 请求参数。"""
    options: dict[str, Any] = {
        "model": model or config.openai_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    enabled = _thinking_enabled(enable_thinking)
    budget = _thinking_budget(thinking_budget)
    extra_body: dict[str, Any] = {}
    # 始终显式设置 enable_thinking，避免模型默认行为与预期不符
    extra_body["enable_thinking"] = enabled
    if enabled and budget is not None:
        extra_body["thinking_budget"] = budget
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
    stream_log: bool = False,
    on_stream_chunk: "Callable[[str, int, int], None] | None" = None,
    model: str | None = None,
    client: OpenAI | None = None,  # 传入则使用指定客户端（清洗用 OpenRouter 等）
) -> str:
    """发送单轮聊天请求并返回助手文本。遇到 429 自动等待 60s 重试。"""
    from typing import Callable

    if client is None:
        client = get_client()
    options = _request_options(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        enable_thinking=enable_thinking,
        thinking_budget=thinking_budget,
        response_format=response_format,
        model=model,
    )

    # ── 429 重试：最多 3 次，每次等 60s ──
    for attempt in range(3):
        try:
            if stream_log and on_stream_chunk:
                options["stream"] = True
                accumulated = ""
                thinking_chars = 0
                last_report = 0
                stream = client.chat.completions.create(**options)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, 'reasoning_content', None) or ''
                    if reasoning:
                        thinking_chars += len(reasoning)
                    if delta.content:
                        accumulated += delta.content
                        n = len(accumulated)
                        if n - last_report >= 2000 or (n >= 500 and last_report == 0):
                            on_stream_chunk(accumulated, n, thinking_chars)
                            last_report = n
                if accumulated and last_report < len(accumulated):
                    on_stream_chunk(accumulated, len(accumulated), thinking_chars)
                return accumulated
            else:
                resp = client.chat.completions.create(**options)
                return resp.choices[0].message.content or ""
        except RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                raise


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
    model: str | None = None,
) -> dict | list | None:
    """调用 AI 并解析 JSON 返回；失败时返回 None。遇到 429 等 60s 重试。"""
    if response_format is None and config.ai_json_response_format:
        response_format = {"type": "json_object"}

    for attempt in range(3):
        try:
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
                    model=model,
                )
            )
            raw = (resp.choices[0].message.content or "").strip()
            return json.loads(_strip_json(raw))
        except RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                return None
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
    """对单篇科技新闻文章生成中文分析摘要。HTML 提取纯文本后利用大上下文窗口做全量分析。"""
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


# ══════════════════════════════════════════════════════════════
# HTML 拆分 — 极端大文件在块级元素边界拆分后分别清洗
# ══════════════════════════════════════════════════════════════

_HTML_CHARS_PER_TOKEN = 2.0        # 英文 HTML 约 2 字符/token（保守估计）
_HTML_MAX_CHUNK_CHARS = 1_800_000  # 每块约 900K tokens，为系统提示+输出预留 100K


def _split_html_at_blocks(html: str, max_chars: int = _HTML_MAX_CHUNK_CHARS) -> list[str]:
    """在块级元素边界安全拆分 HTML，确保每块不超过 max_chars 字符。

    拆分策略：
    1. 在所有块级起始标签（div/section/article/p/h1-h6 等）处寻找候选切割点
    2. 每块尽可能接近 max_chars，但总是在块级元素起始处切割，不割裂标签
    3. 单一块级元素超过 max_chars 时回退到强制字符切割（极少见，如巨型 <pre>）
    """
    if len(html) <= max_chars:
        return [html]

    # 块级元素起始标签模式 — 在这些标签之前切割
    _block_start_pat = re.compile(
        r'<(div|section|article|main|aside|header|footer|nav|'
        r'table|tbody|thead|tfoot|figure|figcaption|'
        r'blockquote|p|h[1-6]|ul|ol|dl|form|'
        r'fieldset|details|summary|pre|hr|br)[\s>]',
        re.IGNORECASE,
    )

    # 收集所有切割候选点（文档开头 + 每个块级起始标签位置）
    cut_points = [0]
    for m in _block_start_pat.finditer(html):
        cut_points.append(m.start())
    cut_points = sorted(set(cut_points))

    chunks: list[str] = []
    chunk_start = 0

    for i in range(1, len(cut_points)):
        cp = cut_points[i]
        if cp - chunk_start > max_chars:
            # 在前一个块级元素起始处切割
            prev_cp = cut_points[i - 1]
            if prev_cp > chunk_start:
                chunks.append(html[chunk_start:prev_cp])
                chunk_start = prev_cp
            else:
                # 单一块超过限制（如巨型 <pre>），强制字符切割
                chunks.append(html[chunk_start:chunk_start + max_chars])
                chunk_start += max_chars

    # 处理剩余尾部
    remaining = html[chunk_start:]
    if remaining:
        if len(remaining) > max_chars:
            for j in range(0, len(remaining), max_chars):
                chunks.append(remaining[j:j + max_chars])
        else:
            chunks.append(remaining)

    return chunks


def clean_article_content(html: str, on_stream: "Callable[[str, int, int], None] | None" = None) -> str:
    """将文章 HTML 送入 LLM，提取纯净正文（去广告/导航/侧栏/弹窗/评论）。

    利用大上下文窗口做全量清洗。对于超大 HTML，自动在块级元素边界拆分为多块
    分别清洗后合并。

    返回仅含文章正文的 HTML 片段，不包含 <html>/<head>/<body>。
    传入 on_stream(text, content_chars, thinking_chars) 回调启用 SSE 流式。
    """
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

    # ── 超大文件拆分清洗 ──
    if len(html) > _HTML_MAX_CHUNK_CHARS:
        chunks = _split_html_at_blocks(html)
        if on_stream:
            on_stream(f"[拆分清洗] 总 {len(chunks)} 块，逐块处理中...", 0, 0)

        cleaned_parts: list[str] = []
        for idx, chunk in enumerate(chunks):
            chunk_prompt = (
                f"以下是 HTML 文档的第 {idx + 1}/{len(chunks)} 部分。"
                f"从中提取文章正文内容。\n"
                f"保留的 HTML 标签：标题 (h1-h6)、段落 (p)、带 href 的链接 (a)、"
                f"带有效 src 和 alt 的图片 (img)、引用块 (blockquote)、"
                f"有序/无序列表 (ul/ol/li)、行内格式 (strong/b, em/i, code)、"
                f"代码块 (pre/code)、图表及其标题 (figure/figcaption)、"
                f"表格 (table/thead/tbody/tr/td/th) 如果包含正文数据。\n"
                f"如果文章包含作者和日期信息，保留它们。\n\n"
                f"{chunk}"
            )
            try:
                result = chat(
                    chunk_prompt,
                    system_prompt=system_prompt,
                    max_tokens=65536,
                    temperature=0.05,
                    enable_thinking=True,
                    model=config.clean_model,
                )
                if result and len(result.strip()) > 50:
                    cleaned_parts.append(result.strip())
                if on_stream:
                    on_stream(
                        f"[拆分清洗] {idx + 1}/{len(chunks)} 完成",
                        idx + 1, len(chunks),
                    )
            except Exception as e:
                if on_stream:
                    on_stream(
                        f"[拆分清洗] 第 {idx + 1} 块异常: {e}",
                        idx + 1, len(chunks),
                    )
                # 失败时保留原始 HTML 片段，避免整篇丢失
                cleaned_parts.append(chunk)

        return "\n".join(cleaned_parts)

    # ── 常规文件直接清洗 ──
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

    # 清洗是结构性提取任务，深度思考对质量提升有限但增加推理 token。
    return chat(
        prompt,
        system_prompt=system_prompt,
        max_tokens=65536,
        temperature=0.05,
        enable_thinking=True,
        stream_log=on_stream is not None,
        on_stream_chunk=on_stream,
        model=config.clean_model,
    )


# ══════════════════════════════════════════════════════════════
# AI 接管规则 — 替代 news_db.py 硬编码逻辑
# ══════════════════════════════════════════════════════════════


def extract_keywords_ai(title: str, text: str = "", source: str = "", model: str | None = None) -> list[str]:
    """AI 从标题+正文中提取技术关键词。text 为空时仅用标题。model=None 使用全局 openai_model。"""
    content = _prepare_content(text)
    user_prompt = f"标题：{title}\n来源：{source}\n"
    if content:
        user_prompt += f"正文：{content}\n\n"
    else:
        user_prompt += "\n"
    user_prompt += "提取 5-15 个技术关键词，返回 JSON 数组。关键词应覆盖：产品名、公司名、技术名、核心概念。"
    result = _ai_json(
        user_prompt,
        "你是科技新闻关键词提取引擎。基于标题+正文提取技术关键词。"
        "只输出 JSON 数组，如 [\"GPU\",\"NVIDIA\",\"Blackwell\",\"AI训练\"]。"
        "技术名词、产品名、公司名保留英文原文。关键词按重要性排序。",
        max_tokens=4096,          # Qwen 会自然停，不用抠 token
        temperature=0.05,
        enable_thinking=False,
        model=model,
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


def classify_article_ai(title: str, text: str, model: str | None = None) -> dict | None:
    """AI 分类文章主题。利用大上下文窗口做全量分类。"""
    content = _prepare_content(text)
    result = _ai_json(
        f"标题：{title}\n正文：{content}\n\n"
        "请输出 JSON："
        '{"category":"细分领域（AI/LLM, PC/Hardware, Mobile, Gaming, Security, Semiconductors, Enterprise, Automotive, Space, Chip/Wafer, OpenSource, Regulation, Other）",'
        '"tags":["标签1","标签2","标签3","标签4","标签5"],'
        '"score":0.1-1.0（综合重要性评估）}',
        "你是科技新闻分类引擎。只输出 JSON。技术名词保留英文原文。",
        max_tokens=4096,
        temperature=0.05,
        enable_thinking=False,
        model=model,
    )
    if isinstance(result, dict) and "category" in result:
        return result
    return None


def score_priority_ai(title: str, text: str, source: str, days_old: int = 0, model: str | None = None) -> dict | None:
    """AI 评估文章优先级（百分制 0~100）。利用大上下文窗口做全量评估。"""
    content = _prepare_content(text)
    result = _ai_json(
        f"标题：{title}\n来源：{source}\n发布天数：{days_old}\n正文：{content}\n\n"
        f"请输出 JSON：{{"
        f'"score":0-100 的整数（百分制综合评分：来源权威性30% + 内容重要性40% + 时效性30%），'
        f'"label":"high/medium/low（high:>=70, medium:35-69, low:<35）",'
        f'"reason":"30字以内理由"}}',
        "你是科技新闻优先级评估引擎。考虑技术突破性、行业影响范围、信息稀缺性。只输出 JSON。",
        max_tokens=1024,
        temperature=0.05,
        enable_thinking=False,
    )
    if isinstance(result, dict) and "score" in result:
        return result
    return None


def extract_keywords_classify_score_ai(
    title: str, text: str = "", source: str = "", days_old: int = 0,
    model: str | None = None,
) -> dict | None:
    """一次 API 调用同时完成关键词提取、话题分类和优先级评分。

    利用大上下文窗口合并三个轻量任务，减少 API 调用次数。
    返回 {keywords, category, tags, score, label, reason} 或 None。
    """
    content = _prepare_content(text)
    result = _ai_json(
        f"标题：{title}\n来源：{source}\n发布天数：{days_old}\n正文：{content}\n\n"
        "请一次性完成以下三项任务，输出一个 JSON 对象：\n"
        "{\n"
        '  "keywords": ["技术关键词1","关键词2",...] (5-15个，按重要性排序，技术名词保留英文),\n'
        '  "category": "细分领域（AI/LLM, PC/Hardware, Mobile, Gaming, Security, Semiconductors, Enterprise, Automotive, Space, Chip/Wafer, OpenSource, Regulation, Other）",\n'
        '  "tags": ["标签1","标签2","标签3","标签4","标签5"],\n'
        '  "score": 0-100 的整数（来源权威性30% + 内容重要性40% + 时效性30%），\n'
        '  "label": "high/medium/low（high:>=70, medium:35-69, low:<35）",\n'
        '  "reason": "30字以内评分理由"\n'
        "}",
        "你是科技新闻分析引擎。一次完成关键词提取、话题分类和优先级评分。只输出 JSON。",
        max_tokens=4096,
        temperature=0.05,
        enable_thinking=False,
        model=model,
    )
    if isinstance(result, dict) and "keywords" in result:
        return result
    return None


def extract_keywords_batch(articles: list[dict], model: str | None = None) -> list[list[str]] | None:
    """批量提取多篇文章关键词，一次 API 调用处理多篇文章。

    Args:
        articles: [{"id": int, "title": str, "text": str, "source": str}, ...]
        model: 可选模型覆写

    Returns:
        [[kw1, kw2, ...], ...] 与输入顺序对应的关键词列表；失败返回 None
    """
    if not articles:
        return []

    # 组装批量 prompt
    items = []
    for a in articles:
        content = _prepare_content(a.get("text", ""))
        items.append(
            f"[ID:{a['id']}] 标题：{a.get('title', '')}\n"
            f"来源：{a.get('source', '')}\n"
            f"正文：{content[:3000]}\n"  # 批量模式下正文截取前 3000 字
        )

    prompt = (
        "请为以下每篇文章提取 5-15 个技术关键词。\n"
        "输出 JSON 数组的数组，按文章顺序排列：\n"
        '[[文章1的关键词], [文章2的关键词], ...]\n'
        "关键词应覆盖：产品名、公司名、技术名、核心概念。技术名词保留英文原文。\n\n"
        + "\n---\n".join(items)
    )

    result = _ai_json(
        prompt,
        "你是科技新闻关键词批量提取引擎。只输出 JSON 数组的数组，不输出其他内容。",
        max_tokens=8192,
        temperature=0.05,
        enable_thinking=False,
        model=model,
    )
    if isinstance(result, list) and len(result) == len(articles):
        return [[str(k) for k in kw_list if isinstance(k, str)] for kw_list in result]
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
# 全景图全局推理 — 利用大上下文窗口一次性传入全部事件数据
# ══════════════════════════════════════════════════════════════


def build_panoramic_context(conn) -> str:
    """从数据库组装完整事件全景图：每个事件含全部关联文章的标题、日期、评分、关键词及已有关系。

    利用大上下文窗口一次性传入全部数据，让 AI 有充足信息做高质量全局推理。
    """
    import json

    # 活跃事件（按文章数降序）
    events = conn.execute("""
        SELECT e.id, e.title, e.article_count, e.first_seen, e.last_seen, e.ai_summary
        FROM events e
        WHERE e.status = 'active' AND e.article_count >= 1
        ORDER BY e.article_count DESC
    """).fetchall()

    # 每个事件的关联文章列表（含标题、发布日期、优先级）
    event_articles: dict[int, list[dict]] = {}
    for evt_id, _, _, _, _, _ in events:
        rows = conn.execute("""
            SELECT a.title, a.published_date, a.priority_score, a.priority_label,
                   a.ai_keywords, a.keywords
            FROM news_articles a
            JOIN news_article_events ae ON ae.article_id = a.id
            WHERE ae.event_id = ?
            ORDER BY a.published_date DESC
        """, (evt_id,)).fetchall()
        articles = []
        for title, pub_date, score, label, ai_kw, kw in rows:
            articles.append({
                'title': title,
                'date': pub_date or '',
                'score': score or 0.0,
                'label': label or '',
            })
        event_articles[evt_id] = articles

    # 每个事件的关键词聚合
    event_kws: dict[int, set[str]] = {}
    for evt_id, _, _, _, _, _ in events:
        rows = conn.execute("""
            SELECT a.ai_keywords, a.keywords FROM news_articles a
            JOIN news_article_events ae ON ae.article_id = a.id
            WHERE ae.event_id = ?
        """, (evt_id,)).fetchall()
        kws: set[str] = set()
        for (ai_kw, kw) in rows:
            for src in (ai_kw, kw):
                try:
                    for k in json.loads(src or '[]'):
                        if len(k) > 1 and k.lower() not in ('news', 'rss_news', 'hotlist'):
                            kws.add(k)
                except (json.JSONDecodeError, TypeError):
                    pass
        event_kws[evt_id] = kws

    # 已有事件关系
    relations = conn.execute("""
        SELECT r.from_event_id, r.to_event_id, r.relation
        FROM event_relations r
    """).fetchall()

    # 组装结构化文本 — 全量数据，不截断
    lines: list[str] = []
    lines.append(f"=== 事件全景图（共 {len(events)} 个活跃事件）===\n")

    for evt_id, title, count, first_seen, last_seen, summary in events:
        kws = event_kws.get(evt_id, set())
        kw_str = ", ".join(sorted(kws)) if kws else "无"
        lines.append(f"[#{evt_id}] {title}")
        lines.append(f"  文章数: {count} | 首次出现: {first_seen} | 最后更新: {last_seen}")
        lines.append(f"  关键词: {kw_str}")
        if summary:
            lines.append(f"  摘要: {summary}")

        # 列出所有关联文章
        articles = event_articles.get(evt_id, [])
        if articles:
            lines.append(f"  关联文章 ({len(articles)} 篇):")
            for a in articles:
                score_str = f" [评分:{a['score']:.0f}/{a['label']}]" if a['score'] else ""
                date_str = f" ({a['date']})" if a['date'] else ""
                lines.append(f"    - {a['title']}{date_str}{score_str}")
        lines.append("")

    if relations:
        lines.append(f"=== 已有事件关系（共 {len(relations)} 条）===")
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
        max_tokens=262144,
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
        max_tokens=262144,
        temperature=0.1,
    )
    if isinstance(result, list):
        return result
    return None
