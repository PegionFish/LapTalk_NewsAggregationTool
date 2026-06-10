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
        return self._data.get('db_path', '')

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

    def to_dict(self) -> dict:
        # Mask API key in serialized output
        d = dict(self._data)
        if d.get('openai_api_key'):
            d['openai_api_key'] = '***'
        return d

config = AppConfig()
