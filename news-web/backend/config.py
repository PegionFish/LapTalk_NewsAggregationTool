import json, os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

DEFAULT_CONFIG = {
    'db_path': '',
    'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'openai_base_url': 'https://api.siliconflow.cn/v1',
    'openai_api_key': '',
    'openai_model': 'deepseek-ai/DeepSeek-V3.2',
    'simple_model': 'Qwen/Qwen3.5-35B-A3B',       # 关键词/分类/评分等轻量任务
    'clean_model': 'nex-agi/Nex-N2-Pro',            # 内容清洗专用（SiliconFlow 平台）
    'clean_base_url': 'https://api.siliconflow.cn/v1',  # 清洗 API 地址（已切回 SiliconFlow）
    'clean_api_key': '',                                 # 清洗 API 密钥（空=复用 openai_api_key）
    'pipeline_model': 'deepseek-ai/DeepSeek-V3.1-Terminus',  # 分析/分类/评分等线性管道
    'ai_enable_thinking': True,
    'ai_thinking_budget': 32768,
    'ai_deep_thinking_max_tokens': 8192,
    'ai_json_response_format': True,
    'pipeline_schedule_enabled': True,
    'pipeline_cron_hours': [10, 17],      # 数据采集每天运行的小时数（0-23）
    'pipeline_cron_minutes': [0, 0],      # 对应每个小时的分钟数
    'ai_cron_enabled': True,              # AI 全流程定时开关
    'ai_cron_hours': [15, 22],            # AI 全流程每天运行的小时数（0-23）
    'ai_cron_minutes': [0, 0],            # 对应每个小时的分钟数
    # 翻译 API — 独立配置，默认指向硅基流动 DeepSeek V3.2
    'translation_enabled': False,
    'translation_base_url': 'https://api.siliconflow.cn/v1',
    'translation_api_key': '',
    'translation_model': 'deepseek-ai/DeepSeek-V3.2',
    'translation_target_lang': 'zh-CN',
    # 内容缓存目录 — 默认为 DB 同级的 content/ 目录
    'content_cache_path': '',
    # 平台热搜采集 — 微博/知乎/抖音/头条 + B站热门视频
    'platform_hotlist_enabled': True,
    'bilibili_max_pages': 7,
    # 境外内容抓取代理 — 仅用于 RSS/页面下载，AI/翻译不走代理
    'proxy_enabled': False,
    'proxy_url': '',   # http://127.0.0.1:7890 或 socks5://127.0.0.1:1080
}

