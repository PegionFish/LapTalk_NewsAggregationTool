# 文章内容内联化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文章 HTML 内联化为自包含静态文档（CSS 内联 + 本地图片引用 + 同源 CSS 共享去重），iframe 无 sandbox 展示。

**Architecture:** 新增 `content_processor.py` 处理 CSS 内联/去重和图片下载/URL 改写。修改 `/html` 端点调用新处理器。新增 `/shared-css` 和 `/images` 两个静态文件端点。前端移除 iframe sandbox。

**Tech Stack:** Python 3.14, FastAPI, BeautifulSoup4 (HTML 解析), hashlib, requests

## Global Constraints

- CSS 内联是纯文本（token 量小），图片走本地文件引用
- 同源 CSS 文件按 domain + MD5 去重，存 `content/shared/{domain}/{md5}.css`
- 图片存 `content/images/{article_id}_{img_hash}.{ext}`
- AI 管线吃 `text_content` 纯文本，不受内联化影响
- iframe 不加 sandbox（本地部署应用）
- 下载失败优雅降级（保留原始 URL）
- 已缓存内容直接用本地 HTML，未缓存先抓取再展示

---

### Task 1: content_processor.py — 内联化处理器

**Files:**
- Create: `news-web/backend/pipeline/content_processor.py`

**Interfaces:**
- Produces: `process_html_for_local_cache(html: str, url: str, article_id: int) -> str` — 主入口，CSS 内联 + 图片下载 + URL 改写 + 存入磁盘，返回处理后 HTML
- Produces: `_inline_stylesheets(html: str, url: str) -> str` — 下载 CSS 文件 → 按 domain+MD5 存 shared/ 目录 → 改写 href
- Produces: `_download_and_rewrite_images(html: str, article_id: int) -> str` — 下载图片 → 存 images/ 目录 → 改写 src/url()
- Produces: `_ensure_content_dirs() -> tuple[str, str, str]` — 确保 content/shared, content/images 目录存在

- [ ] **Step 1: 创建模块骨架和测试**

```bash
mkdir -p /srv/LapTalk_NewsAggregationTool/news-web/backend/pipeline
touch /srv/LapTalk_NewsAggregationTool/news-web/backend/pipeline/content_processor.py
```

- [ ] **Step 2: 实现 content_processor.py**

