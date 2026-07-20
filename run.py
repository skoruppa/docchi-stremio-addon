import logging
import sys
import uuid
from contextvars import ContextVar

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse

from app.routes.catalog import catalog_router
from app.routes.manifest import manifest_router
from app.routes.meta import meta_router
from app.routes.stream import stream_router
from app.routes.translate import translate_router
from app.utils.anime_mapping import load_mapping
from config import Config
from version import __version__

# Per-request ID via contextvars
request_id_var: ContextVar[str] = ContextVar('request_id', default='-')


class RequestIdFilter(logging.Filter):
    """Inject request_id into every log record."""
    def filter(self, record):
        record.request_id = request_id_var.get('-')
        return True


# Configure logging at module level
logging.basicConfig(
    format='%(asctime)s %(levelname)s [%(request_id)s] %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
    force=True
)
# Add filter to root logger so all loggers inherit it
for handler in logging.root.handlers:
    handler.addFilter(RequestIdFilter())

templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    load_mapping()
    # Ensure season_episodes_cache table exists (Turso migration)
    from app.db import execute
    await execute("""
        CREATE TABLE IF NOT EXISTS season_episodes_cache (
            cache_key TEXT PRIMARY KEY,
            episodes TEXT,
            timestamp INTEGER
        )
    """)
    logging.info(f"Starting Docchi Stremio Addon v{__version__}")
    yield
    # Shutdown (nothing needed)


app = FastAPI(lifespan=lifespan)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Generate short request ID (6 chars) and bind to context
    rid = uuid.uuid4().hex[:6]
    request_id_var.set(rid)
    response = await call_next(request)
    if not request.url.path.startswith('/static') and request.url.path != '/favicon.ico':
        logging.info(f"{request.method} {request.url.path} -> {response.status_code}")
    return response


# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register routers (normal)
app.include_router(manifest_router)
app.include_router(catalog_router)
app.include_router(meta_router)
app.include_router(stream_router)
app.include_router(translate_router)

# Register routers with VIP prefix
app.include_router(manifest_router, prefix=f"/{Config.VIP_PATH}")
app.include_router(catalog_router, prefix=f"/{Config.VIP_PATH}")
app.include_router(meta_router, prefix=f"/{Config.VIP_PATH}")
app.include_router(stream_router, prefix=f"/{Config.VIP_PATH}")


# Template routes
@app.get('/')
@app.get('/configure')
async def index(request: Request):
    """Render the index page"""
    manifest_url = f'{Config.PROTOCOL}://{Config.REDIRECT_URL}/manifest.json'
    manifest_magnet = f'stremio://{Config.REDIRECT_URL}/manifest.json'
    return templates.TemplateResponse(request, "index.html", {
        "logged_in": True,
        "manifest_url": manifest_url,
        "manifest_magnet": manifest_magnet,
        "version": __version__,
    })


@app.get(f'/{Config.VIP_PATH}')
@app.get(f'/{Config.VIP_PATH}/configure')
async def index_vip(request: Request):
    """Render the VIP index page"""
    manifest_url = f'{Config.PROTOCOL}://{Config.REDIRECT_URL}/{Config.VIP_PATH}/manifest.json'
    manifest_magnet = f'stremio://{Config.REDIRECT_URL}/{Config.VIP_PATH}/manifest.json'
    return templates.TemplateResponse(request, "index.html", {
        "logged_in": True,
        "manifest_url": manifest_url,
        "manifest_magnet": manifest_magnet,
        "version": __version__,
    })


@app.get('/favicon.ico')
async def favicon():
    """Render the favicon for the app"""
    return FileResponse("static/favicon.ico")


if __name__ == '__main__':
    import sys as _sys
    if '--clear-cache' in _sys.argv:
        import asyncio
        from app.utils.anime_mapping import _redis_client
        if _redis_client:
            _redis_client.flushdb()
            print("Redis cache cleared")
        from app.db import execute, connection
        if Config.TURSO_URL and Config.TURSO_TOKEN:
            asyncio.run(execute("DELETE FROM meta_cache"))
            print("Turso meta cache cleared")
        else:
            connection.execute("DELETE FROM meta_cache")
            connection.commit()
            print("SQLite meta cache cleared")
        _sys.exit(0)

    import uvicorn
    logging.info(f"Starting Docchi Stremio Addon v{__version__} on http://0.0.0.0:5000")
    uvicorn.run(app, host='0.0.0.0', port=5000, access_log=False)
