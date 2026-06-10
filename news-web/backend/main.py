import os, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from config import config
from db.migrations import ensure_schema
from scheduler import start_scheduler, stop_scheduler, trigger_pipeline_manual, get_pipeline_status

# ── Logging ──────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'news-web.log'), encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.db_path:
        ensure_schema(config.db_path)
    if not os.environ.get('NEWS_WEB_TESTING'):
        start_scheduler()                      # Start daily cron jobs
    yield
    if not os.environ.get('NEWS_WEB_TESTING'):
        stop_scheduler()                       # Clean shutdown

app = FastAPI(title="News Aggregation Web", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global exception handler ─────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An unexpected error occurred"},
    )

@app.get("/api/health")
def health():
    return {"status": "ok", "db_path": config.db_path or "(not configured)"}

@app.post("/api/pipeline/run")
async def manual_pipeline_run():
    """Manually trigger the news pipeline."""
    await trigger_pipeline_manual()
    return {"status": "pipeline_started"}

@app.get("/api/pipeline/status")
def pipeline_status():
    """Get current pipeline run status."""
    return get_pipeline_status()

# ── Register API routers ──────────────────────────────────
from api.settings import router as settings_router
from api.stats import router as stats_router
from api.articles import router as articles_router
from api.events import router as events_router
from api.chains import router as chains_router
from api.relations import router as relations_router
from api.auth import router as auth_router

app.include_router(settings_router)
app.include_router(stats_router)
app.include_router(articles_router)
app.include_router(events_router)
app.include_router(chains_router)
app.include_router(relations_router)
app.include_router(auth_router)

# ── Production static mount (must be last) ───────────────
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frontend', 'dist')
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    logger.info(f"Mounted frontend static files from {FRONTEND_DIST}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
