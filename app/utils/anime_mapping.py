import json
import os
import logging
from typing import Optional
from config import Config
from app.db import db
from app.api.docchi import DocchiAPI

_redis_client = None

if Config.USE_REDIS and Config.REDIS_URL:
    try:
        import redis
        _redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)
        logging.info("Using Redis for anime mapping")
    except ImportError:
        logging.warning("redis package not installed. Falling back to SQLite")
    except Exception as e:
        logging.warning(f"Could not connect to Redis: {e}. Falling back to SQLite")

if not _redis_client:
    logging.info("Using SQLite/Turso for anime mapping")

MAPPING_FILE = os.path.join(os.path.dirname(__file__), '../../data/anime-lists/anime-list-full.json')
OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), '../../data/mapping-overrides.json')
_loaded = False
_overrides: dict = {}  # mal_id (str) -> override fields


def _load_overrides():
    """Load manual mapping overrides from JSON file, apply to Redis, and keep in memory.
    
    Tracks per-entry hashes in Redis — only clears meta/videos cache for new or modified entries.
    """
    global _overrides
    try:
        with open(OVERRIDES_FILE, 'r') as f:
            data = json.load(f)
        new_overrides = {k: v for k, v in data.items() if not k.startswith('_')}
        if not new_overrides:
            _overrides = {}
            return

        logging.info(f"Loaded {len(new_overrides)} mapping overrides")

        if _redis_client:
            import hashlib
            changed_mal_ids = []
            ttl = 86400 * 7
            for mal_id, override in new_overrides.items():
                # Detect changed entries
                entry_hash = hashlib.md5(json.dumps(override, sort_keys=True).encode()).hexdigest()
                prev_hash = _redis_client.get(f"override:hash:{mal_id}")
                if prev_hash != entry_hash:
                    changed_mal_ids.append(mal_id)
                    _redis_client.setex(f"override:hash:{mal_id}", ttl, entry_hash)

                # Always apply override to Redis mapping
                existing = _redis_client.get(f"mal:{mal_id}")
                item = json.loads(existing) if existing else {}
                item['mal_id'] = int(mal_id)
                for key in ('kitsu_id', 'tvdb_id'):
                    if key in override:
                        item[key] = override[key]
                if 'imdb_id' in override:
                    item['imdb_id'] = override['imdb_id']
                if 'tmdb_id' in override:
                    item['themoviedb_id'] = override['tmdb_id']
                if 'tvdb_season' in override:
                    if override['tvdb_season'] is not None:
                        item['season'] = {'tvdb': override['tvdb_season']}
                    else:
                        item.pop('season', None)
                _redis_client.setex(f"mal:{mal_id}", ttl, json.dumps(item))
                _redis_client.delete(f"resolved:mal:{mal_id}")

                # Update reverse lookups (tvdb: and imdb:) so get_all_seasons_for_tvdb_id works
                if item.get('tvdb_id'):
                    tvdb_key = f"tvdb:{item['tvdb_id']}"
                    existing_tvdb = _redis_client.get(tvdb_key)
                    tvdb_list = json.loads(existing_tvdb) if existing_tvdb else []
                    if not isinstance(tvdb_list, list):
                        tvdb_list = [tvdb_list]
                    # Remove old entry for this mal_id, add updated
                    tvdb_list = [e for e in tvdb_list if e.get('mal_id') != int(mal_id)]
                    tvdb_list.append(item)
                    tvdb_list.sort(key=lambda x: int(x.get('season', {}).get('tvdb', 0) if isinstance(x.get('season'), dict) else 0))
                    _redis_client.setex(tvdb_key, ttl, json.dumps(tvdb_list))

            # Clear meta/videos cache only for changed entries
            if changed_mal_ids:
                logging.info(f"Override changes detected for {len(changed_mal_ids)} entries, clearing cache: {changed_mal_ids}")
                import sqlite3
                from config import Config
                try:
                    conn = sqlite3.connect(Config.DATABASE)
                    placeholders = ','.join('?' * len(changed_mal_ids))
                    conn.execute(f"DELETE FROM meta_cache WHERE mal_id IN ({placeholders})", changed_mal_ids)
                    conn.execute(f"DELETE FROM videos_cache WHERE mal_id IN ({placeholders})", changed_mal_ids)
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logging.warning(f"Failed to clear cache for changed overrides: {e}")

        _overrides = new_overrides
    except FileNotFoundError:
        _overrides = {}
    except Exception as e:
        logging.warning(f"Failed to load mapping overrides: {e}")
        _overrides = {}

