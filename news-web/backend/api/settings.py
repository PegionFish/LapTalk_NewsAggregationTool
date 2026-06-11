from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import config
from ai_client import chat
from translation_client import translate_to_chinese

router = APIRouter(prefix="/api/settings", tags=["settings"])

class SettingsUpdate(BaseModel):
    db_path: str | None = None
    user_agent: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    pipeline_schedule_enabled: bool | None = None
    # 翻译 API
    translation_enabled: bool | None = None
    translation_base_url: str | None = None
    translation_api_key: str | None = None
    translation_model: str | None = None
    translation_target_lang: str | None = None
    # 内容缓存
    content_cache_path: str | None = None
    # 境外内容抓取代理
    proxy_enabled: bool | None = None
    proxy_url: str | None = None

@router.get("")
def get_settings():
    return config.to_dict()

@router.put("")
def update_settings(body: SettingsUpdate):
    if body.db_path is not None:
        config.db_path = body.db_path
    if body.user_agent is not None:
        config.user_agent = body.user_agent
    if body.openai_base_url is not None:
        config.openai_base_url = body.openai_base_url
    if body.openai_api_key is not None and body.openai_api_key != '***':
        config.openai_api_key = body.openai_api_key
    if body.openai_model is not None:
        config.openai_model = body.openai_model
    if body.pipeline_schedule_enabled is not None:
        config.pipeline_schedule_enabled = body.pipeline_schedule_enabled
    # 翻译 API
    if body.translation_enabled is not None:
        config.translation_enabled = body.translation_enabled
    if body.translation_base_url is not None:
        config.translation_base_url = body.translation_base_url
    if body.translation_api_key is not None and body.translation_api_key != '***':
        config.translation_api_key = body.translation_api_key
    if body.translation_model is not None:
        config.translation_model = body.translation_model
    if body.translation_target_lang is not None:
        config.translation_target_lang = body.translation_target_lang
    # 内容缓存
    if body.content_cache_path is not None:
        config.content_cache_path = body.content_cache_path
    # 境外代理
    if body.proxy_enabled is not None:
        config.proxy_enabled = body.proxy_enabled
    if body.proxy_url is not None:
        config.proxy_url = body.proxy_url
    return config.to_dict()


# ══════════════════════════════════════════════════════════════
# API 连通性测试
# ══════════════════════════════════════════════════════════════

@router.post("/test-ai")
def test_ai():
    """发送简短请求验证 AI 分析 API 是否可用。"""
    if not config.openai_api_key:
        return {'ok': False, 'error': 'API Key 未配置'}
    try:
        result = chat("Hello! Reply with just 'OK'.", system_prompt="You only reply 'OK'.")
        return {'ok': True, 'response': result[:200], 'model': config.openai_model}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}


@router.post("/test-translation")
def test_translation_api():
    """发送简短翻译请求验证翻译 API 是否可用。"""
    if not config.translation_api_key:
        return {'ok': False, 'error': '翻译 API Key 未配置'}
    try:
        test_text = "The quick brown fox jumps over the lazy dog."
        result = translate_to_chinese(test_text)
        return {'ok': True, 'original': test_text, 'translation': result[:300], 'model': config.translation_model}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}


# ══════════════════════════════════════════════════════════════
# 代理连通性测试
# ══════════════════════════════════════════════════════════════

@router.post("/test-proxy")
def test_proxy():
    """通过访问 Google 测试代理是否可用。"""
    if not config.proxy_enabled or not config.proxy_url:
        return {'ok': False, 'error': '代理未启用或未配置代理地址'}

    import time as _time
    import urllib.request
    import urllib.error

    proxy_url = config.proxy_url.strip()
    started = _time.monotonic()

    try:
        if proxy_url.startswith('socks'):
            try:
                import socks
                import sockshandler
                from urllib.parse import urlparse
                parsed = urlparse(proxy_url)
                proxy_type = socks.PROXY_TYPE_SOCKS5
                proxy_host = parsed.hostname or '127.0.0.1'
                proxy_port = parsed.port or 1080
                handler = sockshandler.SocksiPyHandler(proxy_type, proxy_host, proxy_port)
                opener = urllib.request.build_opener(handler)
            except ImportError:
                return {'ok': False, 'error': 'PySocks 未安装，无法使用 SOCKS5 代理'}
        else:
            handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
            opener = urllib.request.build_opener(handler)

        req = urllib.request.Request(
            'https://www.google.com',
            headers={'User-Agent': config.user_agent, 'Accept': 'text/html'},
        )
        resp = opener.open(req, timeout=10)
        elapsed_ms = int((_time.monotonic() - started) * 1000)
        size = len(resp.read() or b'')
        resp.close()

        return {
            'ok': True,
            'message': f'代理连接成功 — Google 返回 {size} 字节，耗时 {elapsed_ms}ms',
            'elapsed_ms': elapsed_ms,
            'proxy_url': proxy_url,
        }
    except urllib.error.HTTPError as e:
        elapsed_ms = int((_time.monotonic() - started) * 1000)
        return {
            'ok': True,
            'message': f'代理连通 — Google 返回 HTTP {e.code}，耗时 {elapsed_ms}ms',
            'elapsed_ms': elapsed_ms,
            'proxy_url': proxy_url,
        }
    except urllib.error.URLError as e:
        elapsed_ms = int((_time.monotonic() - started) * 1000)
        return {
            'ok': False,
            'error': f'代理连接失败: {e.reason}',
            'elapsed_ms': elapsed_ms,
        }
    except Exception as e:
        elapsed_ms = int((_time.monotonic() - started) * 1000)
        return {
            'ok': False,
            'error': str(e)[:200],
            'elapsed_ms': elapsed_ms,
        }