```python
#!/usr/bin/env python3
"""文章内容内联化处理器 — CSS 内联 + 图片下载 + URL 改写。

将原始 HTML 转换为自包含的静态文档：
- <link rel=stylesheet> → 下载 CSS → 按 domain+MD5 存 shared/ → <style>
- <img src> + CSS url() → 下载图片 → 存 images/ → 改写为本地 URL
- 下载失败保留原始 URL（优雅降级）
"""

import os
import re
import hashlib
import logging
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from config import config

logger = logging.getLogger(__name__)

# 图片下载超时
IMAGE_TIMEOUT = 15

# 图片文件扩展名映射（Content-Type → ext）
_MIME_TO_EXT = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/svg+xml': 'svg',
    'image/bmp': 'bmp',
    'image/ico': 'ico',
    'image/x-icon': 'ico',
}


def _ensure_content_dirs() -> tuple[str, str, str]:
    """确保内容目录存在，返回 (cache_dir, shared_dir, images_dir)。"""
    cache_dir = config.content_cache_path
    shared_dir = os.path.join(cache_dir, 'shared')
    images_dir = os.path.join(cache_dir, 'images')
    os.makedirs(shared_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    return cache_dir, shared_dir, images_dir


def _domain_from_url(url: str) -> str:
    """从 URL 提取域名（用于 shared CSS 的子目录）。"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.hostname or 'unknown'
        # 去掉端口号
        domain = domain.split(':')[0]
        # 去掉 www. 前缀以增加共享命中率
        if domain.startswith('www.'):
            domain = domain[4:]
        # 安全化：去掉非文件名字符
        domain = re.sub(r'[^a-zA-Z0-9._-]', '_', domain)
        return domain
    except Exception:
        return 'unknown'


def _inline_stylesheets(html: str, url: str) -> str:
    """下载 <link rel=stylesheet> 的 CSS 文件，按 domain+MD5 存 shared/ 目录，
    href 改写为 /api/news/shared-css/{domain}/{md5}.css。"""
    _, shared_dir, _ = _ensure_content_dirs()
    domain = _domain_from_url(url)
    soup = BeautifulSoup(html, 'html.parser')

    for link in soup.find_all('link', rel='stylesheet'):
        href = link.get('href', '')
        if not href:
            continue

        css_url = urljoin(url, href)

        # 下载 CSS 内容
        try:
            resp = requests.get(css_url, timeout=15,
                                headers={'User-Agent': config.user_agent})
            if resp.status_code != 200:
                logger.warning(f"CSS 下载失败 HTTP {resp.status_code}: {css_url}")
                continue
            css_content = resp.text
            if not css_content or len(css_content.strip()) < 10:
                continue
        except Exception as e:
            logger.warning(f"CSS 下载异常: {css_url} — {e}")
            continue

        # MD5 去重
        css_hash = hashlib.md5(css_content.encode('utf-8')).hexdigest()

        # 存 shared/{domain}/{md5}.css
        domain_dir = os.path.join(shared_dir, domain)
        os.makedirs(domain_dir, exist_ok=True)
        css_path = os.path.join(domain_dir, f'{css_hash}.css')

        if not os.path.exists(css_path):
            with open(css_path, 'w', encoding='utf-8') as f:
                f.write(css_content)
            logger.debug(f"CSS 已缓存: {domain}/{css_hash}.css")

        # 改写 <link> → <style>
        new_tag = soup.new_tag('style')
        new_tag.string = css_content
        link.replace_with(new_tag)

    # 处理 <link rel=preload/preconnect> 等非样式表标签：移除（本地不需要）
    for link in soup.find_all('link'):
        rel = (link.get('rel') or [])
        if isinstance(rel, str):
            rel = [rel]
        if 'stylesheet' not in rel:
            link.decompose()

    return str(soup)


def _download_and_rewrite_images(html: str, article_id: int) -> str:
    """解析 <img> 和 CSS url() 中的图片引用，下载并存到 images/ 目录，
    URL 改写为 /api/news/images/{img_hash}.{ext}。"""
    _, _, images_dir = _ensure_content_dirs()
    soup = BeautifulSoup(html, 'html.parser')

    # 1. 处理 <img> 标签
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if not src or src.startswith('data:'):
            continue

        # 跳过已经是本地 URL 的
        if src.startswith('/api/news/'):
            continue

        local_url = _download_single_image(src, article_id, images_dir)
        if local_url:
            img['src'] = local_url
            # 移除 srcset（改用单个 src）
            if img.get('srcset'):
                del img['srcset']

    # 2. 处理 <source> 标签（<picture> 内）
    for source in soup.find_all('source'):
        srcset = source.get('srcset', '')
        if not srcset:
            continue
        # 取第一个 URL
        first_url = srcset.split(',')[0].strip().split(' ')[0]
        if first_url and not first_url.startswith('data:'):
            local_url = _download_single_image(first_url, article_id, images_dir)
            if local_url:
                source['srcset'] = local_url

    # 3. 处理内联 style 中的 background-image
    for el in soup.find_all(style=True):
        style_text = el['style']
        urls = re.findall(r'url\(["\']?([^)"\']+)["\']?\)', style_text)
        for img_url in urls:
            if img_url.startswith('data:') or img_url.startswith('/api/news/'):
                continue
            local_url = _download_single_image(img_url, article_id, images_dir)
            if local_url:
                style_text = style_text.replace(img_url, local_url)
        el['style'] = style_text

    return str(soup)


def _download_single_image(img_url: str, article_id: int, images_dir: str) -> str | None:
    """下载单个图片，返回本地 URL 或 None（失败时）。"""
    try:
        resp = requests.get(img_url, timeout=IMAGE_TIMEOUT,
                            headers={'User-Agent': config.user_agent})
        if resp.status_code != 200:
            return None

        content = resp.content
        if len(content) < 100:  # 太小，可能不是真实图片
            return None

        # 推断扩展名
        content_type = resp.headers.get('Content-Type', '').split(';')[0].strip()
        ext = _MIME_TO_EXT.get(content_type, 'bin')

        # 从 URL 也尝试推断
        url_ext = os.path.splitext(urlparse(img_url).path)[1].lstrip('.').lower()
        if url_ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'):
            ext = url_ext

        # MD5 hash
        img_hash = hashlib.md5(content).hexdigest()

        # 存盘
        filename = f'{article_id}_{img_hash}.{ext}'
        filepath = os.path.join(images_dir, filename)

        if not os.path.exists(filepath):
            with open(filepath, 'wb') as f:
                f.write(content)

        return f'/api/news/images/{img_hash}.{ext}'
    except Exception as e:
        logger.debug(f"图片下载失败: {img_url} — {e}")
        return None


def process_html_for_local_cache(html: str, url: str, article_id: int) -> str:
    """主入口：CSS 内联 + 图片下载 + URL 改写。

    Args:
        html: 原始 HTML 内容
        url: 文章原始 URL（用于解析相对路径和提取 domain）
        article_id: 文章 ID（用于图片命名）

    Returns:
        处理后的 HTML 字符串
    """
    if not html or len(html.strip()) < 100:
        return html

    # Step 1: CSS 内联
    try:
        html = _inline_stylesheets(html, url)
    except Exception as e:
        logger.warning(f"CSS 内联失败: {e}")

    # Step 2: 图片下载 + 改写
    try:
        html = _download_and_rewrite_images(html, article_id)
    except Exception as e:
        logger.warning(f"图片处理失败: {e}")

    return html
```