def load_mapping():
    """Load anime mapping from file to Redis or TinyDB (run once at startup)"""
    global _loaded
    _load_overrides()  # Always reload overrides
    if _loaded:
        return
    
    try:
        import hashlib
        import os as _os
        MAPPING_SCHEMA_VERSION = "2"  # bump when _load_to_redis changes structure
        
        # Use file size + mtime as fast hash proxy (avoids reading 15MB into RAM)
        stat = _os.stat(MAPPING_FILE)
        file_hash = hashlib.md5(f"{stat.st_size}:{stat.st_mtime}:{MAPPING_SCHEMA_VERSION}".encode()).hexdigest()
        
        if _redis_client:
            # Check if Redis has same version — skip expensive JSON parse if so
            cached_hash = _redis_client.get('mapping:hash')
            if cached_hash == file_hash:
                logging.info(f"Redis has up-to-date anime mapping (hash: {file_hash[:8]}), skipping load")
                _loaded = True
                return
            
            # Hash mismatch — need to parse and reload
            with open(MAPPING_FILE, 'r') as f:
                data = json.load(f)
            _load_to_redis(data)
            del data  # Free parsed data after loading to Redis
            _redis_client.set('mapping:hash', file_hash)
            logging.info(f"Loaded anime mapping with hash: {file_hash[:8]}")
        else:
            with open(MAPPING_FILE, 'r') as f:
                data = json.load(f)
            _load_to_sqlite(data)
            del data
        _loaded = True
    except FileNotFoundError:
        logging.error("anime-list-full.json not found. Run: git submodule update --init")
    except Exception as e:
        logging.error(f"Failed to load anime mapping: {e}")
        _loaded = True  # Don't retry on every request if Redis is full

def _load_to_redis(data):
    """Load only necessary fields to Redis with TTL"""
    pipe = _redis_client.pipeline()
    ttl = 86400 * 7  # 7 days
    
    for item in data:
        mini = {}
        if item.get('mal_id'):
            mini['mal_id'] = item['mal_id']
        if item.get('kitsu_id'):
            mini['kitsu_id'] = item['kitsu_id']
        if item.get('imdb_id'):
            mini['imdb_id'] = item['imdb_id']
        if item.get('tvdb_id'):
            mini['tvdb_id'] = item['tvdb_id']
        tmdb = item.get('themoviedb_id')
        if tmdb:
            mini['themoviedb_id'] = next(iter(tmdb.values())) if isinstance(tmdb, dict) else tmdb
        if item.get('season', {}).get('tvdb'):
            mini['season'] = {'tvdb': item['season']['tvdb']}

        item_json = json.dumps(mini)
        if mini.get('mal_id'):
            pipe.setex(f"mal:{mini['mal_id']}", ttl, item_json)
        if mini.get('kitsu_id'):
            pipe.setex(f"kitsu:{mini['kitsu_id']}", ttl, item_json)
    
    pipe.execute()

    imdb_map = {}
    for item in data:
        imdb_id = item.get('imdb_id')
        if not imdb_id:
            continue
            
        mini = {}
        if item.get('mal_id'):
            mini['mal_id'] = item['mal_id']
        if item.get('kitsu_id'):
            mini['kitsu_id'] = item['kitsu_id']
        if item.get('imdb_id'):
            mini['imdb_id'] = item['imdb_id']
        if item.get('tvdb_id'):
            mini['tvdb_id'] = item['tvdb_id']
        tmdb = item.get('themoviedb_id')
        if tmdb:
            mini['themoviedb_id'] = next(iter(tmdb.values())) if isinstance(tmdb, dict) else tmdb
        if item.get('season', {}).get('tvdb'):
            mini['season'] = {'tvdb': item['season']['tvdb']}
            
        ids = [imdb_id] if not isinstance(imdb_id, list) else imdb_id
        for iid in ids:
            if iid not in imdb_map:
                imdb_map[iid] = []
            imdb_map[iid].append(mini)
    
    pipe = _redis_client.pipeline()
    for iid, items in imdb_map.items():
        pipe.setex(f"imdb:{iid}", ttl, json.dumps(items))
    pipe.execute()

    # Build TVDB map (tvdb_id -> list of seasons)
    tvdb_map = {}
    for item in data:
        tvdb_id = item.get('tvdb_id')
        if not tvdb_id:
            continue
        mini = {}
        if item.get('mal_id'):
            mini['mal_id'] = item['mal_id']
        if item.get('kitsu_id'):
            mini['kitsu_id'] = item['kitsu_id']
        if item.get('imdb_id'):
            mini['imdb_id'] = item['imdb_id']
        if item.get('tvdb_id'):
            mini['tvdb_id'] = item['tvdb_id']
        tmdb = item.get('themoviedb_id')
        if tmdb:
            mini['themoviedb_id'] = next(iter(tmdb.values())) if isinstance(tmdb, dict) else tmdb
        if item.get('season', {}).get('tvdb'):
            mini['season'] = {'tvdb': item['season']['tvdb']}
        tvdb_key = str(tvdb_id)
        if tvdb_key not in tvdb_map:
            tvdb_map[tvdb_key] = []
        tvdb_map[tvdb_key].append(mini)

    pipe = _redis_client.pipeline()
    for tid, items in tvdb_map.items():
        pipe.setex(f"tvdb:{tid}", ttl, json.dumps(items))
    pipe.execute()
    
    logging.info(f"Loaded {len(data)} anime to Redis with {ttl}s TTL")