class AppConfig:
    def __init__(self):
        self._data = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    self._data.update(json.load(f))
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @property
    def db_path(self) -> str:
        val = self._data.get('db_path', '')
        if val:
            return val
        # 自动推导默认路径：backend/data/news.db（仓库模板 db_path 留空时回退）
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'news.db')

    @db_path.setter
    def db_path(self, val: str):
        self._data['db_path'] = val
        self.save()

    @property
    def user_agent(self) -> str:
        return self._data.get('user_agent', DEFAULT_CONFIG['user_agent'])

    @user_agent.setter
    def user_agent(self, val: str):
        self._data['user_agent'] = val
        self.save()

    @property
    def openai_base_url(self) -> str:
        return self._data.get('openai_base_url', DEFAULT_CONFIG['openai_base_url'])

    @openai_base_url.setter
    def openai_base_url(self, val: str):
        self._data['openai_base_url'] = val
        self.save()

    @property
    def openai_api_key(self) -> str:
        return self._data.get('openai_api_key', '')

    @openai_api_key.setter
    def openai_api_key(self, val: str):
        self._data['openai_api_key'] = val
        self.save()

    @property
    def openai_model(self) -> str:
        return self._data.get('openai_model', DEFAULT_CONFIG['openai_model'])

    @openai_model.setter
    def openai_model(self, val: str):
        self._data['openai_model'] = val
        self.save()

    @property
    def clean_model(self) -> str:
        return self._data.get('clean_model', self.openai_model)

    @clean_model.setter
    def clean_model(self, val: str):
        self._data['clean_model'] = val
        self.save()

    @property
    def clean_base_url(self) -> str:
        return self._data.get('clean_base_url', self.openai_base_url)

    @clean_base_url.setter
    def clean_base_url(self, val: str):
        self._data['clean_base_url'] = val
        self.save()

    @property
    def clean_api_key(self) -> str:
        return self._data.get('clean_api_key', '') or self.openai_api_key

    @clean_api_key.setter
    def clean_api_key(self, val: str):
        self._data['clean_api_key'] = val
        self.save()

    @property
    def simple_model(self) -> str:
        return self._data.get('simple_model', self.openai_model)

    @simple_model.setter
    def simple_model(self, val: str):
        self._data['simple_model'] = val
        self.save()

    @property
    def pipeline_model(self) -> str:
        return self._data.get('pipeline_model', DEFAULT_CONFIG['pipeline_model'])

    @pipeline_model.setter
    def pipeline_model(self, val: str):
        self._data['pipeline_model'] = val
        self.save()

    @property
    def ai_enable_thinking(self) -> bool:
        return self._data.get('ai_enable_thinking', True) is True

    @ai_enable_thinking.setter
    def ai_enable_thinking(self, val: bool):
        self._data['ai_enable_thinking'] = bool(val)
        self.save()

    @property
    def ai_thinking_budget(self) -> int:
        val = self._data.get('ai_thinking_budget', 32768)
        try:
            return max(128, min(32768, int(val)))
        except (TypeError, ValueError):
            return 32768

    @ai_thinking_budget.setter
    def ai_thinking_budget(self, val: int):
        self._data['ai_thinking_budget'] = self.ai_thinking_budget if val is None else int(val)
        self.save()

    @property
    def ai_deep_thinking_max_tokens(self) -> int:
        val = self._data.get('ai_deep_thinking_max_tokens', 8192)
        try:
            return max(1024, int(val))
        except (TypeError, ValueError):
            return 8192

    @ai_deep_thinking_max_tokens.setter
    def ai_deep_thinking_max_tokens(self, val: int):
        self._data['ai_deep_thinking_max_tokens'] = int(val)
        self.save()

    @property
    def ai_json_response_format(self) -> bool:
        return self._data.get('ai_json_response_format', True) is True

    @ai_json_response_format.setter
    def ai_json_response_format(self, val: bool):
        self._data['ai_json_response_format'] = bool(val)
        self.save()

    @property
    def pipeline_schedule_enabled(self) -> bool:
        return self._data.get('pipeline_schedule_enabled', True)

    @pipeline_schedule_enabled.setter
    def pipeline_schedule_enabled(self, val: bool):
        self._data['pipeline_schedule_enabled'] = val
        self.save()

    @property
    def pipeline_cron_hours(self) -> list[int]:
        hours = self._data.get('pipeline_cron_hours', [10, 17])
        if not isinstance(hours, list):
            hours = [10, 17]
        return [max(0, min(23, int(h))) for h in hours if isinstance(h, (int, float))]

    @pipeline_cron_hours.setter
    def pipeline_cron_hours(self, val: list[int]):
        self._data['pipeline_cron_hours'] = val
        self.save()

    @property
    def pipeline_cron_minutes(self) -> list[int]:
        minutes = self._data.get('pipeline_cron_minutes', [0, 0])
        if not isinstance(minutes, list):
            minutes = [0, 0]
        return [max(0, min(59, int(m))) for m in minutes if isinstance(m, (int, float))]

    @pipeline_cron_minutes.setter
    def pipeline_cron_minutes(self, val: list[int]):
        self._data['pipeline_cron_minutes'] = val
        self.save()

    # ── AI 全流程定时调度 ──────────────────────────────────

    @property
    def ai_cron_enabled(self) -> bool:
        return self._data.get('ai_cron_enabled', True)

    @ai_cron_enabled.setter
    def ai_cron_enabled(self, val: bool):
        self._data['ai_cron_enabled'] = val
        self.save()

    @property
    def ai_cron_hours(self) -> list[int]:
        hours = self._data.get('ai_cron_hours', [15, 22])
        if not isinstance(hours, list):
            hours = [15, 22]
        return [max(0, min(23, int(h))) for h in hours if isinstance(h, (int, float))]

    @ai_cron_hours.setter
    def ai_cron_hours(self, val: list[int]):
        self._data['ai_cron_hours'] = val
        self.save()

    @property
    def ai_cron_minutes(self) -> list[int]:
        minutes = self._data.get('ai_cron_minutes', [0, 0])
        if not isinstance(minutes, list):
            minutes = [0, 0]
        return [max(0, min(59, int(m))) for m in minutes if isinstance(m, (int, float))]

    @ai_cron_minutes.setter
    def ai_cron_minutes(self, val: list[int]):
        self._data['ai_cron_minutes'] = val
        self.save()

    # ── 翻译 API 配置 ──────────────────────────────────────
    @property
    def translation_enabled(self) -> bool:
        return self._data.get('translation_enabled', False)

    @translation_enabled.setter
    def translation_enabled(self, val: bool):
        self._data['translation_enabled'] = val
        self.save()

    @property
    def translation_base_url(self) -> str:
        return self._data.get('translation_base_url', DEFAULT_CONFIG['translation_base_url'])

    @translation_base_url.setter
    def translation_base_url(self, val: str):
        self._data['translation_base_url'] = val
        self.save()

    @property
    def translation_api_key(self) -> str:
        return self._data.get('translation_api_key', '')

    @translation_api_key.setter
    def translation_api_key(self, val: str):
        self._data['translation_api_key'] = val
        self.save()

    @property
    def translation_model(self) -> str:
        return self._data.get('translation_model', DEFAULT_CONFIG['translation_model'])

    @translation_model.setter
    def translation_model(self, val: str):
        self._data['translation_model'] = val
        self.save()

    @property
    def translation_target_lang(self) -> str:
        return self._data.get('translation_target_lang', 'zh-CN')

    @translation_target_lang.setter
    def translation_target_lang(self, val: str):
        self._data['translation_target_lang'] = val
        self.save()

    # ── 内容缓存路径 ───────────────────────────────────────
    @property
    def content_cache_path(self) -> str:
        val = self._data.get('content_cache_path', '')
        if val:
            return val
        # 默认为 DB 同级的 content/ 目录
        db_dir = os.path.dirname(self.db_path)
        return os.path.join(db_dir, 'content')

    @content_cache_path.setter
    def content_cache_path(self, val: str):
        self._data['content_cache_path'] = val
        self.save()

    # ── 平台热搜采集 ─────────────────────────────────────────
    @property
    def platform_hotlist_enabled(self) -> bool:
        return self._data.get('platform_hotlist_enabled', True)

    @platform_hotlist_enabled.setter
    def platform_hotlist_enabled(self, val: bool):
        self._data['platform_hotlist_enabled'] = val
        self.save()

    @property
    def bilibili_max_pages(self) -> int:
        return self._data.get('bilibili_max_pages', 7)

    @bilibili_max_pages.setter
    def bilibili_max_pages(self, val: int):
        self._data['bilibili_max_pages'] = val
        self.save()

    # ── 境外内容抓取代理 ──────────────────────────────────────
    @property
    def proxy_enabled(self) -> bool:
        return self._data.get('proxy_enabled', False)

    @proxy_enabled.setter
    def proxy_enabled(self, val: bool):
        self._data['proxy_enabled'] = val
        self.save()

    @property
    def proxy_url(self) -> str:
        return self._data.get('proxy_url', '')

    @proxy_url.setter
    def proxy_url(self, val: str):
        self._data['proxy_url'] = val
        self.save()

    def to_dict(self) -> dict:
        # Mask API keys in serialized output
        d = dict(self._data)
        if d.get('openai_api_key'):
            d['openai_api_key'] = '***'
        if d.get('translation_api_key'):
            d['translation_api_key'] = '***'
        if d.get('clean_api_key'):
            d['clean_api_key'] = '***'
        d['pipeline_cron_hours'] = self.pipeline_cron_hours
        d['pipeline_cron_minutes'] = self.pipeline_cron_minutes
        d['ai_cron_hours'] = self.ai_cron_hours
        d['ai_cron_minutes'] = self.ai_cron_minutes
        return d

config = AppConfig()