- [ ] **Step 3: 验证导入**

```bash
cd /srv/LapTalk_NewsAggregationTool/news-web/backend && python -c "
from pipeline.content_processor import process_html_for_local_cache
print('content_processor 导入成功')
"
```

- [ ] **Step 4: Commit**

```bash
git add news-web/backend/pipeline/content_processor.py
git commit -m "feat: 新增 content_processor — CSS 内联 + 图片下载 + URL 改写

process_html_for_local_cache() 将原始 HTML 转为自包含文档:
- CSS: <link>下载→domain+MD5去重存shared/→<style>内联
- 图片: 下载→存images/→URL改写为/api/news/images/...
- 失败优雅降级保留原始URL

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: content_processor 单元测试

**Files:**
- Create: `news-web/tests/backend/test_content_processor.py`

**Interfaces:**
- Consumes: `process_html_for_local_cache()`, `_inline_stylesheets()`, `_download_and_rewrite_images()`

- [ ] **Step 1: 编写测试**

```python
# news-web/tests/backend/test_content_processor.py
import os
import pytest
from pipeline.content_processor import (
    process_html_for_local_cache,
    _inline_stylesheets,
    _download_and_rewrite_images,
    _domain_from_url,
    _ensure_content_dirs,
)


def test_domain_from_url():
    """从 URL 提取域名"""
    assert _domain_from_url('https://techcrunch.com/article/123') == 'techcrunch.com'
    assert _domain_from_url('https://www.anandtech.com/show/456') == 'anandtech.com'
    assert _domain_from_url('http://example.com:8080/path') == 'example.com'


def test_inline_stylesheets_no_stylesheets():
    """无 <link> 的 HTML 保持不变"""
    html = '<html><head></head><body><p>hello</p></body></html>'
    result = _inline_stylesheets(html, 'https://example.com')
    assert '<p>hello</p>' in result


def test_inline_stylesheets_removes_preload_links():
    """非 stylesheet 的 <link> 标签应被移除"""
    html = '<html><head><link rel="preconnect" href="https://fonts.gstatic.com"></head><body></body></html>'
    result = _inline_stylesheets(html, 'https://example.com')
    assert 'preconnect' not in result


def test_download_and_rewrite_images_no_images():
    """无图片的 HTML 保持不变"""
    html = '<html><body><p>text only</p></body></html>'
    result = _download_and_rewrite_images(html, 1)
    assert '<p>text only</p>' in result


