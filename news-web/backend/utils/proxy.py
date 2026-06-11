"""
境外内容抓取代理工具 — 统一 urllib 和 httpx 的代理配置。

使用方式：
  - 模块顶层调用 setup_urllib_proxy()，之后所有 urllib 请求自动走代理
  - httpx 调用处使用 get_httpx_proxy() 获取代理 URL 传入 AsyncClient

仅对 RSS/页面下载生效，AI/翻译客户端不调用本模块。
"""
import logging
from config import config

logger = logging.getLogger(__name__)

_proxy_setup_done = False


def get_httpx_proxy() -> str | None:
    """返回 httpx 兼容的代理 URL，未启用时返回 None。
    支持 http://、socks5://、socks5h:// 协议。"""
    if not config.proxy_enabled or not config.proxy_url:
        return None
    return config.proxy_url


def setup_urllib_proxy():
    """若代理已启用，为 urllib.request 安装全局代理。
    幂等调用（仅第一次生效）。HTTP 代理走原生 ProxyHandler，
    SOCKS5 代理需要 PySocks 库支持。"""
    global _proxy_setup_done
    if _proxy_setup_done:
        return
    _proxy_setup_done = True

    if not config.proxy_enabled or not config.proxy_url:
        return

    url = config.proxy_url.strip()
    if not url:
        return

    import urllib.request

    if url.startswith('socks'):
        # SOCKS5 代理 — 需要 PySocks (或 socks) 库
        try:
            import socks
            import sockshandler
            import socket
            # 解析 socks5://host:port 格式
            from urllib.parse import urlparse
            parsed = urlparse(url)
            proxy_type = socks.PROXY_TYPE_SOCKS5
            proxy_host = parsed.hostname or '127.0.0.1'
            proxy_port = parsed.port or 1080
            handler = sockshandler.SocksiPyHandler(proxy_type, proxy_host, proxy_port)
            opener = urllib.request.build_opener(handler)
            urllib.request.install_opener(opener)
            logger.info(f"[proxy] SOCKS5 代理已启用: {proxy_host}:{proxy_port}")
        except ImportError:
            logger.warning(
                "[proxy] SOCKS5 代理需要 PySocks 库，请执行: pip install PySocks\n"
                f"       已跳过代理设置，代理 URL: {url}"
            )
        except Exception as e:
            logger.warning(f"[proxy] SOCKS5 代理设置失败: {e}")
    else:
        # HTTP/HTTPS 代理 — urllib 原生支持
        handler = urllib.request.ProxyHandler({
            'http': url,
            'https': url,
        })
        opener = urllib.request.build_opener(handler)
        urllib.request.install_opener(opener)
        logger.info(f"[proxy] HTTP 代理已启用: {url}")
