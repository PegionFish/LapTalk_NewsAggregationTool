from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/browser", tags=["browser"])


class FingerprintData(BaseModel):
    userAgent: str = ''
    platform: str = ''
    language: str = ''
    languages: list[str] = ['zh-CN', 'zh', 'en']
    deviceMemory: Optional[float] = None
    hardwareConcurrency: int = 8
    screenWidth: int = 1920
    screenHeight: int = 1080
    colorDepth: int = 24
    pixelRatio: float = 1
    timezone: str = 'Asia/Shanghai'
    cookiesEnabled: bool = True


@router.post("/fingerprint")
def set_browser_fingerprint(fp: FingerprintData):
    """接收前端浏览器真实指纹，供服务端 Playwright 使用。"""
    from fingerprint_store import save_fingerprint
    save_fingerprint(fp.model_dump())
    return {"ok": True}


@router.get("/fingerprint")
def get_browser_fingerprint():
    """查询当前存储的浏览器指纹。"""
    from fingerprint_store import load_fingerprint
    fp = load_fingerprint()
    return {"ok": True, "fingerprint": fp}


@router.post("/retry-playwright/{article_id}")
def retry_playwright_capture(article_id: int):
    """用户在浏览器通过验证后，重试 Playwright 捕获。"""
    from config import config
    import sqlite3

    conn = sqlite3.connect(config.db_path)
    row = conn.execute(
        "SELECT id, url FROM news_articles WHERE id=?", (article_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, "article_not_found")

    aid, url = row
    if not url or not url.startswith('http'):
        raise HTTPException(400, "invalid_url")

    from pipeline.browser_capture import retry_playwright
    result = retry_playwright(aid, url)

    if result.get('ok'):
        return {"ok": True, "source": result['source']}
    elif 'challenge' in result:
        return {
            "ok": False,
            "error": result['error'],
            "challenge": True,
        }
    else:
        return {"ok": False, "error": result.get('error', 'unknown')}
