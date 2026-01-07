"""
Proxy endpoint for IP-bound m3u8 playlists.
Fetches the playlist on server-side and returns it unchanged,
since the actual media segments inside are not IP-bound.
"""

import base64
import hashlib
import requests
from flask import Blueprint, request, Response, abort
from app.utils.common_utils import get_random_agent
from config import Config

proxy_bp = Blueprint('proxy', __name__)


def encode_proxy_url(url: str, secret_key: str) -> str:
    """Encode URL with HMAC signature to prevent tampering."""
    signature = hashlib.sha256(f"{url}{secret_key}".encode()).hexdigest()[:16]
    encoded_url = base64.urlsafe_b64encode(url.encode()).decode()
    return f"{encoded_url}.{signature}"


def decode_proxy_url(encoded: str, secret_key: str) -> str | None:
    """Decode and verify URL signature."""
    try:
        parts = encoded.split('.')
        if len(parts) != 2:
            return None
        
        encoded_url, signature = parts
        url = base64.urlsafe_b64decode(encoded_url).decode()
        
        expected_signature = hashlib.sha256(f"{url}{secret_key}".encode()).hexdigest()[:16]
        if signature != expected_signature:
            return None
        
        return url
    except Exception:
        return None


@proxy_bp.route('/proxy/m3u8')
def proxy_m3u8():
    """
    Proxy endpoint for IP-bound m3u8 playlists.
    Query params:
    - url: The encoded m3u8 URL to fetch
    - referer: (optional) Encoded referer header
    - use_proxy: (optional) '1' to use MediaFlow proxy for fetching
    """
    encoded_url = request.args.get('url')
    if not encoded_url:
        abort(400, 'Missing url parameter')
    
    # Decode URL
    url = decode_proxy_url(encoded_url, Config.PROXY_SECRET_KEY)
    if not url:
        abort(403, 'Invalid or tampered URL')
    
    # Decode referer if provided
    encoded_referer = request.args.get('referer', '')
    referer = decode_proxy_url(encoded_referer, Config.PROXY_SECRET_KEY) if encoded_referer else ''
    
    user_agent = request.args.get('user_agent', get_random_agent())
    use_proxy = request.args.get('use_proxy', '0') == '1'
    
    headers = {
        'User-Agent': user_agent,
        'Referer': referer
    }
    
    try:
        # Use MediaFlow proxy if requested and enabled
        if use_proxy and Config.PROXIFY_STREAMS:
            proxy_url = f'{Config.STREAM_PROXY_URL}/proxy/stream?d={url}&api_password={Config.STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
            response = requests.get(proxy_url, headers=headers, timeout=10, verify=False)
        else:
            response = requests.get(url, headers=headers, timeout=10)
        
        response.raise_for_status()
        content = response.text
        
        return Response(content, mimetype='application/vnd.apple.mpegurl')
    
    except Exception as e:
        abort(500, f'Error fetching m3u8: {str(e)}')
