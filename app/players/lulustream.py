import re
import aiohttp

from app.routes.utils import get_random_agent


def unpack(encoded_js):  # taken from https://github.com/LcdoWalterGarcia/Luluvdo-Link-Direct/blob/main/JavaScriptUnpacker.php
    match = re.search(r"}\('(.*)', *(\d+), *(\d+), *'(.*?)'\.split\('\|'\)", encoded_js)
    if not match:
        return ""

    payload, radix, count, symtab = match.groups()
    radix, count = int(radix), int(count)
    symtab = symtab.split('|')

    if len(symtab) != count:
        raise ValueError("Malformed p.a.c.k.e.r symtab")

    def unbase(val):
        alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'[:radix]
        base_dict = {char: index for index, char in enumerate(alphabet)}
        result = 0
        for i, char in enumerate(reversed(val)):
            result += base_dict[char] * (radix ** i)
        return result

    def lookup(match):
        word = match.group(0)
        index = unbase(word)
        return symtab[index] if index < len(symtab) else word

    decoded = re.sub(r'\b\w+\b', lookup, payload)
    return decoded.replace('\\', '')


def fix_m3u8_link(link: str) -> str:
    param_order = ['t', 's', 'e', 'f']
    params = re.findall(r'[?&]([^=]*)=([^&]*)', link)

    param_dict = {}
    for i, (key, value) in enumerate(params):
        if not key:
            if i < len(param_order):
                param_dict[param_order[i]] = value
        else:
            param_dict[key] = value

    base_url = link.split('?')[0]
    fixed_link = base_url + '?' + '&'.join(f"{k}={v}" for k, v in param_dict.items() if k in param_order)

    fixed_link = f'{fixed_link}&i=0.3&sp=0'

    return fixed_link


async def fetch_resolution_from_m3u8(session, m3u8_url, headers):
    m3u8_url = m3u8_url
    async with session.get(m3u8_url, headers=headers, timeout=10) as response:
        response.raise_for_status()
        m3u8_content = await response.text()

    resolution_match = re.search(r'RESOLUTION=\d+x(\d+)', m3u8_content)

    if resolution_match:
        return int(resolution_match.group(1))
    return None


async def get_video_from_lulustream_player(filelink):
    headers = {
        "User-Agent": get_random_agent(),
        "Referer": "https://luluvdo.com",
        "Origin": "https://luluvdo.com"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(filelink, headers=headers, timeout=10) as response:
            response.raise_for_status()
            html_content = await response.text()

        player_data = ""
        if re.search(r"eval\(function\(p,a,c,k,e", html_content):
            player_data = unpack(html_content)

        m3u8_match = re.search(r"sources:\[\{file:\"([^\"]+)\"", player_data)
        if not m3u8_match:
            return None, None

        stream_url = fix_m3u8_link(m3u8_match.group(1))
        try:
            quality = await fetch_resolution_from_m3u8(session, stream_url, headers)
            quality = f'{quality}p'
        except:
            quality = 'unknown'
        stream_headers = {'request': headers}

        return stream_url, quality, stream_headers
