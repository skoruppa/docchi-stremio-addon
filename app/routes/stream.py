import asyncio
import urllib.parse
from flask import Blueprint

from app.routes import MAL_ID_PREFIX, docchi_client
from app.routes.utils import respond_with
from app.db.db import get_slug_from_mal_id, save_slug_from_mal_id
from app.players.cda import get_video_from_cda_player
from app.players.lycoris import get_video_from_lycoris_player
from app.players.okru import get_video_from_okru_player
from app.players.sibnet import get_video_from_sibnet_player
from app.players.dailymotion import get_video_from_dailymotion_player
from config import Config

stream_bp = Blueprint('stream', __name__)
PROXIFY_CDA = Config.PROXIFY_CDA
supported_streams = ['cda', 'lycoris.cafe', 'ok', 'sibnet', 'dailymotion']


async def process_player(player):
    player_hosting = player['player_hosting'].lower()
    stream = {
        'url': None,
        'quality': None,
        'player_hosting': player_hosting,
        'translator_title': player['translator_title'],
        'headers': None
    }
    headers = None

    if player_hosting == 'cda':
        url, quality = await get_video_from_cda_player(player['player'])
    elif player_hosting == 'lycoris.cafe':
        url, quality = await get_video_from_lycoris_player(player['player'])
    elif player_hosting == 'ok':
        url, quality = await get_video_from_okru_player(player['player'])
    elif player_hosting == 'sibnet':
        url, quality, headers = await get_video_from_sibnet_player(player['player'])
    elif player_hosting == 'dailymotion':
        url, quality, headers = await get_video_from_dailymotion_player(player['player'])
    else:
        return stream

    stream.update({'url': url, 'quality': quality, 'headers': headers})
    return stream


async def process_players(players):
    streams = {'streams': []}
    tasks = [process_player(player) for player in players if player['player_hosting'].lower() in supported_streams]

    for task in asyncio.as_completed(tasks):
        stream = await task
        if stream['url']:
            stream_data = {
                'title': f"[{stream['player_hosting']}][{stream['quality']}][{stream['translator_title']}]",
                'name': f"[{stream['player_hosting']}][{stream['quality']}][{stream['translator_title']}]",
                'url': stream['url']
            }
            if stream['player_hosting'] == 'cda':
                if PROXIFY_CDA:
                    stream_data['behaviorHints'] = {'notWebReady': True}
            if stream.get('headers'):
                stream_data['behaviorHints'] = {
                    'proxyHeaders': {
                        'request': stream['headers']
                    },
                    'notWebReady': True
                }
            streams['streams'].append(stream_data)
    return streams


@stream_bp.route('/stream/<content_type>/<content_id>.json')
async def addon_stream(content_type: str, content_id: str):
    """
    Provide url streams for web players
    :param content_type: The type of content
    :param content_id: The id of the content
    :return: JSON response
    """
    content_id = urllib.parse.unquote(content_id)
    parts = content_id.split(":")

    prefix = parts[0]
    prefix_id = parts[1]
    episode = parts[2]

    if prefix != MAL_ID_PREFIX:
        return respond_with({})

    exists, slug = get_slug_from_mal_id(prefix_id)
    if not exists:
        slug = docchi_client.get_slug_from_mal_id(prefix_id)
        save_slug_from_mal_id(prefix_id, slug)

    players = docchi_client.get_episode_players(slug, episode)
    if players:
        streams = await process_players(players)
        return respond_with(streams)
    return {}