def _load_to_sqlite(data):
    """Load data to SQLite (using existing database)"""
    db.load_anime_mapping(data)
    logging.info(f"Loaded {len(data)} anime to SQLite")

def get_mal_id_from_kitsu_id(kitsu_id: str) -> Optional[str]:
    """Get MAL ID from Kitsu ID. Falls back to Kitsu Mappings API if not in local DB."""
    item = _get_item('kitsu', kitsu_id)
    if item and item.get('mal_id'):
        return str(item['mal_id'])

    # Fallback: query Kitsu API mappings endpoint
    mal_id = _kitsu_api_fallback(kitsu_id)
    if mal_id:
        # Cache the result for future lookups
        _cache_kitsu_mapping(kitsu_id, mal_id)
    return mal_id


def _kitsu_api_fallback(kitsu_id: str) -> Optional[str]:
    """Query Kitsu Mappings API to resolve kitsu_id -> MAL ID."""
    import requests
    try:
        url = (
            f"https://kitsu.io/api/edge/anime/{kitsu_id}/mappings"
            f"?filter[externalSite]=myanimelist/anime"
        )
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        mappings = data.get("data", [])
        if mappings:
            return mappings[0].get("attributes", {}).get("externalId")
    except Exception as e:
        logging.warning(f"Kitsu API fallback failed for kitsu:{kitsu_id}: {e}")
    return None


def _cache_kitsu_mapping(kitsu_id: str, mal_id: str):
    """Cache a kitsu->mal mapping discovered via API fallback."""
    mini = {'kitsu_id': int(kitsu_id), 'mal_id': int(mal_id)}
    if _redis_client:
        import json as _json
        ttl = 86400 * 7
        _redis_client.setex(f"kitsu:{kitsu_id}", ttl, _json.dumps(mini))
    # For SQLite, we don't persist API-discovered mappings to avoid stale data

def get_kitsu_from_mal_id(mal_id: str) -> Optional[str]:
    """Get Kitsu ID from MAL ID"""
    item = _get_item('mal', mal_id)
    return str(item.get('kitsu_id')) if item and item.get('kitsu_id') else None

