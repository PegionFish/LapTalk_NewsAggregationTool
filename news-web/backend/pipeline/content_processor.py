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
