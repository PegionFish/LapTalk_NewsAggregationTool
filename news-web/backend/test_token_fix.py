"""测试 HTML 提取纯文本后 AI 分析是否正常，验证 token 超限修复。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from utils.text import extract_text_from_html
from ai_client import analyze_article, extract_keywords_ai, classify_article_ai, score_priority_ai

TEST_FILES = [
    ("84.html",  "最大文件 1.7MB"),
    ("215.html", "第二大 1.7MB"),
    ("83.html",  "第三大 1.7MB"),
]

content_dir = os.path.join(os.path.dirname(__file__), "data", "content")

for fname, desc in TEST_FILES:
    fpath = os.path.join(content_dir, fname)
    if not os.path.isfile(fpath):
        print(f"[SKIP] {fname} 不存在")
        continue

    raw = open(fpath, "r", encoding="utf-8").read()
    raw_kb = len(raw) / 1024

    clean = extract_text_from_html(raw)
    clean_kb = len(clean) / 1024

    print(f"\n{'='*60}")
    print(f"[FILE] {fname} ({desc})")
    print(f"  HTML: {raw_kb:.0f}KB -> text: {clean_kb:.0f}KB (reduced {100*(1-clean_kb/raw_kb):.0f}%)")

    title = f"Test Article {fname}"

    # Test 1: analyze
    print(f"  [TEST] analyze_article ...", flush=True)
    try:
        result = analyze_article(title, clean)
        print(f"  [OK] analyze: {len(result)} chars")
    except Exception as e:
        print(f"  [FAIL] analyze: {e}")

    # Test 2: keywords
    print(f"  [TEST] extract_keywords_ai ...", flush=True)
    try:
        kws = extract_keywords_ai(title, clean, "TestSource")
        print(f"  [OK] keywords: {kws[:5] if kws else 'empty'}")
    except Exception as e:
        print(f"  [FAIL] keywords: {e}")

    # Test 3: classify
    print(f"  [TEST] classify_article_ai ...", flush=True)
    try:
        cls = classify_article_ai(title, clean)
        print(f"  [OK] classify: {cls.get('category') if cls else 'empty'}")
    except Exception as e:
        print(f"  [FAIL] classify: {e}")

    # Test 4: score
    print(f"  [TEST] score_priority_ai ...", flush=True)
    try:
        score = score_priority_ai(title, clean, "TestSource", 0)
        print(f"  [OK] score: {score.get('score') if score else 'empty'}")
    except Exception as e:
        print(f"  [FAIL] score: {e}")

print(f"\n{'='*60}")
print("[DONE] All tests completed")
