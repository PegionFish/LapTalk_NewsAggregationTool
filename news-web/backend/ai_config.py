"""
AI 入口级配置模块 — 按调用入口注册，每个入口独立配置 endpoint/key/model/参数。

设计目标（遵循 docs/superpowers/specs/2026-06-23-ai-endpoint-settings-design.md）：
- 3 个 AI 调用入口各自独立配置
- 旧字段兼容映射（config.json 旧字段 ↔ 入口级结构）
- API Key 掩码（*** 不覆盖真实 Key，空字符串明确清空）
- 统一测试入口，每个入口独立反馈
"""
from config import config

# ── 入口注册表 ──────────────────────────────────────────────

AI_ENDPOINTS = {
    'title_filter': {
        'name': '标题初筛',
        'description': 'RSS 抓取后的标题批量筛选，判断文章是否值得缓存',
        'default_model': 'deepseek-v4-flash',
        'default_base_url': 'https://api.deepseek.com',
        'default_enabled': True,
        'params': ['enable_thinking', 'json_response_format'],
        'legacy_field': None,
    },
    'article_processing': {
        'name': '文章处理',
        'description': '内容清洗、翻译、分析摘要、KCS（关键词+分类+评分）',
        'default_model': 'deepseek-v4-flash',
        'default_base_url': 'https://api.deepseek.com',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget'],
        'legacy_field': None,
    },
    'event_pipeline': {
        'name': '事件管线',
        'description': '事件聚类、摘要生成、逻辑链构建',
        'default_model': 'deepseek-v4-flash',
        'default_base_url': 'https://api.deepseek.com',
        'default_enabled': True,
        'params': ['enable_thinking', 'thinking_budget'],
        'legacy_field': None,
    },
}

# ── 旧字段 → 入口级字段映射 ────────────────────────────────

_LEGACY_TO_ENDPOINT = {
    'openai_base_url': 'openai',
    'openai_api_key': 'openai',
    'openai_model': 'openai',
    'simple_model': 'simple',
    'ai_enable_thinking': None,
    'ai_thinking_budget': None,
    'ai_deep_thinking_max_tokens': None,
    'ai_json_response_format': None,
}


def _get_endpoint_base_url(endpoint_key: str) -> str:
    """读取入口的 base_url，回退到默认值。"""
    if endpoint_key == 'title_filter':
        return config.openai_base_url
    elif endpoint_key == 'article_processing':
        return config.openai_base_url
    elif endpoint_key == 'event_pipeline':
        return config.openai_base_url
    return AI_ENDPOINTS.get(endpoint_key, {}).get('default_base_url', 'https://api.deepseek.com')


def _get_endpoint_api_key(endpoint_key: str) -> str:
    """读取入口的 api_key，回退到 openai_api_key。"""
    return config.openai_api_key


def _get_endpoint_model(endpoint_key: str) -> str:
    """读取入口的 model。"""
    if endpoint_key == 'title_filter':
        return config.simple_model
    elif endpoint_key in ('article_processing', 'event_pipeline'):
        return config.openai_model
    return config.openai_model


def _get_endpoint_enabled(endpoint_key: str) -> bool:
    """读取入口的启用状态。"""
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
    if 'json_response_format' in supported:
        params['json_response_format'] = config.ai_json_response_format
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

        # 更新 base_url — 所有入口共用 openai_base_url
        if 'base_url' in ep_data:
            config.openai_base_url = ep_data['base_url']

        # 更新 api_key（*** 不覆盖，空字符串明确清空）
        if 'api_key' in ep_data:
            api_key = ep_data['api_key']
            if api_key == '***':
                pass  # 不覆盖
            elif not api_key:
                config.openai_api_key = ''
            else:
                config.openai_api_key = api_key

        # 更新 model
        if 'model' in ep_data:
            model = ep_data['model']
            if key == 'title_filter':
                config.simple_model = model
            else:
                config.openai_model = model

        # 更新高级参数（全局共享）
        if 'enable_thinking' in ep_data:
            config.ai_enable_thinking = bool(ep_data['enable_thinking'])
        if 'thinking_budget' in ep_data:
            config.ai_thinking_budget = int(ep_data['thinking_budget'])
        if 'json_response_format' in ep_data:
            config.ai_json_response_format = bool(ep_data['json_response_format'])

    return to_ai_endpoint_config()


def test_ai_endpoint(endpoint_key: str) -> dict:
    """测试单个入口的连通性。"""
    from ai_client import chat

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

    import time as _time
    started = _time.monotonic()

    try:
        if endpoint_key == 'title_filter':
            # 用一组模拟标题测试筛选逻辑
            test_articles = [
                (1, 'OpenAI releases GPT-5 with breakthrough reasoning capabilities', 'TechCrunch'),
                (2, 'NVIDIA announces Blackwell Ultra GPU architecture for AI training', 'AnandTech'),
                (3, 'Best gaming headsets for Elden Ring DLC 2024', 'IGN'),
                (4, 'TSMC begins mass production of 2nm chips', 'Reuters'),
                (5, 'How to beat Malenia in Elden Ring - complete guide', 'GameSpot'),
            ]
            from pipeline.ai_filter import filter_batch
            result_ids = filter_batch(test_articles, model=ep_config.get('model'))
            elapsed_ms = int((_time.monotonic() - started) * 1000)
            if result_ids is None:
                return {
                    'endpoint_key': endpoint_key,
                    'ok': False,
                    'model': ep_config.get('model', ''),
                    'error': 'API 调用失败',
                    'elapsed_ms': elapsed_ms,
                }
            approved = [a[1] for a in test_articles if a[0] in result_ids]
            return {
                'endpoint_key': endpoint_key,
                'ok': True,
                'model': ep_config.get('model', ''),
                'response': f'保留 {len(result_ids)} 篇: ' + '; '.join(approved[:3]),
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
