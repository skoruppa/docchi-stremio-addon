"""
Proxy utilities for MediaFlow integration.
"""

import aiohttp
from config import Config

STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


async def generate_proxy_url(
    session: aiohttp.ClientSession, 
    destination_url: str, 
    endpoint: str = '/proxy/stream',
    request_headers: dict = None,
    response_headers: dict = None
) -> str:
    """
    Generate signed proxy URL using MediaFlow /generate_url endpoint.
    
    Args:
        session: aiohttp ClientSession
        destination_url: Target URL to proxy
        endpoint: MediaFlow endpoint (default: /proxy/stream, for HLS: /proxy/hls/manifest.m3u8)
        request_headers: Optional headers to send with proxied requests
        response_headers: Optional headers to add to proxy responses (manifest only)
    
    Returns:
        Signed proxy URL or original URL if generation fails
    """
    generate_url = f"{STREAM_PROXY_URL}/generate_url"
    
    payload = {
        'mediaflow_proxy_url': STREAM_PROXY_URL,
        'endpoint': endpoint,
        'destination_url': destination_url,
        'expiration': 3600,
        'api_password': STREAM_PROXY_PASSWORD
    }
    
    if request_headers:
        payload['request_headers'] = request_headers
    
    if response_headers:
        payload['response_headers'] = response_headers
    
    try:
        async with session.post(generate_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            resp.raise_for_status()
            result = await resp.json()
            return result.get('url', destination_url)
    except Exception:
        return destination_url
