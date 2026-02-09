import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """
    Configuration class
    """
    FLASK_HOST = os.getenv('FLASK_RUN_HOST', "localhost")
    FLASK_PORT = os.getenv('FLASK_RUN_PORT', "5000")
    CACHE_TYPE = 'SimpleCache'
    CACHE_DEFAULT_TIMEOUT = 600
    PROXIFY_STREAMS = os.getenv('PROXIFY_STREAMS', True)  # proxify needed streams
    STREAM_PROXY_URL = os.getenv('STREAM_PROXY_URL', "")  # MediaFlow Proxy
    STREAM_PROXY_PASSWORD = os.getenv('STREAM_PROXY_PASSWORD', "")  # MediaFlowProxy API_PASSWORD
    VIP_PATH = os.getenv('VIP_PATH', 'vip')  # Secret path for VIP users with proxy access
    FORCE_VIP_PLAYERS = os.getenv('FORCE_VIP_PLAYERS', False)  # Make VIP-only players available for all users
    KITSU_STREMIO_API_URL = os.getenv('KITSU_STREMIO_API_URL', "https://anime-kitsu.strem.fun/meta")
    MAL_CLIENT_ID = os.getenv('MAL_CLIENT_ID', '')  # MyAnimeList API Client ID

    DEBUG = os.getenv('FLASK_DEBUG', False)
    DATABASE = "/tmp/database.json"
    
    # Redis for anime mapping
    USE_REDIS = os.getenv('USE_REDIS', False)
    REDIS_URL = os.getenv('REDIS_URL', '')

    # Env dependent configs
    if DEBUG in ["1", True, "True"]:  # Local development
        PROTOCOL = "http"
        REDIRECT_URL = f"{FLASK_HOST}:{FLASK_PORT}"
    else:  # Production environment
        PROTOCOL = "https"
        REDIRECT_URL = f"{FLASK_HOST}"