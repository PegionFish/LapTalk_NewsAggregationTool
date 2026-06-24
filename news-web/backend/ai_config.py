"""
AI 入口级配置模块 — 集中管理所有 AI 端点的映射、默认值与模型解析。

设计目标：
- 单一配置源（config.json），通过 Provider 注册机制避免重复
- 统一测试入口，支持按端点测试和全部测试
- 模型解析：任务类型 → provider_id → model_id，默认值可被 config.json 覆盖
"""
from config import config

# ── 端点注册表 ──────────────────────────────────────────────

AI_CONFIG_FIELDS = [
    'openai_base_url', 'openai_api_key', 'openai_model',
    'simple_model', 'clean_model', 'clean_base_url', 'clean_api_key',
    'pipeline_model',
    'translation_base_url', 'translation_api_key', 'translation_model',
    'ai_enable_thinking', 'ai_thinking_budget',
    'ai_deep_thinking_max_tokens', 'ai_json_response_format',
]

# 任务类型 → 默认模型映射（可被 config.json 覆盖）
AI_TASK_DEFAULTS = {
    'analyze': 'deepseek-ai/DeepSeek-V3.2',
    'simple': 'Qwen/Qwen3.5-35B-A3B',
    'clean': 'nex-agi/Nex-N2-Pro',
    'translation': 'deepseek-ai/DeepSeek-V3.2',
}


def get_ai_config() -> dict:
    """获取 AI 入口级配置（含 provider、endpoint、settings、tasks）。"""
    providers = {}

    # SiliconFlow 主端点（分析/简单任务）
    sf_id = 'siliconflow'
    sf_base = config.openai_base_url
    sf_key = config.openai_api_key
    providers[sf_id] = {
        'id': sf_id,
        'name': 'SiliconFlow',
        'base_url': sf_base,
        'api_key': sf_key,
        'api_key_masked': '***' if sf_key else '',
        'status': 'unknown',
        'models': {
            'analyze': config.openai_model or AI_TASK_DEFAULTS['analyze'],
            'simple': config.simple_model or AI_TASK_DEFAULTS['simple'],
        },
    }

    # 清洗端点（可能独立于主端点）
    clean_base = config.clean_base_url
    clean_key = config.clean_api_key
    clean_same = (clean_base == sf_base and clean_key == sf_key)
    if clean_same:
        providers[sf_id]['models']['clean'] = config.clean_model or AI_TASK_DEFAULTS['clean']
    else:
        clean_id = 'siliconflow_clean'
        providers[clean_id] = {
            'id': clean_id,
            'name': 'SiliconFlow 清洗',
            'base_url': clean_base,
            'api_key': clean_key,
            'api_key_masked': '***' if clean_key else '',
            'status': 'unknown',
            'models': {
                'clean': config.clean_model or AI_TASK_DEFAULTS['clean'],
            },
        }

    # 翻译端点
    trans_base = config.translation_base_url
    trans_key = config.translation_api_key
    trans_same = (trans_base == sf_base and trans_key == sf_key)
    if trans_same:
        providers[sf_id]['models']['translation'] = config.translation_model or AI_TASK_DEFAULTS['translation']
    else:
        trans_id = 'siliconflow_translation'
        providers[trans_id] = {
            'id': trans_id,
            'name': 'SiliconFlow 翻译',
            'base_url': trans_base,
            'api_key': trans_key,
            'api_key_masked': '***' if trans_key else '',
            'status': 'unknown',
            'models': {
                'translation': config.translation_model or AI_TASK_DEFAULTS['translation'],
            },
        }

    # 端点配置文件（简化前端分组展示）
    profiles = [
        {
            'id': 'analyze',
            'name': 'AI 分析',
            'description': '文章分析、事件总结、全景推理',
            'provider_id': sf_id,
            'model_id': config.openai_model or AI_TASK_DEFAULTS['analyze'],
        },
        {
            'id': 'simple',
            'name': '轻量任务',
            'description': '关键词提取、话题分类、优先级评分',
            'provider_id': sf_id,
            'model_id': config.simple_model or AI_TASK_DEFAULTS['simple'],
        },
        {
            'id': 'clean',
            'name': '内容清洗',
            'description': '去除广告/导航，提取纯净正文',
            'provider_id': sf_id if clean_same else 'siliconflow_clean',
            'model_id': config.clean_model or AI_TASK_DEFAULTS['clean'],
        },
        {
            'id': 'translation',
            'name': 'AI 翻译',
            'description': '英文科技新闻自动译中文',
            'provider_id': sf_id if trans_same else 'siliconflow_translation',
            'model_id': config.translation_model or AI_TASK_DEFAULTS['translation'],
            'enabled': config.translation_enabled,
        },
    ]

    # 全局设置
    settings = {
        'enable_thinking': config.ai_enable_thinking,
        'thinking_budget': config.ai_thinking_budget,
        'deep_thinking_max_tokens': config.ai_deep_thinking_max_tokens,
        'json_response_format': config.ai_json_response_format,
    }

    return {
        'providers': providers,
        'profiles': profiles,
        'settings': settings,
    }


def resolve_ai_model(task: str) -> str | None:
    """根据任务类型解析当前使用的模型 ID。"""
    mapping = {
        'analyze': config.openai_model,
        'simple': config.simple_model,
        'clean': config.clean_model,
        'translation': config.translation_model,
    }
    return mapping.get(task) or AI_TASK_DEFAULTS.get(task)


def update_ai_config(data: dict) -> None:
    """批量更新 AI 配置字段（仅更新 data 中非 None 的字段）。"""
    field_map = {
        'openai_base_url': ('openai_base_url', str),
        'openai_api_key': ('openai_api_key', str),
        'openai_model': ('openai_model', str),
        'simple_model': ('simple_model', str),
        'clean_model': ('clean_model', str),
        'clean_base_url': ('clean_base_url', str),
        'clean_api_key': ('clean_api_key', str),
        'pipeline_model': ('pipeline_model', str),
        'translation_base_url': ('translation_base_url', str),
        'translation_api_key': ('translation_api_key', str),
        'translation_model': ('translation_model', str),
        'translation_enabled': ('translation_enabled', bool),
        'ai_enable_thinking': ('ai_enable_thinking', bool),
        'ai_thinking_budget': ('ai_thinking_budget', int),
        'ai_deep_thinking_max_tokens': ('ai_deep_thinking_max_tokens', int),
        'ai_json_response_format': ('ai_json_response_format', bool),
    }
    for key, value in data.items():
        if value is None:
            continue
        if key == 'openai_api_key' and value == '***':
            continue
        if key == 'translation_api_key' and value == '***':
            continue
        if key == 'clean_api_key' and value == '***':
            continue
        if key in field_map:
            config_attr, _ = field_map[key]
            setattr(config, config_attr, value)
