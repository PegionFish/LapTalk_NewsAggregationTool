"""直接调试 keyword API 原始返回"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from utils.text import extract_text_from_html
from ai_client import _with_deep_thinking, _strip_json
from openai import OpenAI
from config import config

fp = os.path.join('data', 'content', '84.html')
raw = open(fp, 'r', encoding='utf-8').read()
clean = extract_text_from_html(raw)

prompt = (
    f"标题：Final Fantasy 7 Revelation Announced\n来源：PCGamer\n正文：{clean}\n\n"
    f"提取 5-15 个技术关键词，返回 JSON 数组。关键词应覆盖：产品名、公司名、技术名、核心概念。"
)
system = (
    "你是科技新闻关键词提取引擎。只输出 JSON 数组，"
    "如 [\"GPU\",\"NVIDIA\",\"Blackwell\",\"AI训练\"]。"
    "技术名词、产品名、公司名保留英文原文。关键词按重要性排序。"
)

client = OpenAI(
    base_url=config.openai_base_url,
    api_key=config.openai_api_key or 'sk-placeholder',
    timeout=300.0,
)
resp = client.chat.completions.create(
    model=config.openai_model,
    messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": _with_deep_thinking(prompt)},
    ],
    temperature=0.05,
    max_tokens=512,
    response_format={"type": "json_object"},
)
raw_text = (resp.choices[0].message.content or "").strip()
print(f"RAW response ({len(raw_text)} chars):")
print(raw_text[:800])
print("---")
parsed = json.loads(_strip_json(raw_text))
print(f"PARSED type: {type(parsed)}")
print(f"PARSED: {parsed}")