def get_mal_id_from_imdb_id(imdb_id: str, season: int = None) -> Optional[str]:
    """Get MAL ID from IMDB ID and optional season number"""
    items = _get_imdb_items(imdb_id)
    if not items:
        return None

    if season is not None:
        for item in items:
            tvdb_season = item.get('season', {}).get('tvdb')
            if tvdb_season and int(tvdb_season) == int(season):
                return str(item.get('mal_id')) if item.get('mal_id') else None

        # For season 1 (or any season with no direct match): prefer entries without season info
        # These are typically the main/base series (e.g. Dragon Ball, One Piece)
        # Entries with tvdb_season=0 are specials/extras, skip them
        no_season_entries = [
            it for it in items
            if not it.get('season', {}).get('tvdb')
        ]
        if no_season_entries:
            return str(no_season_entries[0].get('mal_id')) if no_season_entries[0].get('mal_id') else None

        # Fallback: if only one entry exists (regardless of season info), use it
        if len(items) == 1:
            return str(items[0].get('mal_id')) if items[0].get('mal_id') else None
        return None
    
    # No season specified: prefer entry with season=1, then no-season entry, then first
    for item in items:
        tvdb_season = item.get('season', {}).get('tvdb')
        if tvdb_season and int(tvdb_season) == 1:
            return str(item.get('mal_id')) if item.get('mal_id') else None
    # Prefer entries without season info (main series)
    no_season_entries = [
        it for it in items
        if not it.get('season', {}).get('tvdb')
    ]
    if no_season_entries:
        return str(no_season_entries[0].get('mal_id')) if no_season_entries[0].get('mal_id') else None
    for item in items:
        if item.get('season', {}).get('tvdb'):
            return str(item.get('mal_id')) if item.get('mal_id') else None
    return str(items[0].get('mal_id')) if items[0].get('mal_id') else None

async def get_slug_from_imdb_id(imdb_id: str, season: int = None) -> Optional[str]:
    """Get Docchi slug from IMDB ID and optional season (IMDB -> MAL -> slug)"""
    mal_id = get_mal_id_from_imdb_id(imdb_id, season)
    if mal_id:
        return await get_slug_from_mal_id(mal_id)
    return None

def get_imdb_id_from_mal_id(mal_id: str) -> Optional[str]:
    """Get IMDB ID from MAL ID (returns first if multiple)"""
    item = _get_item('mal', mal_id)
    if item:
        imdb_id = item.get('imdb_id')
        if imdb_id:
            return str(imdb_id[0]) if isinstance(imdb_id, list) else str(imdb_id)
    return None


def get_ids_from_mal_id(mal_id: str) -> dict:
    """Get kitsu_id, imdb_id, tvdb_id, themoviedb_id for a given MAL ID.
    Checks overrides first, then main mapping, then resolved cache."""
    # Check manual overrides first
    override = _overrides.get(str(mal_id))

    item = _get_item('mal', mal_id) or {}
    imdb_id = item.get('imdb_id')
    result = {
        'kitsu_id': str(item['kitsu_id']) if item.get('kitsu_id') else None,
        'imdb_id': (imdb_id[0] if isinstance(imdb_id, list) else imdb_id) or None,
        'tvdb_id': item.get('tvdb_id'),
        'tmdb_id': item.get('themoviedb_id'),
        'tvdb_season': item.get('season', {}).get('tvdb') if item.get('season') else None,
    }

    # Apply overrides (null values clear the field)
    if override:
        for key in ('imdb_id', 'tvdb_id', 'tmdb_id', 'tvdb_season'):
            if key in override:
                result[key] = override[key]
        if 'kitsu_id' in override:
            result['kitsu_id'] = str(override['kitsu_id']) if override['kitsu_id'] else None

    # If main mapping lacks tvdb_id, check resolved cache (Simkl/AniList fallback)
    # But don't override fields that were explicitly cleared by manual overrides
    if not result['tvdb_id'] and _redis_client and not (override and 'tvdb_id' in override):
        resolved_data = _redis_client.get(f"resolved:mal:{mal_id}")
        if resolved_data:
            resolved = json.loads(resolved_data)
            result['tvdb_id'] = result['tvdb_id'] or resolved.get('tvdb_id')
            if not (override and 'imdb_id' in override):
                result['imdb_id'] = result['imdb_id'] or resolved.get('imdb_id')
            if not (override and 'tmdb_id' in override):
                result['tmdb_id'] = result['tmdb_id'] or resolved.get('themoviedb_id')
            if not (override and 'tvdb_season' in override):
                result['tvdb_season'] = result['tvdb_season'] or (resolved.get('season', {}).get('tvdb') if resolved.get('season') else None)
    return result

