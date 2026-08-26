import sqlite3
import asyncio
import logging
import threading
from config import Config

db_lock = threading.Lock()
connection = sqlite3.connect(Config.DATABASE, check_same_thread=False)
connection.row_factory = sqlite3.Row
connection.executescript("""
    CREATE TABLE IF NOT EXISTS anime_mapping (
        mal_id INTEGER,
        kitsu_id INTEGER,
        imdb_id TEXT,
        tvdb_id INTEGER,
        themoviedb_id INTEGER,
        season_tvdb INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_mal ON anime_mapping(mal_id);
    CREATE INDEX IF NOT EXISTS idx_kitsu ON anime_mapping(kitsu_id);
    CREATE INDEX IF NOT EXISTS idx_imdb ON anime_mapping(imdb_id);
    CREATE INDEX IF NOT EXISTS idx_tvdb ON anime_mapping(tvdb_id);
    CREATE TABLE IF NOT EXISTS slug_mapping (
        mal_id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS meta_cache (
        mal_id TEXT PRIMARY KEY,
        meta TEXT,
        timestamp INTEGER
    );
    CREATE TABLE IF NOT EXISTS videos_cache (
        mal_id TEXT PRIMARY KEY,
        videos TEXT,
        timestamp INTEGER
    );
    CREATE TABLE IF NOT EXISTS season_episodes_cache (
        cache_key TEXT PRIMARY KEY,
        episodes TEXT,
        timestamp INTEGER
    );
""")
connection.commit()


class _Row(dict):
    """Dict-like row wrapper to unify SQLite Row and Turso row access."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


# Pre-import libsql_client at module level if Turso is configured
_libsql_client = None
_turso_url = None
_turso_client = None  # Persistent Turso client (reused across requests)
_turso_lock = asyncio.Lock()  # Protects client creation

if Config.TURSO_URL and Config.TURSO_TOKEN:
    try:
        import libsql_client as _libsql_client
        _turso_url = Config.TURSO_URL.replace('libsql://', 'https://')
    except ImportError:
        _libsql_client = None


def _get_turso_client():
    """Get or create a persistent Turso client. Must be called from async context."""
    global _turso_client
    if _turso_client is None or _turso_client.closed:
        _turso_client = _libsql_client.create_client(url=_turso_url, auth_token=Config.TURSO_TOKEN)
    return _turso_client


def _reset_turso_client():
    """Reset the Turso client after persistent failures."""
    global _turso_client
    if _turso_client is not None:
        try:
            asyncio.ensure_future(_turso_client.close())
        except Exception:
            pass
    _turso_client = None


async def execute(sql: str, params=()) -> list:
    """Unified async execute for Turso or SQLite.
    
    Uses a persistent Turso client to avoid opening a new HTTP connection per query.
    Retries up to 3 times on transient errors, resetting the client on failure.
    """
    if _libsql_client and _turso_url:
        last_error = None
        for attempt in range(3):
            try:
                client = _get_turso_client()
                rs = await client.execute(sql, list(params))
                cols = list(rs.columns)
                return [_Row(zip(cols, row)) for row in rs.rows]
            except Exception as e:
                last_error = e
                _reset_turso_client()
                if attempt < 2:
                    wait = 0.5 * (attempt + 1)
                    logging.warning(f"Turso execute failed (attempt {attempt+1}/3): {e}, retrying in {wait}s...")
                    await asyncio.sleep(wait)
        logging.error(f"Turso execute failed after 3 attempts: {last_error}")
        # Don't fallback to local SQLite when Turso is configured
        # (local DB is empty on serverless — fallback would lose data)
        return []
    rows = connection.execute(sql, params).fetchall()
    connection.commit()
    return [_Row(row) for row in rows]