def test_download_and_rewrite_images_skips_data_uri():
    """data: URI 图片不被处理"""
    html = '<img src="data:image/png;base64,abc123">'
    result = _download_and_rewrite_images(html, 1)
    assert 'data:image/png;base64,abc123' in result


def test_process_html_for_local_cache_empty():
    """空/短 HTML 直接返回"""
    assert process_html_for_local_cache('', 'https://example.com', 1) == ''
    assert process_html_for_local_cache(None, 'https://example.com', 1) is None


def test_process_html_for_local_cache_basic():
    """完整流程测试 — 无外部资源的 HTML"""
    html = '<html><head></head><body><p>hello world</p></body></html>'
    result = process_html_for_local_cache(html, 'https://example.com/article', 1)
    assert 'hello world' in result


def test_ensure_content_dirs():
    """目录创建"""
    cache_dir, shared_dir, images_dir = _ensure_content_dirs()
    assert os.path.isdir(cache_dir)
    assert os.path.isdir(shared_dir)
    assert os.path.isdir(images_dir)
```

- [ ] **Step 2: 运行测试**

```bash
cd /srv/LapTalk_NewsAggregationTool/news-web && python -m pytest tests/backend/test_content_processor.py -v
# Expected: 8 passed
```

- [ ] **Step 3: Commit**

```bash
git add news-web/tests/backend/test_content_processor.py
git commit -m "test: content_processor 单元测试 — 8 用例

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 修改 /html 端点 + 新增 /shared-css /images 子路径

**Files:**
- Modify: `news-web/backend/api/news.py` (lines ~417-548)

**Interfaces:**
- Consumes: `process_html_for_local_cache()` from Task 1
- Modified: `GET /api/news/{id}/html` — 调用 content_processor 内联化
- New: `GET /api/news/shared-css/{domain}/{hash}.css` — 共享 CSS 文件
- New: `GET /api/news/images/{hash}.{ext}` — 本地图片文件

- [ ] **Step 1: 修改 /html 端点**

在 `/html` 端点的 HTTP download 成功分支和 Playwright 成功分支中，返回前调用 `process_html_for_local_cache()`：

```python
# news-web/backend/api/news.py

# 在文件顶部新增导入:
from pipeline.content_processor import process_html_for_local_cache

# 在 /html 端点中，HTTP download 成功后 (line ~486):
# 在 return _mk_response(html) 之前增加:
html = process_html_for_local_cache(html, url, article_id)

# 在 Playwright 成功后 (line ~508):
# 同样在 return 前增加:
html = process_html_for_local_cache(html, url, article_id)
```

- [ ] **Step 2: 新增 shared-css 端点**

在 `news.py` 中新增（在 `/html` 端点后面）：

```python
@router.get("/shared-css/{domain}/{hash}.css")
async def serve_shared_css(domain: str, hash: str):
    """返回共享 CSS 文件。Cache-Control: immutable（内容由 hash 标识，永不变）。"""
    from fastapi.responses import FileResponse
    import os

    css_path = os.path.join(config.content_cache_path, 'shared', domain, f'{hash}.css')
    if not os.path.isfile(css_path):
        raise HTTPException(404, "css_not_found")

    return FileResponse(
        css_path,
        media_type='text/css',
        headers={
            'Cache-Control': 'max-age=31536000, immutable',
            'Access-Control-Allow-Origin': '*',
        },
    )


@router.get("/images/{hash}.{ext}")
async def serve_cached_image(hash: str, ext: str):
    """返回本地缓存的图片文件。"""
    from fastapi.responses import FileResponse
    import os

    img_path = os.path.join(config.content_cache_path, 'images', f'{hash}.{ext}')
    if not os.path.isfile(img_path):
        raise HTTPException(404, "image_not_found")

    # 推断 Content-Type
    content_type = _MIME_TO_EXT_REVERSE.get(ext, 'application/octet-stream')

    return FileResponse(
        img_path,
        media_type=content_type,
        headers={
            'Cache-Control': 'max-age=86400',
            'Access-Control-Allow-Origin': '*',
        },
    )
```

