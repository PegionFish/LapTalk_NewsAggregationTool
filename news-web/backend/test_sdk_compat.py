"""测试 OpenAI SDK extra_body 兼容性"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from openai import OpenAI
from config import config

client = OpenAI(base_url=config.openai_base_url, api_key=config.openai_api_key, timeout=30.0)

tests = [
    ("no extra", {}),
    ("enable_thinking=True", {"enable_thinking": True}),
    ("enable_thinking + budget", {"enable_thinking": True, "thinking_budget": 1024}),
]

for label, extra in tests:
    try:
        r = client.chat.completions.create(
            model=config.openai_model,
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=16,
            temperature=0.1,
            **({"extra_body": extra} if extra else {}),
        )
        print(f"[OK]   {label}: {r.choices[0].message.content}")
    except TypeError as e:
        print(f"[FAIL] {label}: {e}")
    except Exception as e:
        print(f"[ERR]  {label}: {type(e).__name__}: {e}")
