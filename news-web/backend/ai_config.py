"""
AI 入口级配置模块 — 所有入口返回统一配置。

三个入口（title_filter / article_processing / event_pipeline）共用
config.openai_base_url / config.openai_model / config.openai_api_key。
"""
from config import config

# ── 入口注册表（用于迭代和展示）────────────────────────────────

AI_ENDPOINTS = {
    'title_filter': {
        'name': '标题初筛',
        'description': 'RSS 抓取后的标题批量筛选，判断文章是否值得缓存',
        'default_enabled': True,
    },
    'article_processing': {
        'name': '文章处理',
        'description': '内容清洗、翻译、分析摘要、KCS（关键词+分类+评分）',
        'default_enabled': True,
    },
    'event_pipeline': {
        'name': '事件管线',
        'description': '事件聚类、摘要生成、逻辑链构建',
        'default_enabled': True,
    },
}


def _get_endpoint_base_url(_endpoint_key: str) -> str:
    """所有入口共用 openai_base_url。"""
    return config.openai_base_url


def _get_endpoint_api_key(_endpoint_key: str) -> str:
    """所有入口共用 openai_api_key。"""
    return config.openai_api_key


def _get_endpoint_model(_endpoint_key: str) -> str:
    """所有入口共用 openai_model。"""
    return config.openai_model


def _get_endpoint_enabled(endpoint_key: str) -> bool:
    """读取入口的启用状态。"""
    return AI_ENDPOINTS.get(endpoint_key, {}).get('default_enabled', True)


def _mask_key(key: str) -> str:
    """API Key 掩码：非空返回 ***，空返回空字符串。"""
    return '***' if key else ''


def _get_endpoint_params(_endpoint_key: str) -> dict:
    """读取入口支持的高级参数（全局共享）。"""
    params = {}
    if hasattr(config, 'ai_enable_thinking'):
        params['enable_thinking'] = config.ai_enable_thinking
    if hasattr(config, 'ai_thinking_budget'):
        params['thinking_budget'] = config.ai_thinking_budget
    if hasattr(config, 'ai_json_response_format'):
        params['json_response_format'] = config.ai_json_response_format
    return params


def to_ai_endpoint_config() -> dict:
    """从 config 读取统一配置，为每个入口生成相同的配置。"""
    base_url = _get_endpoint_base_url('')
    api_key = _get_endpoint_api_key('')
    model = _get_endpoint_model('')
    params = _get_endpoint_params('')

    endpoints = {}
    for key in AI_ENDPOINTS:
        entry = {
            'enabled': _get_endpoint_enabled(key),
            'base_url': base_url,
            'api_key': _mask_key(api_key),
            'model': model,
        }
        entry.update(params)
        endpoints[key] = entry

    return {'ai_endpoints': endpoints, 'ai_workers': config.ai_workers}


def apply_ai_endpoint_config(body: dict) -> dict:
    """接收入口级配置，写回 config 统一字段，返回掩码后的配置。"""
    endpoints = body.get('ai_endpoints', {})
    if not isinstance(endpoints, dict):
        return to_ai_endpoint_config()

    for key, ep_data in endpoints.items():
        if key not in AI_ENDPOINTS:
            continue
        if not isinstance(ep_data, dict):
            continue

        # 更新 base_url
        if 'base_url' in ep_data:
            config.openai_base_url = ep_data['base_url']

        # 更新 api_key（*** 不覆盖，空字符串明确清空）
        if 'api_key' in ep_data:
            api_key = ep_data['api_key']
            if api_key == '***':
                pass
            elif not api_key:
                config.openai_api_key = ''
            else:
                config.openai_api_key = api_key

        # 更新 model
        if 'model' in ep_data:
            config.openai_model = ep_data['model']

        # 更新高级参数（全局共享）
        if 'enable_thinking' in ep_data and hasattr(config, 'ai_enable_thinking'):
            config.ai_enable_thinking = bool(ep_data['enable_thinking'])
        if 'thinking_budget' in ep_data and hasattr(config, 'ai_thinking_budget'):
            config.ai_thinking_budget = int(ep_data['thinking_budget'])
        if 'json_response_format' in ep_data and hasattr(config, 'ai_json_response_format'):
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