```python
# 在文件顶部新增 Content-Type 反向映射:
_MIME_TO_EXT_REVERSE = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'svg': 'image/svg+xml',
    'bmp': 'image/bmp',
    'ico': 'image/x-icon',
}
```

- [ ] **Step 3: 运行测试**

```bash
cd /srv/LapTalk_NewsAggregationTool/news-web && python -m pytest tests/backend/ -q
# Expected: 55 passed (47 original + 8 new from Task 2)
```

- [ ] **Step 4: 手动验证端点**

```bash
# 重启后端
bash /srv/LapTalk_NewsAggregationTool/start_platform.sh restart
# 测试一个不存在的 CSS 返回 404
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/api/news/shared-css/test/missing.css
# Expected: 404
```

- [ ] **Step 5: Commit**

```bash
git add news-web/backend/api/news.py
git commit -m "feat: /html 端点集成 content_processor + 新增 shared-css/images 端点

- /html 端点下载成功后自动调用 process_html_for_local_cache 内联化
- GET /api/news/shared-css/{domain}/{hash}.css — 共享CSS (immutable cache)
- GET /api/news/images/{hash}.{ext} — 本地图片缓存

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 前端移除 iframe sandbox

**Files:**
- Modify: `news-web/frontend/src/components/ArticlePane.tsx`
- Modify: `news-web/frontend/src/pages/ArticleReader.tsx`

- [ ] **Step 1: ArticlePane.tsx — 移除 sandbox**

```tsx
// ArticlePane.tsx line ~458
// 旧: sandbox="allow-same-origin allow-popups"
// 新: 移除 sandbox 属性

<iframe
  ref={iframeRef}
  src={`/api/news/${article.id}/html`}
  style={{ width: '100%', height: '100%', border: 'none' }}
  title={article.title}
  onLoad={handleIframeOnLoad}
/>
```

- [ ] **Step 2: ArticleReader.tsx — 移除 sandbox**

```tsx
// ArticleReader.tsx line ~60
// 旧: sandbox="allow-same-origin allow-popups"
// 新: 移除 sandbox 属性

<iframe
  src={`/api/news/${id}/html`}
  onLoad={() => setIframeLoaded(true)}
  style={{ width: '100%', height: '100%', border: 'none' }}
  title={article.title}
/>
```

- [ ] **Step 3: 构建前端**

```bash
cd /srv/LapTalk_NewsAggregationTool/news-web/frontend && npm run build
# Expected: ✓ built in X.XXs
```

- [ ] **Step 4: Commit**

```bash
git add news-web/frontend/src/components/ArticlePane.tsx \
        news-web/frontend/src/pages/ArticleReader.tsx
git commit -m "feat: 移除 iframe sandbox — 本地应用完整浏览器能力

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 集成测试 + 验证

- [ ] **Step 1: 全量后端测试**

```bash
cd /srv/LapTalk_NewsAggregationTool/news-web && python -m pytest tests/backend/ -v
# Expected: 55 passed
```

- [ ] **Step 2: 全量前端测试**

```bash
cd /srv/LapTalk_NewsAggregationTool/news-web/frontend && npm test
# Expected: 16 passed
```

- [ ] **Step 3: 前端构建**

```bash
cd /srv/LapTalk_NewsAggregationTool/news-web/frontend && npm run build
# Expected: 成功
```

- [ ] **Step 4: 重启 + 验证日志**

```bash
bash /srv/LapTalk_NewsAggregationTool/start_platform.sh restart
tail -20 /srv/LapTalk_NewsAggregationTool/news-web/logs/news-web.log
# Expected: DbWriter 已启动, TaskScheduler Worker 数: 10
```

- [ ] **Step 5: Commit + Push**

```bash
git add -A
git commit -m "test: 全量测试通过 — 文章内容内联化集成验证

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin main
```

---

## 依赖关系

```
Task 1 (content_processor) ──→ Task 2 (tests)
                            ──→ Task 3 (/html + endpoints)
Task 3 ──→ Task 5 (integration)
Task 4 (frontend sandbox) ──→ Task 5 (integration)
```

Task 1-2-3 串行，Task 4 可并行。