def _get_imdb_items(imdb_id: str) -> list:
    """Get list of items for IMDB ID (can have multiple seasons)"""
    if _redis_client:
        data = _redis_client.get(f"imdb:{imdb_id}")
        if data:
            items = json.loads(data)
            return items if isinstance(items, list) else [items]
    else:
        return db.get_anime_by_imdb_id(imdb_id)
    return []


def get_all_seasons_for_tvdb_id(tvdb_id: int) -> list[dict]:
    """Get all MAL entries that share the same TVDB ID (multi-season series).
    
    Returns list of dicts with keys: mal_id, kitsu_id, tvdb_season, sorted by tvdb_season.
    """
    if _redis_client:
        data = _redis_client.get(f"tvdb:{tvdb_id}")
        if data:
            items = json.loads(data)
            items = items if isinstance(items, list) else [items]
            return sorted(items, key=lambda x: int(x.get('season', {}).get('tvdb', 0) if isinstance(x.get('season'), dict) else 0))
    else:
        items = db.get_anime_by_tvdb_id(int(tvdb_id))
        if items:
            return sorted(items, key=lambda x: int(x.get('season', {}).get('tvdb', 0) if isinstance(x.get('season'), dict) else 0))
    return []

def _get_item(key_type: str, key_value: str) -> Optional[dict]:
    """Internal helper to get item from Redis or TinyDB"""
    if _redis_client:
        data = _redis_client.get(f"{key_type}:{key_value}")
        if data:
            return json.loads(data)
    else:
        if key_type == 'mal':
            return db.get_anime_by_mal_id(int(key_value))
        elif key_type == 'kitsu':
            return db.get_anime_by_kitsu_id(int(key_value))
    return None

async def get_mal_id_from_slug(slug: str) -> Optional[int]:
    """Get MAL ID from Docchi slug (Redis or TinyDB, then Docchi API)"""
    if _redis_client:
        mal_id = _redis_client.get(f"slug:docchi:{slug}")
        if mal_id:
            return int(mal_id)
    else:
        _, mal_id = db.get_mal_id_from_slug(slug)
        if mal_id:
            return mal_id

    try:
        from app.routes import docchi_client
        details = await docchi_client.get_anime_details(slug)
        mal_id = details and details.get('mal_id')
    except Exception:
        mal_id = None
    if mal_id:
        save_mal_slug_mapping(mal_id, slug)
    return int(mal_id) if mal_id else None

def save_mal_slug_mapping(mal_id, slug: str):
    """Save mal_id <-> slug mapping to Redis or TinyDB."""
    if not mal_id or not slug:
        return
    mal_id = int(mal_id)
    if _redis_client:
        _redis_client.setex(f"slug:mal:{mal_id}", 86400 * 90, slug)
        _redis_client.setex(f"slug:docchi:{slug}", 86400 * 90, str(mal_id))
    else:
        db.save_slug_from_mal_id(mal_id, slug)


async def get_slug_from_mal_id(mal_id: str) -> Optional[str]:
    """Get Docchi slug from MAL ID (Redis or TinyDB, then Docchi API)"""
    if _redis_client:
        slug = _redis_client.get(f"slug:mal:{mal_id}")
        if slug:
            return slug
    else:
        exists, slug = db.get_slug_from_mal_id(int(mal_id))
        if exists and slug:
            return slug

    slug = None
    try:
        from app.routes import docchi_client
        slug = await docchi_client.get_slug_from_mal_id(mal_id)
    except Exception:
        pass
    if slug:
        save_mal_slug_mapping(mal_id, slug)
    return slug
