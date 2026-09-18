"""
Proxy utilities for MediaFlow integration with fallback support.
"""

import logging
import aiohttp
from config import Config

# Primary proxy
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD

# Fallback proxy (used if primary fails or returns 403)
STREAM_PROXY_URL_FALLBACK = Config.STREAM_PROXY_URL_FALLBACK
STREAM_PROXY_PASSWORD_FALLBACK = Config.STREAM_PROXY_PASSWORD_FALLBACK

_PROXIES = []
if STREAM_PROXY_URL:
    _PROXIES.append((STREAM_PROXY_URL, STREAM_PROXY_PASSWORD))
if STREAM_PROXY_URL_FALLBACK:
    _PROXIES.append((STREAM_PROXY_URL_FALLBACK, STREAM_PROXY_PASSWORD_FALLBACK))


async def generate_proxy_url(
    session: aiohttp.ClientSession, 
    destination_url: str, 
    endpoint: str = '/proxy/stream',
    request_headers: dict = None,
    response_headers: dict = None,
    proxy_index: int = 0,
) -> str:
    """
    Generate signed proxy URL using MediaFlow /generate_url endpoint.
    Tries primary proxy first, falls back to secondary if available.
    """
    for i in range(proxy_index, len(_PROXIES)):
        proxy_url, proxy_password = _PROXIES[i]
        generate_url = f"{proxy_url}/generate_url"
        
        payload = {
            'mediaflow_proxy_url': proxy_url,
            'endpoint': endpoint,
            'destination_url': destination_url,
            'expiration': 3600,
            'api_password': proxy_password,
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
        except Exception as e:
            logging.warning(f"[Proxy] generate_url failed on proxy {i}: {e}")
            continue

    return destination_url


async def proxy_get(session: aiohttp.ClientSession, url: str,
                    headers: dict = None, timeout: int = 10) -> tuple[str | None, int]:
    """GET through proxy with fallback. Returns (response_text, proxy_index_used) or (None, -1).
    
    Tries each proxy in order. Skips to next on 403 or connection error.
    Falls back to direct request if no proxy works.
    """
    ua = (headers or {}).get('User-Agent', 'Mozilla/5.0')
    referer = (headers or {}).get('Referer', '')

    for i, (proxy_url, proxy_password) in enumerate(_PROXIES):
        forward_url = (
            f'{proxy_url}/proxy/stream?d={url}'
            f'&api_password={proxy_password}'
            f'&h_user-agent={ua}'
        )
        if referer:
            forward_url += f'&h_referer={referer}'

        try:
            async with session.get(forward_url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 403 or resp.status == 502:
                    text = await resp.text()
                    if 'error' in text.lower() or 'forbidden' in text.lower():
                        logging.info(f"[Proxy] GET {url} blocked on proxy {i}, trying next")
                        continue
                if resp.status == 200:
                    return await resp.text(), i
                return None, i
        except Exception as e:
            logging.warning(f"[Proxy] GET failed on proxy {i}: {e}")
            continue

    # All proxies failed — try direct
    try:
        h = dict(headers) if headers else {}
        async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 200:
                return await resp.text(), -1
    except Exception:
        pass

    return None, -1


async def proxy_post(session: aiohttp.ClientSession, url: str,
                     data: str = None, headers: dict = None,
                     content_type: str = 'application/x-www-form-urlencoded',
                     timeout: int = 10) -> tuple[str | None, int]:
    """POST through proxy with fallback. Returns (response_text, proxy_index_used) or (None, -1)."""
    ua = (headers or {}).get('User-Agent', 'Mozilla/5.0')
    referer = (headers or {}).get('Referer', '')

    for i, (proxy_url, proxy_password) in enumerate(_PROXIES):
        forward_url = (
            f'{proxy_url}/proxy/forward?d={url}'
            f'&api_password={proxy_password}'
            f'&h_user-agent={ua}'
            f'&h_content-type={content_type}'
        )
        if referer:
            forward_url += f'&h_referer={referer}'

        try:
            async with session.post(forward_url, data=data,
                                    headers={'Content-Type': content_type},
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 403 or resp.status == 502:
                    logging.info(f"[Proxy] POST {url} blocked on proxy {i}, trying next")
                    continue
                if resp.status == 200:
                    return await resp.text(), i
                return None, i
        except Exception as e:
            logging.warning(f"[Proxy] POST failed on proxy {i}: {e}")
            continue

    # All proxies failed — try direct
    try:
        h = dict(headers) if headers else {}
        async with session.post(url, data=data, headers=h,
                                timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 200:
                return await resp.text(), -1
    except Exception:
        pass

    return None, -1
