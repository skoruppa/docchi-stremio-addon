import sqlite3
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
if Config.TURSO_URL and Config.TURSO_TOKEN:
    try:
        import libsql_client as _libsql_client
        _turso_url = Config.TURSO_URL.replace('libsql://', 'https://')
    except ImportError:
        _libsql_client = None


async def execute(sql: str, params=()) -> list:
    """Unified async execute for Turso or SQLite. Returns list of _Row."""
    if _libsql_client and _turso_url:
        try:
            async with _libsql_client.create_client(url=_turso_url, auth_token=Config.TURSO_TOKEN) as client:
                rs = await client.execute(sql, list(params))
                cols = list(rs.columns)
                return [_Row(zip(cols, row)) for row in rs.rows]
        except Exception as e:
            logging.error(f"Turso execute failed, falling back to SQLite: {e}")
    rows = connection.execute(sql, params).fetchall()
    connection.commit()
    return [_Row(row) for row in rows]
