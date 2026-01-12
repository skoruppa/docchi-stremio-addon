import asyncio
import urllib.parse
import aiohttp
from flask import Blueprint, abort
from .manifest import MANIFEST


from app.routes import MAL_ID_PREFIX, docchi_client, kitsu_client
from app.utils.stream_utils import respond_with
from app.db.db import get_slug_from_mal_id, save_slug_from_mal_id
from app.utils.player_utils import detect_player_from_url, get_player_handler


from config import Config

stream_bp = Blueprint('stream', __name__)
PROXIFY_STREAMS = Config.PROXIFY_STREAMS


async def process_player(session, player, client_ip=None):
    player_hosting = player['player_hosting'].lower()
    detected_player = detect_player_from_url(player['player'])
    
    if detected_player != 'default' and detected_player != player_hosting:
        player_hosting = detected_player
    
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
        # Get handler function for the player
        handler = get_player_handler(player_hosting)
        
        if handler:
            # Call the handler with client_ip if it's dood player
            if player_hosting in ['dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood']:
                url, quality, headers = await handler(session, player['player'], client_ip)
            else:
                url, quality, headers = await handler(session, player['player'])
            
            # Special handling for VK inverted
            if player_hosting == 'vk' and player.get('isInverted'):
                inverted = True
    except Exception as e:
        # Silently ignore player errors - just return None values
        pass
        
    stream.update({'url': url, 'quality': quality, 'headers': headers, 'inverted': inverted})
    return stream


async def process_players(players, client_ip=None):
    streams = {'streams': []}
    
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    connector = aiohttp.TCPConnector(limit=30, limit_per_host=10, ttl_dns_cache=300, verify_ssl=False)
    
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks = [process_player(session, player, client_ip) for player in players]

        for task in asyncio.as_completed(tasks):
            stream = await task
            if stream:
                if stream['url']:
                    if not stream['translator_title']:
                        stream['translator_title'] = "unknown"
                    stream_data = {
                        'title': f"[{stream['player_hosting']}][{stream['quality']}][{stream['translator_title']}]",
                        'name': f"[{stream['player_hosting']}][{stream['quality']}][{stream['translator_title']}]",
                        'url': stream['url'],
                        'priority': sort_priority(stream)
                    }
                    if stream['inverted']:
                        stream_data['title'] = f"{stream_data['title']}[inverted]"
                        stream_data['priority'] = 8
                    if stream['player_hosting'] == 'uqload':
                        if PROXIFY_STREAMS:
                            stream_data['behaviorHints'] = {'notWebReady': True}
                    if stream.get('headers'):
                        stream_data['behaviorHints'] = {
                            'proxyHeaders': stream['headers'],
                            'notWebReady': True
                        }
                    streams['streams'].append(stream_data)
    
    streams['streams'] = sorted(streams['streams'], key=lambda d: d['priority'])
    return streams


def sort_priority(stream):
    if stream['player_hosting'] == 'lycoris.cafe':
        return 0
    elif stream['player_hosting'] == 'cda':
        return 1
    elif stream['player_hosting'] == 'uqload':
        return 4
    elif stream['player_hosting'] == 'streamtape':
        return 5
    elif stream['translator_title'].lower() == 'ai':
        return 9
    return 2


@stream_bp.route('/stream/<content_type>/<content_id>.json')
async def addon_stream(content_type: str, content_id: str):
    """
    Provide url streams for web players
    :param content_type: The type of content
    :param content_id: The id of the content
    :return: JSON response
    """
    from flask import request
    
    # Get client IP - Cloudflare passes real IP in CF-Connecting-IP
    client_ip = request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    content_id = urllib.parse.unquote(content_id)
    parts = content_id.split(":")

    if content_type not in MANIFEST['types']:
        abort(404)

    prefix = parts[0]

    prefix_id = parts[1]
    if prefix == 'kitsu':
        prefix_id = kitsu_client.get_mal_id_from_kitsu_id(prefix_id)
        if prefix_id:
            prefix = MAL_ID_PREFIX
        else:
            return respond_with({})
    try:
        episode = parts[2]
    except IndexError:
        episode = '1'

    if prefix != MAL_ID_PREFIX:
        return respond_with({})

    exists, slug = get_slug_from_mal_id(prefix_id)
    if not exists:
        slug = docchi_client.get_slug_from_mal_id(prefix_id)
        save_slug_from_mal_id(prefix_id, slug)

    players = docchi_client.get_episode_players(slug, episode)
    if players:
        streams = await process_players(players, client_ip)
        return respond_with(streams)
    return {'streams': []}
