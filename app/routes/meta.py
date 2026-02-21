import re
from urllib.parse import unquote
from flask import Blueprint, abort, request
from config import Config
from .manifest import MANIFEST
from app.utils.stream_utils import respond_with, cache
from app.utils.meta_cache import fetch_and_cache_meta

meta_bp = Blueprint('meta', __name__)


@meta_bp.route('/meta/<meta_type>/<meta_id>.json')
@cache.cached(timeout=86400)
async def addon_meta(meta_type: str, meta_id: str):
    is_vip = Config.VIP_PATH in request.path
    meta_id = unquote(meta_id)

    if meta_type not in MANIFEST['types']:
        abort(404)

    if '_' in meta_id:
        meta_id = meta_id.replace("_", ":")

    meta, mal_id = await fetch_and_cache_meta(meta_id, is_vip)

    if not meta:
        return respond_with({'meta': {}, 'message': 'Could not fetch anime metadata'}), 404

    meta['id'] = meta_id
    return respond_with({'meta': meta}, 86400, 86400)
