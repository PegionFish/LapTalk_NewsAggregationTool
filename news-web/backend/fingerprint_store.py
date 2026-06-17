#!/usr/bin/env python3
"""
浏览器指纹存储 — 接收前端真实浏览器特征，供 Playwright 使用。

存储方式：内存（模块级变量）+ JSON 文件持久化。
文件路径：config.content_cache_path/fingerprint.json
"""

import json, os, logging

logger = logging.getLogger(__name__)

_fingerprint = {}

FINGERPRINT_FILE = 'fingerprint.json'


def get_fingerprint_path() -> str:
    from config import config
    return os.path.join(config.content_cache_path, FINGERPRINT_FILE)


def save_fingerprint(fp: dict) -> dict:
    """保存前端提交的浏览器指纹到内存和文件。"""
    global _fingerprint
    _fingerprint = fp
    try:
        path = get_fingerprint_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(fp, f, ensure_ascii=False, indent=2)
        logger.info(f"[fingerprint] 已保存浏览器指纹: UA={fp.get('userAgent','')[:50]}...")
    except Exception as e:
        logger.warning(f"[fingerprint] 持久化失败: {e}")
    return _fingerprint


def load_fingerprint() -> dict:
    """从文件加载指纹（用于 Playwright 启动前读取）。"""
    global _fingerprint
    if _fingerprint:
        return _fingerprint
    try:
        path = get_fingerprint_path()
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                _fingerprint = json.load(f)
    except Exception as e:
        logger.warning(f"[fingerprint] 加载失败: {e}")
    return _fingerprint


def build_playwright_config(fp: dict | None = None) -> dict:
    """将浏览器指纹转为 Playwright browser.new_context() 的参数。"""
    if fp is None:
        fp = load_fingerprint()

    config_kwargs = {}

    if fp.get('userAgent'):
        config_kwargs['user_agent'] = fp['userAgent']

    if fp.get('screenWidth') and fp.get('screenHeight'):
        config_kwargs['viewport'] = {
            'width': fp['screenWidth'],
            'height': fp['screenHeight'],
        }
    else:
        config_kwargs['viewport'] = {'width': 1920, 'height': 1080}

    config_kwargs['locale'] = (fp.get('language') or 'zh-CN').replace('-', '_')
    config_kwargs['timezone_id'] = fp.get('timezone') or 'Asia/Shanghai'

    stealth_script = _build_stealth_script(fp)
    config_kwargs['stealth_script'] = stealth_script

    return config_kwargs


def _build_stealth_script(fp: dict) -> str:
    """生成隐身初始化脚本，使用真实浏览器参数覆盖 Playwright 默认值。"""
    lang_list = json.dumps(fp.get('languages') or ['zh-CN', 'zh', 'en'])
    platform = json.dumps(fp.get('platform') or 'Win32')
    device_memory = fp.get('deviceMemory') or 8
    hardware_concurrency = fp.get('hardwareConcurrency') or 8

    return f"""
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
        Object.defineProperty(navigator, 'platform', {{ get: () => {platform} }});
        Object.defineProperty(navigator, 'plugins', {{ get: () => [1,2,3,4,5] }});
        Object.defineProperty(navigator, 'languages', {{ get: () => {lang_list} }});
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {device_memory} }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {hardware_concurrency} }});
        window.chrome = {{ runtime: {{}} }};
    """
