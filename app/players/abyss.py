import re
import json
import hashlib
import base64
import aiohttp
from urllib.parse import urljoin
from app.utils.common_utils import get_random_agent
from app.players.test import run_tests

# Domains handled by this player
DOMAINS = ['abysscdn.com', 'hydraxcdn.biz', 'short.icu', 'embedplayabyss.top']
NAMES = ['abyss']

ENABLED = True

_CHARSET = 'RB0fpH8ZEyVLkv7c2i6MAJ5u3IKFDxlS1NTsnGaqmXYdUrtzjwObCgQP94hoeW+/='


def _custom_decode(encoded: str) -> str:
    """Decode custom base64 charset."""
    out = bytearray()
    for i in range(0, len(encoded), 4):
        chunk = encoded[i:i + 4].ljust(4, '=')
        c = [_CHARSET.index(ch) if ch in _CHARSET else 64 for ch in chunk]
        out.append((c[0] << 2) | (c[1] >> 4))
        if c[2] != 64:
            out.append(((c[1] & 15) << 4) | (c[2] >> 2))
        if c[3] != 64:
            out.append(((c[2] & 3) << 6) | c[3])
    return out.decode('utf-8', 'ignore')


def _derive_key(seed) -> bytearray:
    """Derive AES key from seed."""
    seed_str = str(seed)
    if seed_str.replace('.', '', 1).replace(':', '').replace('-', '').isdigit():
        buf = bytearray()
        for ch in seed_str:
            buf.append(int(ch) if ch.isdigit() else (ord(ch) & 0xFF))
        digest_source = bytes(buf)
    else:
        digest_source = seed_str.encode('utf-8')
    return bytearray(hashlib.md5(digest_source).hexdigest().encode('utf-8'))


def _aes_ctr_transform(data_bytes: bytes, key_seed) -> bytes | None:
    """AES-CTR encrypt/decrypt."""
    from Crypto.Cipher import AES
    from Crypto.Util import Counter as CtrCounter
    key = _derive_key(key_seed)
    iv = key[:16]
    ctr = CtrCounter.new(128, initial_value=int.from_bytes(bytes(iv), 'big'))
    cipher = AES.new(bytes(key), AES.MODE_CTR, counter=ctr)
    return cipher.encrypt(bytes(data_bytes))


