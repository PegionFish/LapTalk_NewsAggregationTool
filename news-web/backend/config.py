import json, os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

DEFAULT_CONFIG = {
    'db_path': '',
    'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'openai_base_url': 'https://api.openai.com/v1',
    'openai_api_key': '',
    'openai_model': 'gpt-4o-mini',
    'pipeline_schedule_enabled': True,
    # 翻译 API — 独立配置，默认指向硅基流动 DeepSeek V3.2
    'translation_enabled': False,
    'translation_base_url': 'https://api.siliconflow.cn/v1',
    'translation_api_key': '',
    'translation_model': 'deepseek-ai/DeepSeek-V3-0324',
    'translation_target_lang': 'zh-CN',
    # 内容缓存目录 — 默认为 DB 同级的 content/ 目录
    'content_cache_path': '',
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
    def pipeline_schedule_enabled(self) -> bool:
        return self._data.get('pipeline_schedule_enabled', True)

    @pipeline_schedule_enabled.setter
    def pipeline_schedule_enabled(self, val: bool):
        self._data['pipeline_schedule_enabled'] = val
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

    def to_dict(self) -> dict:
        # Mask API keys in serialized output
        d = dict(self._data)
        if d.get('openai_api_key'):
            d['openai_api_key'] = '***'
        if d.get('translation_api_key'):
            d['translation_api_key'] = '***'
        return d

config = AppConfig()
