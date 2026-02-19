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
        logging.warning("redis package not installed. Falling back to TinyDB")
    except Exception as e:
        logging.warning(f"Could not connect to Redis: {e}. Falling back to TinyDB")

if not _redis_client:
    logging.info("Using TinyDB for anime mapping")

MAPPING_FILE = os.path.join(os.path.dirname(__file__), '../../data/anime-lists/anime-list-full.json')
_loaded = False

def load_mapping():
    """Load anime mapping from file to Redis or TinyDB (run once at startup)"""
    global _loaded
    if _loaded:
        return
    
    try:
        with open(MAPPING_FILE, 'r') as f:
            data = json.load(f)
        
        # Use hash of file content to detect changes
        import hashlib
        file_content = json.dumps(data, sort_keys=True)
        file_hash = hashlib.md5(file_content.encode()).hexdigest()
            
        if _redis_client:
            # Check if Redis has same version
            cached_hash = _redis_client.get('mapping:hash')
            if cached_hash == file_hash:
                logging.info(f"Redis has up-to-date anime mapping (hash: {file_hash[:8]}), skipping load")
            else:
                _load_to_redis(data)
                _redis_client.set('mapping:hash', file_hash)
                logging.info(f"Loaded anime mapping with hash: {file_hash[:8]}")
        else:
            _load_to_tinydb(data)
        
        _loaded = True
    except FileNotFoundError:
        logging.error("anime-list-full.json not found. Run: git submodule update --init")
    except Exception as e:
        logging.error(f"Failed to load anime mapping: {e}")

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
    
    logging.info(f"Loaded {len(data)} anime to Redis with {ttl}s TTL")

def _load_to_tinydb(data):
    """Load data to TinyDB (using existing database)"""
    db.load_anime_mapping(data)
    logging.info(f"Loaded {len(data)} anime to TinyDB")

def get_mal_id_from_kitsu_id(kitsu_id: str) -> Optional[str]:
    """Get MAL ID from Kitsu ID"""
    item = _get_item('kitsu', kitsu_id)
    return str(item.get('mal_id')) if item and item.get('mal_id') else None

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
        return None
    
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
        if _redis_client:
            _redis_client.setex(f"slug:mal:{mal_id}", 86400 * 90, slug)
            _redis_client.setex(f"slug:docchi:{slug}", 86400 * 90, str(mal_id))
        else:
            db.save_slug_from_mal_id(int(mal_id), slug)
    return slug
