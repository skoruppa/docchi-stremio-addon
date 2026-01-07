"""
Common utilities shared across the application.
"""

import re
import random
import aiohttp


def get_random_agent(browser: str = None):
    """Get random user agent string."""
    USER_AGENTS_BY_BROWSER = {
        "chrome": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        ],
        "firefox": [
            "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/119.0",
        ],
        "safari": [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        ],
        "opera": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0",
        ]
    }

    if browser and browser.lower() in USER_AGENTS_BY_BROWSER:
        return random.choice(USER_AGENTS_BY_BROWSER[browser.lower()])

    all_agents = [agent for sublist in USER_AGENTS_BY_BROWSER.values() for agent in sublist]
    return random.choice(all_agents)


def unpack_js(encoded_js):
    """Unpack JavaScript packed code (p.a.c.k.e.r format)."""
    match = re.search(r"}\\('(.*)', *(\\d+), *(\\d+), *'(.*?)'\.split\('\|'\)", encoded_js)
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

    decoded = re.sub(r'\\b\\w+\\b', lookup, payload)
    return decoded.replace('\\\\', '')


async def fetch_resolution_from_m3u8(session: aiohttp.ClientSession, m3u8_url: str, headers: dict) -> str | None:
    """Extract maximum resolution from m3u8 playlist."""
    async with session.get(m3u8_url, headers=headers, timeout=10) as response:
        response.raise_for_status()
        m3u8_content = await response.text()
    resolutions = re.findall(r'RESOLUTION=\\d+x(\\d+)', m3u8_content)
    if resolutions:
        max_resolution = max(int(r) for r in resolutions)
        return f"{max_resolution}p"
    return None
