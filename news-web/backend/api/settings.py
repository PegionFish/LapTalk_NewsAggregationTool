from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import config

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
    return config.to_dict()
