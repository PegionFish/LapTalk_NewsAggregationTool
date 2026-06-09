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
    if body.openai_api_key is not None:
        config.openai_api_key = body.openai_api_key
    if body.openai_model is not None:
        config.openai_model = body.openai_model
    if body.pipeline_schedule_enabled is not None:
        config.pipeline_schedule_enabled = body.pipeline_schedule_enabled
    return config.to_dict()
