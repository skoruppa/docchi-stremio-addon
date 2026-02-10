import asyncio
import urllib.parse
import aiohttp
from flask import Blueprint, abort
from .manifest import MANIFEST


from app.routes import docchi_client, mapping
from app.utils.stream_utils import respond_with
from app.db.db import get_slug_from_mal_id, save_slug_from_mal_id
from app.utils.player_utils import detect_player, get_player_handler


from config import Config

from app.utils.meta_cache import fetch_and_cache_meta

stream_bp = Blueprint('stream', __name__)
PROXIFY_STREAMS = Config.PROXIFY_STREAMS


async def process_player(session, player, is_vip=False):
    player_hosting = player['player_hosting'].lower()
    detected_player = detect_player(player)
    
    if detected_player != 'default' and detected_player != player_hosting:
        player_hosting = detected_player
    
    # Early return if no handler available
    handler = get_player_handler(player_hosting)
    if not handler:
        return None
    
    stream = {
        'url': None,
        'quality': None,
        'player_hosting': player_hosting,
        'translator_title': player['translator_title'],
        'headers': None
    }
    headers = None
    url = None
    quality = None
    inverted = False

    try:
        url, quality, headers = await handler(session, player['player'], is_vip=is_vip)
        
        if player_hosting == 'vk' and player.get('isInverted'):
            inverted = True
    except Exception as e:
        pass
        
    stream.update({'url': url, 'quality': quality, 'headers': headers, 'inverted': inverted})
    return stream


def build_filename(anime_name, episode_num, content_id, quality, translator_norm):
    """Build filename for stream."""
    if anime_name:
        name_norm = anime_name.replace(' ', '_').replace(':', '').replace('/', '')
        if episode_num:
            return f"{name_norm}.e{episode_num.zfill(2)}.{quality}-{translator_norm}.docc"
        return f"{name_norm}.{quality}-{translator_norm}.docc"
    
    # Fallback to content_id
    parts = content_id.split(':')
    content_base = f"{parts[0]}:{parts[1]}"
    if episode_num:
        return f"{content_base}.e{episode_num.zfill(2)}.{quality}-{translator_norm}.docc"
    return f"{content_base}.{quality}-{translator_norm}.docc"


def build_binge_group(anime_name, content_id, quality, translator_norm):
    """Build bingeGroup identifier (same as filename but without episode number)."""
    if anime_name:
        name_norm = anime_name.replace(' ', '_').replace(':', '').replace('/', '')
        return f"{name_norm}.{quality}-{translator_norm}.docc"
    
    # Fallback to content_id
    parts = content_id.split(':')
    content_base = f"{parts[0]}:{parts[1]}"
    return f"{content_base}.{quality}-{translator_norm}.docc"