def _decode_escaped_binary(escaped: str) -> str:
    """Decode escaped string from JSON payload."""
    if not escaped:
        return ''
    out = []
    i = 0
    esc_map = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b',
               'f': '\f', '\\': '\\', '"': '"', '/': '/'}
    while i < len(escaped):
        ch = escaped[i]
        if ch == '\\' and i + 1 < len(escaped):
            nxt = escaped[i + 1]
            if nxt == 'u' and i + 5 < len(escaped):
                try:
                    out.append(chr(int(escaped[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except Exception:
                    pass
            if nxt in esc_map:
                out.append(esc_map[nxt])
                i += 2
                continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _extract_datas_payload(html: str) -> dict:
    """Extract and parse the datas payload from HTML."""
    match = re.search(r'(?:const|var)\s+datas\s*=\s*"([^"]+)"', html or '')
    if not match:
        return {}
    try:
        raw = base64.b64decode(match.group(1).strip())
    except Exception:
        return {}
    try:
        payload = json.loads(raw.decode('utf-8'))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    decoded = raw.decode('latin-1', 'ignore')
    payload = {}
    for key, pat in [
        ('slug', r'"slug"\s*:\s*"([^"]+)"'),
        ('md5_id', r'"md5_id"\s*:\s*(\d+)'),
        ('user_id', r'"user_id"\s*:\s*(\d+)'),
    ]:
        m = re.search(pat, decoded)
        if m:
            payload[key] = int(m.group(1)) if key != 'slug' else m.group(1)

    media_marker = b'"media":"'
    config_marker = b'","config"'
    m_idx = raw.find(media_marker)
    c_idx = raw.find(config_marker)
    if m_idx >= 0 and c_idx > m_idx:
        try:
            media_escaped = raw[m_idx + len(media_marker):c_idx].decode('latin-1', 'ignore')
            payload['media'] = _decode_escaped_binary(media_escaped)
        except Exception:
            pass
    elif 'media' not in payload:
        m = re.search(r'"media"\s*:\s*"((?:\\.|[^"\\])*)"', decoded, re.DOTALL)
        if m:
            payload['media'] = _decode_escaped_binary(m.group(1))

    config_m = re.search(r'"isDownload"\s*:\s*(true|false)', decoded)
    if config_m:
        payload["isDownload"] = config_m.group(1) == "true"

    return payload if payload else {}


def _decrypt_media(encrypted_text: str, user_id, slug, md5_id) -> dict:
    """Decrypt the media payload using AES-CTR."""
    if not encrypted_text or not user_id or not slug or not md5_id:
        return {}
    key_seed = f'{user_id}:{slug}:{md5_id}'
    raw_bytes = bytes(ord(ch) & 0xFF for ch in encrypted_text)
    result = _aes_ctr_transform(raw_bytes, key_seed)
    if not result:
        return {}
    try:
        decoded = json.loads(result.decode('utf-8', 'ignore'))
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def _build_sora_token(path_value: str, size_value) -> str | None:
    """Build sora token for CDN URL."""
    transformed = _aes_ctr_transform(path_value.encode('utf-8'), str(size_value))
    if not transformed:
        return None
    first = base64.b64encode(transformed).decode('utf-8').replace('=', '')
    second = base64.b64encode(first.encode('utf-8')).decode('utf-8').replace('=', '')
    return second


def _extract_from_media_payload(media_payload: dict, slug, md5_id, is_download=False) -> tuple[str | None, str | None]:
    """Extract stream URL and quality from decrypted media payload."""
    if not isinstance(media_payload, dict):
        return None, None

    mp4 = media_payload.get('mp4') if isinstance(media_payload.get('mp4'), dict) else {}
    raw_sources = mp4.get('sources') if isinstance(mp4.get('sources'), list) else []
    sources = sorted(
        [s for s in raw_sources if isinstance(s, dict)],
        key=lambda s: int(s.get('size', 0) or 0),
        reverse=True
    )

    for src in sources:
        label = src.get('label')
        direct = src.get('file')
        if isinstance(direct, str) and direct:
            return direct.replace('\\/', '/'), label
        if not is_download:
            url_ = src.get('url')
            path_ = src.get('path')
            if isinstance(url_, str) and isinstance(path_, str) and url_ and path_:
                return f"{url_.rstrip('/')}/{path_.lstrip('/')}".replace('\\/', '/'), label

    # Try HLS
    hls = media_payload.get('hls') if isinstance(media_payload.get('hls'), dict) else {}
    for key in ('file', 'url', 'master', 'src', 'source'):
        val = hls.get(key)
        if isinstance(val, str) and val:
            return val.replace('\\/', '/'), None
    for hs in (hls.get('sources') or []):
        if not isinstance(hs, dict):
            continue
        f = hs.get('file') or hs.get('url') or hs.get('src')
        if isinstance(f, str) and f:
            return f.replace('\\/', '/'), hs.get('label')

    # Try sora token construction
    domains = mp4.get('domains') if isinstance(mp4.get('domains'), list) else []
    for src in sources:
        size = src.get('size')
        res_id = src.get('res_id')
        sub = src.get('sub')
        label = src.get('label')
        if not (size and res_id and sub and md5_id and slug):
            continue
        domain = next((d for d in domains if isinstance(d, str) and sub in d), None)
        if not domain:
            continue
        path_value = f'/mp4/{md5_id}/{res_id}/{size}?v={slug}'
        token = _build_sora_token(path_value, str(size))
        if token:
            norm = domain if domain.startswith('http') else f'https://{domain}'
            return f'{norm.rstrip("/")}/sora/{size}/{token}', label

    # HLS by ID fallback
    hls_id = hls.get('id')
    if hls_id:
        return f'https://abysscdn.com/#hls/{hls_id}/master.m3u8', None

    return None, None


def _legacy_extract(html: str) -> str | None:
    """Legacy extraction for older page format."""
    m = re.search(
        r"[\w$]+=\'([A-Za-z0-9+/=RB0fpH8ZEyVLkv7c2i6MAJ5u3IKFDxlS1NTsnGaqmXYdUrtzjwObCgQP94hoeW]{30,})_\'",
        html or ''
    )
    if m:
        try:
            meta = json.loads(_custom_decode(m.group(1)))
            domain = meta.get('domain', '')
            vid_id = meta.get('id', '')
            if domain and vid_id:
                return f'https://{domain.strip("/")}/{vid_id}'
        except Exception:
            pass

    dm = re.search(r"['\"]domain['\"]\s*:\s*['\"]([^'\"]+)['\"]", html or '')
    im = re.search(r"['\"]id['\"]\s*:\s*['\"]([^'\"]+)['\"]", html or '')
    if dm and im:
        return f'https://{dm.group(1).strip("/")}/{im.group(1)}'
    return None


async def get_video_from_abyss_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from Abyss/HydraX player."""
    try:
        # Normalize host
        if 'short.icu' in url or 'embedplayabyss.top' in url:
            # Rewrite to abysscdn.com
            vid_match = re.search(r'[?/]v=([0-9a-zA-Z_-]+)', url)
            if vid_match:
                url = f'https://abysscdn.com/?v={vid_match.group(1)}'

        headers = {
            "User-Agent": get_random_agent(),
            "Referer": urljoin(url, '/'),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        async with session.get(url, headers=headers, ssl=False, timeout=aiohttp.ClientTimeout(total=10),
                               allow_redirects=True) as response:
            response.raise_for_status()
            final_url = str(response.url)
            html = await response.text()

        # Update referer if redirected
        if final_url != url:
            headers['Referer'] = urljoin(final_url, '/')

        # Try new datas payload extraction
        datas = _extract_datas_payload(html)
        source = None

        if datas:
            slug = datas.get('slug')
            md5_id = datas.get('md5_id')
            user_id = datas.get('user_id')
            media_blob = datas.get('media')
            is_download = datas.get("isDownload", False)

            if isinstance(media_blob, dict):
                media_payload = media_blob
            else:
                media_payload = _decrypt_media(media_blob, user_id, slug, md5_id)

            source, quality = _extract_from_media_payload(media_payload, slug, md5_id, is_download)
        else:
            # Fallback to legacy extraction
            source = _legacy_extract(html)
            quality = None

        if source:
            return source, quality, {'request': headers}

        print("Abyss Player Error: No video source found")
        return None, None, None

    except Exception as e:
        print(f"Abyss Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    urls_to_test = [
        "https://abysscdn.com/?v=Q1a8w6rjA",
    ]
    run_tests(get_video_from_abyss_player, urls_to_test)
