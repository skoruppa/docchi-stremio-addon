"""Translation utility using Gemini 2.5 Flash-Lite for English→Polish translation.

Free tier: 15 RPM, 1000 RPD, never expires.
On failure (429/error), returns None — caller should serve English text and cache briefly.

Strategy: batch multiple texts into single API calls to minimize RPM usage.
Rate limiting via sliding window to stay under 15 RPM.
"""
import asyncio
import logging
import time
import aiohttp
from config import Config

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
TIMEOUT = aiohttp.ClientTimeout(total=30)

TRANSLATE_PROMPT = (
    "Translate the following anime synopsis/episode description from English to Polish. "
    "Return ONLY the translated text, nothing else. "
    "Keep proper nouns (character names, place names, attack names) unchanged. "
    "Use natural Polish that fits anime/manga context.\n\n"
)

BATCH_TRANSLATE_PROMPT = (
    "Below are multiple anime series/episode descriptions in English, each separated by |||NEXT|||.\n"
    "Translate each one independently from English to Polish.\n"
    "Keep proper nouns (character names, place names, attack names) unchanged.\n"
    "Use natural Polish that fits anime/manga context.\n"
    "Return translations in the same order, separated by the EXACT delimiter: |||NEXT|||\n"
    "Do NOT add numbering, labels, or any extra text — just the translations separated by |||NEXT|||\n\n"
)

# Rate limiting state (no asyncio primitives at module level)
_request_times: list[float] = []
_MAX_RPM = 12
_WINDOW = 60.0


def _acquire_rate_slot():
    """Synchronous sliding window check. Returns seconds to wait, or 0 if slot available."""
    now = time.time()
    # Remove requests older than window
    while _request_times and _request_times[0] < now - _WINDOW:
        _request_times.pop(0)
    # If at limit, calculate wait time
    if len(_request_times) >= _MAX_RPM:
        return _request_times[0] + _WINDOW - now + 0.1
    # Record this request
    _request_times.append(now)
    return 0


async def _gemini_request(prompt_text: str) -> str | None:
    """Make a single rate-limited request to Gemini API."""
    if not Config.GEMINI_API_KEY:
        return None

    # Sliding window rate limit
    wait = _acquire_rate_slot()
    if wait > 0:
        await asyncio.sleep(wait)
        # Re-acquire after waiting
        _request_times.append(time.time())

    params = {"key": Config.GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(GEMINI_URL, json=payload, params=params) as resp:
                if resp.status == 429:
                    logging.warning("Gemini translation rate limited (429)")
                    return None
                if resp.status != 200:
                    logging.warning(f"Gemini translation failed: HTTP {resp.status}")
                    return None
                data = await resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                return None
    except Exception as e:
        logging.error(f"Gemini translation error: {e}")
        return None


async def translate_to_polish(text: str) -> str | None:
    """Translate a single text from English to Polish using Gemini."""
    if not text or not Config.GEMINI_API_KEY:
        return None
    return await _gemini_request(f"{TRANSLATE_PROMPT}{text}")


async def batch_translate_to_polish(texts: list[str]) -> list[str | None]:
    """Translate multiple texts in a single Gemini call using delimiter-based batching.
    
    Sends all texts in one request, separated by markers.
    Parses response by delimiter. Falls back to None for unparseable entries.
    Uses 1 API call for up to ~30 texts instead of 30 separate calls.
    """
    if not Config.GEMINI_API_KEY or not texts:
        return [None] * len(texts)

    # For single text, use simple translation
    if len(texts) == 1:
        result = await translate_to_polish(texts[0])
        return [result]

    # Build batch prompt
    numbered_texts = "\n|||NEXT|||\n".join(texts)
    prompt = f"{BATCH_TRANSLATE_PROMPT}{numbered_texts}"

    result = await _gemini_request(prompt)
    if not result:
        return [None] * len(texts)

    # Parse response by delimiter
    parts = result.split("|||NEXT|||")
    translations = []
    for i, text in enumerate(texts):
        if i < len(parts):
            translated = parts[i].strip()
            translations.append(translated if translated else None)
        else:
            translations.append(None)

    return translations