async def process_players(players, content_id=None, content_type='series', is_vip=False):
    streams = {'streams': []}
    
    # Get anime name from meta
    anime_name = None
    episode_num = None
    if content_id:
        meta, _ = await fetch_and_cache_meta(content_id, is_vip)
        anime_name = meta.get('name') if meta else None
        
        # Extract episode number from content_id
        parts = content_id.split(':')
        if len(parts) > 2:
            episode_num = parts[-1]  # Last part is always episode
    
    timeout = aiohttp.ClientTimeout(total=8, connect=3)
    connector = aiohttp.TCPConnector(limit=15, limit_per_host=5, ttl_dns_cache=300, verify_ssl=False)
    
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks = [process_player(session, player, is_vip) for player in players]

        for task in asyncio.as_completed(tasks):
            stream = await task
            if stream:
                if stream['url']:
                    translator = stream['translator_title'] or 'unknown'
                    quality = stream['quality'] or 'unknown'
                    player = stream['player_hosting']
                    is_ai = translator.lower() == 'ai'
                    
                    # Build filename and bingeGroup
                    translator_norm = translator.replace(' ', '_').replace('.','_')
                    filename = build_filename(anime_name, episode_num, content_id, quality, translator_norm)
                    binge_group = build_binge_group(anime_name, content_id, quality, translator_norm)
                    
                    # Build description
                    translator_flag = f"🇵🇱 {'⚠️ ' if is_ai else ''}{translator}"
                    description = f"{translator_flag}\n🔗 {player}"
                    if stream['inverted']:
                        description += "\n⚠️ Inverted"
                    
                    # Build stream data
                    priority = sort_priority(stream)
                    
                    stream_data = {
                        'name': quality,
                        'description': description,
                        'url': stream['url'],
                        'behaviorHints': {
                            'filename': filename,
                            'bingeGroup': binge_group
                        },
                        '_priority': priority  
                    }
                    
                    # Add behavior hints
                    if player == 'uqload' and PROXIFY_STREAMS:
                        stream_data['behaviorHints']['notWebReady'] = True
                    if stream.get('headers'):
                        stream_data['behaviorHints'].update({
                            'proxyHeaders': stream['headers'],
                            'notWebReady': True
                        })
                    
                    streams['streams'].append(stream_data)
    
    # Sort by priority and remove internal field
    streams['streams'] = sorted(streams['streams'], key=lambda d: d['_priority'])
    for stream in streams['streams']:
        stream.pop('_priority', None)
    return streams


def sort_priority(stream):
    if 'lycoris' in stream['player_hosting']:
        return 0
    elif stream['player_hosting'] == 'rumble':
        return 1
    elif stream['player_hosting'] == 'gdrive':
        return 2
    elif stream['player_hosting'] == 'cda':
        return 3
    elif stream['player_hosting'] == 'uqload':
        return 4
    elif stream['player_hosting'] == 'streamtape':
        return 5
    elif stream['translator_title'].lower() == 'ai':
        return 9
    return 3


@stream_bp.route('/stream/<content_type>/<content_id>.json')
async def addon_stream(content_type: str, content_id: str):
    """
    Provide url streams for web players
    :param content_type: The type of content
    :param content_id: The id of the content
    :return: JSON response
    """
    from flask import request
    is_vip = Config.VIP_PATH in request.path
    
    content_id = urllib.parse.unquote(content_id)
    parts = content_id.split(":")

    if content_type not in MANIFEST['types']:
        abort(404)

    prefix = parts[0]
    season = None
    episode = '1'

    # Handle different ID formats
    if prefix.startswith('tt') and is_vip:
        if len(parts) == 1:
            episode = '1'
        elif len(parts) == 3:
            season = int(parts[1])
            episode = int(parts[2])

        prefix_id = mapping.get_mal_id_from_imdb_id(prefix, season)
        if prefix_id:
            prefix = 'mal'
        else:
            return respond_with({'streams': []}, 2592000, 2592000)
    elif prefix == 'kitsu':
        prefix_id = parts[1]
        prefix_id = mapping.get_mal_id_from_kitsu_id(prefix_id)
        if prefix_id:
            prefix = 'mal'
            episode = parts[2] if len(parts) > 2 else '1'
        else:
            return respond_with({'streams': []})

    else:
        prefix_id = parts[1]
        episode = parts[2] if len(parts) > 2 else '1'

    if prefix != 'mal':
        return respond_with({'streams': []}, 2592000, 2592000)

    exists, slug = get_slug_from_mal_id(prefix_id)
    if not exists:
        slug = await docchi_client.get_slug_from_mal_id(prefix_id)
        save_slug_from_mal_id(prefix_id, slug)

    players = await docchi_client.get_episode_players(slug, episode)
    if players:
        # Remove duplicates based on 'player' field
        seen = set()
        unique_players = []
        for player in players:
            player_url = player.get('player')
            if player_url and player_url not in seen:
                seen.add(player_url)
                unique_players.append(player)
        
        streams = await process_players(unique_players, content_id, content_type, is_vip)
        return respond_with(streams, 600, 300)
    return respond_with({'streams': []})
