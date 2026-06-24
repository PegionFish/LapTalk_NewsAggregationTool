"""
AI 入口级配置模块 — 按调用入口注册，每个入口独立配置 endpoint/key/model/参数。

设计目标（遵循 docs/superpowers/specs/2026-06-23-ai-endpoint-settings-design.md）：
- 10 个 AI 调用入口各自独立配置
- 旧字段兼容映射（config.json 旧字段 ↔ 入口级结构）
- API Key 掩码（*** 不覆盖真实 Key，空字符串明确清空）
- 统一测试入口，每个入口独立反馈
"""
from config import config

# ── 入口注册表 ──────────────────────────────────────────────

AI_ENDPOINTS = {
    'rss_prefilter': {
        'name': 'RSS 预过滤',
        'description': 'RSS 抓取后的内容预筛选',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'Qwen/Qwen3.5-35B-A3B',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget', 'json_response_format'],
        'legacy_field': None,
        'test_status': 'skipped',
        'test_reason': '入口尚未接入',
    },
    'html_clean': {
        'name': '内容清洗',
        'description': '去除广告/导航/推荐，提取纯净正文',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'nex-agi/Nex-N2-Pro',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget', 'json_response_format'],
        'legacy_field': 'clean',
    },
    'translation': {
        'name': 'AI 翻译',
        'description': '英文科技新闻自动译中文',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'deepseek-ai/DeepSeek-V3.2',
        'default_enabled': False,
        'params': ['target_lang', 'max_tokens'],
        'legacy_field': 'translation',
    },
    'article_analysis': {
        'name': '文章分析',
        'description': '单篇科技新闻深度分析摘要',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'deepseek-ai/DeepSeek-V3.2',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget', 'deep_thinking_max_tokens', 'json_response_format'],
        'legacy_field': 'openai',
    },
    'event_summary': {
        'name': '事件总结',
        'description': '为同一事件的多篇文章生成综合摘要',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'deepseek-ai/DeepSeek-V3.2',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget', 'deep_thinking_max_tokens', 'json_response_format'],
        'legacy_field': 'openai',
    },
    'event_ranking': {
        'name': '事件排序',
        'description': '全景图推理全局事件优先级排序',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'deepseek-ai/DeepSeek-V3.2',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget', 'deep_thinking_max_tokens', 'json_response_format'],
        'legacy_field': 'openai',
    },
    'chain_building': {
        'name': '逻辑链构建',
        'description': '全景图推理识别事件分组并构筑逻辑链',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'deepseek-ai/DeepSeek-V3.2',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget', 'deep_thinking_max_tokens', 'json_response_format'],
        'legacy_field': 'openai',
    },
    'keyword_extraction': {
        'name': '关键词提取',
        'description': '从标题+正文提取技术关键词',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'Qwen/Qwen3.5-35B-A3B',
        'default_enabled': True,
        'params': ['enable_thinking', 'json_response_format'],
        'legacy_field': 'simple',
    },
    'article_classification': {
        'name': '话题分类',
        'description': 'AI 分类文章主题领域',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'Qwen/Qwen3.5-35B-A3B',
        'default_enabled': True,
        'params': ['enable_thinking', 'json_response_format'],
        'legacy_field': 'simple',
    },
    'priority_scoring': {
        'name': '优先级评分',
        'description': 'AI 评估文章优先级（百分制 0~100）',
        'default_base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'Qwen/Qwen3.5-35B-A3B',
        'default_enabled': True,
        'params': ['enable_thinking', 'json_response_format'],
        'legacy_field': 'simple',
    },
}

# ── 旧字段 → 入口级字段映射 ────────────────────────────────

_LEGACY_TO_ENDPOINT = {
    'openai_base_url': 'openai',
    'openai_api_key': 'openai',
    'openai_model': 'openai',
    'simple_model': 'simple',
    'clean_base_url': 'clean',
    'clean_api_key': 'clean',
    'clean_model': 'clean',
    'translation_base_url': 'translation',
    'translation_api_key': 'translation',
    'translation_model': 'translation',
    'translation_enabled': 'translation',
    'translation_target_lang': 'translation',
    'ai_enable_thinking': None,
    'ai_thinking_budget': None,
    'ai_deep_thinking_max_tokens': None,
    'ai_json_response_format': None,
}


