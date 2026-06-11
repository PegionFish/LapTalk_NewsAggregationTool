"""
文本提取和语言检测 — 供 fetch_content 和 API 层共用
"""
import re
import html as html_mod

# DeepSeek V3.2 160K 上下文下，正文提取默认保留更完整内容；极端页面仍保留上限防止异常请求。
FULL_TEXT_MAX_LENGTH = 120000


def extract_text_from_html(html: str, max_length: int = FULL_TEXT_MAX_LENGTH) -> str:
    """从 HTML 中提取纯文本 — 去除脚本、样式、导航等噪音块。"""
    if not html:
        return ""
    # 移除 script / style / head / nav / footer / noscript 块
    for tag in ('script', 'style', 'head', 'nav', 'footer', 'noscript', 'header', 'aside', 'form'):
        html = re.sub(rf'<{tag}[\s\S]*?</{tag}>', '', html, flags=re.IGNORECASE)
    # 移除剩余 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', html)
    # 解码 HTML 实体
    text = html_mod.unescape(text)
    # 合并连续空白
    text = re.sub(r'[ \t\r]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    return text[:max_length]


def detect_language(text: str) -> str:
    """基于 CJK 字符占比的启发式语言检测。
    返回 'zh'（中文为主）或 'en'（英文为主）。"""
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    total = cjk + latin
    if total == 0:
        return 'en'
    return 'zh' if cjk / total > 0.15 else 'en'
