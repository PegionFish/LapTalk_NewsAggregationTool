# 文章内容内联化 + 本地资源池设计

> 日期: 2026-07-01 | 状态: 待实现

## 目标

将文章 HTML 内容处理为自包含的静态文档，通过 iframe（无 sandbox）展示，实现类 PDF 阅读器的观看体验。

## 约束

- 本地部署应用，iframe 不需要 sandbox 限制
- CSS 内联到 HTML 中（纯文本，token 量小），图片走本地文件引用
- 同源 CSS 文件共享去重，节约磁盘
- AI 管线吃 `text_content`（纯文本），不受内联化影响
- 已缓存内容直接用本地 HTML，未缓存内容先抓取再展示

## 一、内容抓取与内联化

### 处理流程

```
1. HTTP download / Playwright browser capture  → 获取原始 HTML
2. _sanitize_html(html)                         → 去 script/iframe
3. CSS 内联: <link> → 下载内容 → <style>        ← 新增
4. 图片下载 + URL 改写                          ← 新增
5. 存入 local_path + 提取 text_content          ← 已有
```

### CSS 处理（共享去重）

```python
def _inline_stylesheets(html: str, url: str, article_id: int) -> str:
    """解析 <link rel=stylesheet>, 按 domain 去重存到 shared/ 目录,
    href 改写为 /api/news/shared-css/{domain}/{css_hash}.css"""
```

- 从原始 URL 提取 domain（如 `techcrunch.com`）
- 对每个 `<link rel="stylesheet" href="...">` HTTP 下载 CSS 内容
- CSS 内容做 MD5 → `shared/{domain}/{md5}.css`
- 文件存在就跳过写入，不存在就创建
- HTML 中 `href` 改写为 `/api/news/shared-css/{domain}/{md5}.css`
- 文章内私有 `<style>` 块保留内联不处理

### 图片处理

- 解析 HTML 中所有 `<img src>` + CSS `url()` 引用
- 跳过 data URI（已内联）
- 逐一下载图片 → 存 `content/images/{article_id}_{img_hash}.{ext}`
- HTML 中 URL 改写为 `/api/news/images/{img_hash}.{ext}`
- 下载失败保留原始 URL（优雅降级）

## 二、存储结构

```
content/
├── shared/{domain}/
│   └── {md5_hash}.css                ← 共享 CSS，同源文章复用
├── images/
│   └── {article_id}_{img_hash}.{ext} ← 图片缓存
└── {article_id}.html                 ← 精简 HTML
```

## 三、API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/news/{id}/html` | 返回内联化 HTML（抓取+内联化流程入口） |
| `GET /api/news/shared-css/{domain}/{hash}.css` | 共享 CSS，`Cache-Control: max-age=31536000, immutable` |
| `GET /api/news/images/{hash}.{ext}` | 本地图片缓存 |

## 四、前端展示

- `ArticlePane.tsx` 和 `ArticleReader.tsx` 中 iframe **移除 sandbox 属性**
- iframe 加载 `/api/news/{id}/html`
- 前端不做额外包装

## 五、AI 管线不变

- `text_content` 字段存纯文本，AI 清洗/翻译/KCS/事件匹配只吃这个
- 内联化仅影响 `local_path` 对应的 HTML 文件，不影响 `text_content`

## 六、模块变更清单

### 新增
- `backend/pipeline/content_processor.py` — 内联化处理器（CSS 内联 + 图片下载 + URL 改写）

### 修改
- `backend/api/news.py` — `/html` 端点调用 content_processor；新增 `/shared-css` 和 `/images` 子路径
- `frontend/src/components/ArticlePane.tsx` — 移除 iframe sandbox
- `frontend/src/pages/ArticleReader.tsx` — 移除 iframe sandbox

### 保留
- `backend/pipeline/browser_capture.py` — Playwright 渲染（已有，继续用于抓取）
- `backend/pipeline/fetch_content.py` — HTTP 下载（已有）