def _get_endpoint_base_url(endpoint_key: str) -> str:
    """读取入口的 base_url，回退到默认值。"""
    mapping = {
        'openai': ('openai_base_url', 'https://api.siliconflow.cn/v1'),
        'simple': ('openai_base_url', 'https://api.siliconflow.cn/v1'),
        'clean': ('clean_base_url', 'https://api.siliconflow.cn/v1'),
        'translation': ('translation_base_url', 'https://api.siliconflow.cn/v1'),
    }
    for prefix, (field, default) in mapping.items():
        if endpoint_key.startswith(prefix) or endpoint_key == prefix:
            return getattr(config, field, default)
    return AI_ENDPOINTS.get(endpoint_key, {}).get('default_base_url', 'https://api.siliconflow.cn/v1')


def _get_endpoint_api_key(endpoint_key: str) -> str:
    """读取入口的 api_key，回退到 openai_api_key。"""
    mapping = {
        'openai': 'openai_api_key',
        'clean': 'clean_api_key',
        'translation': 'translation_api_key',
    }
    for prefix, field in mapping.items():
        if endpoint_key.startswith(prefix) or endpoint_key == prefix:
            return getattr(config, field, '')
    return config.openai_api_key


def _get_endpoint_model(endpoint_key: str) -> str:
    """读取入口的 model。"""
    mapping = {
        'rss_prefilter': 'simple_model',
        'html_clean': 'clean_model',
        'translation': 'translation_model',
        'article_analysis': 'openai_model',
        'event_summary': 'openai_model',
        'event_ranking': 'openai_model',
        'chain_building': 'openai_model',
        'keyword_extraction': 'simple_model',
        'article_classification': 'simple_model',
        'priority_scoring': 'simple_model',
    }
    field = mapping.get(endpoint_key)
    if field:
        return getattr(config, field, '')
    return AI_ENDPOINTS.get(endpoint_key, {}).get('default_model', '')


def _get_endpoint_enabled(endpoint_key: str) -> bool:
    """读取入口的启用状态。"""
    if endpoint_key == 'translation':
        return config.translation_enabled
    return AI_ENDPOINTS.get(endpoint_key, {}).get('default_enabled', True)


def _mask_key(key: str) -> str:
    """API Key 掩码：非空返回 ***，空返回空字符串。"""
    return '***' if key else ''


def _get_endpoint_params(endpoint_key: str) -> dict:
    """读取入口支持的高级参数。"""
    ep_def = AI_ENDPOINTS.get(endpoint_key, {})
    supported = ep_def.get('params', [])
    params = {}
    if 'enable_thinking' in supported:
        params['enable_thinking'] = config.ai_enable_thinking
    if 'thinking_budget' in supported:
        params['thinking_budget'] = config.ai_thinking_budget
    if 'deep_thinking_max_tokens' in supported:
        params['deep_thinking_max_tokens'] = config.ai_deep_thinking_max_tokens
    if 'json_response_format' in supported:
        params['json_response_format'] = config.ai_json_response_format
    if 'target_lang' in supported:
        params['target_lang'] = config.translation_target_lang
    if 'max_tokens' in supported:
        params['max_tokens'] = 65536
    return params


def to_ai_endpoint_config() -> dict:
    """从 config._data 读取旧字段，推导每个入口的 endpoint 配置，返回掩码后的结构。"""
    endpoints = {}
    for key, ep_def in AI_ENDPOINTS.items():
        base_url = _get_endpoint_base_url(key)
        api_key = _get_endpoint_api_key(key)
        model = _get_endpoint_model(key)
        enabled = _get_endpoint_enabled(key)
        params = _get_endpoint_params(key)

        entry = {
            'enabled': enabled,
            'base_url': base_url,
            'api_key': _mask_key(api_key),
            'model': model,
        }
        entry.update(params)

        # rss_prefilter 特殊处理
        if key == 'rss_prefilter':
            entry['test_status'] = 'skipped'
            entry['test_reason'] = ep_def.get('test_reason', '入口尚未接入')

        endpoints[key] = entry

    return {'ai_endpoints': endpoints}


