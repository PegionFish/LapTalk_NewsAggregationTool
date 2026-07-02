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