def apply_ai_endpoint_config(body: dict) -> dict:
    """接收入口级配置，写回 config 旧字段，返回掩码后的入口级配置。"""
    endpoints = body.get('ai_endpoints', {})
    if not isinstance(endpoints, dict):
        return to_ai_endpoint_config()

    for key, ep_data in endpoints.items():
        if key not in AI_ENDPOINTS:
            continue
        if not isinstance(ep_data, dict):
            continue

        # 更新 enabled
        if 'enabled' in ep_data:
            if key == 'translation':
                config.translation_enabled = bool(ep_data['enabled'])

        # 更新 base_url
        if 'base_url' in ep_data:
            base_url = ep_data['base_url']
            if key in ('html_clean',):
                config.clean_base_url = base_url
            elif key == 'translation':
                config.translation_base_url = base_url
            elif key in ('article_analysis', 'event_summary', 'event_ranking', 'chain_building'):
                config.openai_base_url = base_url
            elif key in ('keyword_extraction', 'article_classification', 'priority_scoring', 'rss_prefilter'):
                config.openai_base_url = base_url

        # 更新 api_key（*** 不覆盖，空字符串明确清空）
        if 'api_key' in ep_data:
            api_key = ep_data['api_key']
            if api_key == '***':
                pass  # 不覆盖
            elif api_key == '' or api_key is None:
                if key in ('html_clean',):
                    config.clean_api_key = ''
                elif key == 'translation':
                    config.translation_api_key = ''
                else:
                    config.openai_api_key = ''
            else:
                if key in ('html_clean',):
                    config.clean_api_key = api_key
                elif key == 'translation':
                    config.translation_api_key = api_key
                else:
                    config.openai_api_key = api_key

        # 更新 model
        if 'model' in ep_data:
            model = ep_data['model']
            if key == 'html_clean':
                config.clean_model = model
            elif key == 'translation':
                config.translation_model = model
            elif key in ('keyword_extraction', 'article_classification', 'priority_scoring', 'rss_prefilter'):
                config.simple_model = model
            else:
                config.openai_model = model

        # 更新高级参数（全局共享）
        if 'enable_thinking' in ep_data:
            config.ai_enable_thinking = bool(ep_data['enable_thinking'])
        if 'thinking_budget' in ep_data:
            config.ai_thinking_budget = int(ep_data['thinking_budget'])
        if 'deep_thinking_max_tokens' in ep_data:
            config.ai_deep_thinking_max_tokens = int(ep_data['deep_thinking_max_tokens'])
        if 'json_response_format' in ep_data:
            config.ai_json_response_format = bool(ep_data['json_response_format'])
        if 'target_lang' in ep_data:
            config.translation_target_lang = ep_data['target_lang']

    return to_ai_endpoint_config()


def test_ai_endpoint(endpoint_key: str) -> dict:
    """测试单个入口的连通性。"""
    from ai_client import chat
    from translation_client import translate_to_chinese

    ep_config = to_ai_endpoint_config().get('ai_endpoints', {}).get(endpoint_key, {})

    if not ep_config.get('enabled'):
        return {
            'endpoint_key': endpoint_key,
            'ok': None,
            'skipped': True,
            'reason': '入口已禁用',
        }

    api_key = _get_endpoint_api_key(endpoint_key)
    if not api_key:
        return {
            'endpoint_key': endpoint_key,
            'ok': False,
            'error': 'API Key 未配置',
            'model': ep_config.get('model', ''),
        }

    # rss_prefilter 尚未接入
    if endpoint_key == 'rss_prefilter':
        return {
            'endpoint_key': endpoint_key,
            'ok': None,
            'skipped': True,
            'reason': AI_ENDPOINTS['rss_prefilter'].get('test_reason', '入口尚未接入'),
        }

    import time as _time
    started = _time.monotonic()

    try:
        if endpoint_key == 'translation':
            test_text = "The quick brown fox jumps over the lazy dog."
            result = translate_to_chinese(test_text)
            elapsed_ms = int((_time.monotonic() - started) * 1000)
            return {
                'endpoint_key': endpoint_key,
                'ok': True,
                'model': ep_config.get('model', ''),
                'response': result[:300],
                'elapsed_ms': elapsed_ms,
            }
        else:
            result = chat(
                "Hello! Reply with just 'OK'.",
                system_prompt="You only reply 'OK'.",
                max_tokens=64,
                enable_thinking=False,
                model=ep_config.get('model'),
            )
            elapsed_ms = int((_time.monotonic() - started) * 1000)
            return {
                'endpoint_key': endpoint_key,
                'ok': True,
                'model': ep_config.get('model', ''),
                'response': result[:200],
                'elapsed_ms': elapsed_ms,
            }
    except Exception as e:
        elapsed_ms = int((_time.monotonic() - started) * 1000)
        return {
            'endpoint_key': endpoint_key,
            'ok': False,
            'model': ep_config.get('model', ''),
            'error': str(e)[:200],
            'elapsed_ms': elapsed_ms,
        }


def test_all_ai_endpoints() -> dict:
    """测试所有启用的入口，返回汇总和每个入口结果。"""
    results = []
    total = len(AI_ENDPOINTS)
    passed = 0
    failed = 0
    skipped = 0

    for key in AI_ENDPOINTS:
        result = test_ai_endpoint(key)
        results.append(result)
        if result.get('skipped'):
            skipped += 1
        elif result.get('ok'):
            passed += 1
        else:
            failed += 1

    return {
        'ok': failed == 0,
        'summary': {
            'total': total,
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
        },
        'results': results,
    }
