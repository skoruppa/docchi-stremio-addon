"""Translation utility using OpenRouter free models for English→Polish translation.

Free tier: 20 RPM, 1000 RPD (with $10+ credits purchased).
On failure (429/error), returns None — caller should serve English text and cache briefly.

Strategy: batch multiple texts into single API calls to minimize RPM usage.
"""
import asyncio
import logging
import time
import aiohttp
from config import Config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = aiohttp.ClientTimeout(total=60)
MODEL = "openai/gpt-oss-120b:free"
FALLBACK_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

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

# Rate limiting: sliding window, 20 RPM max
_request_times: list[float] = []
_MAX_RPM = 18  # stay slightly under 20
_WINDOW = 60.0


def _acquire_rate_slot():
    """Synchronous sliding window check. Returns seconds to wait, or 0 if slot available."""
    now = time.time()
    while _request_times and _request_times[0] < now - _WINDOW:
        _request_times.pop(0)
    if len(_request_times) >= _MAX_RPM:
        return _request_times[0] + _WINDOW - now + 0.1
    _request_times.append(now)
    return 0


async def _openrouter_request(prompt_text: str) -> str | None:
    """Make a single rate-limited request to OpenRouter API with fallback model."""
    if not Config.OPENROUTER_API_KEY:
        return None

    wait = _acquire_rate_slot()
    if wait > 0:
        await asyncio.sleep(wait)
        _request_times.append(time.time())

    headers = {
        "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    for model in [MODEL, FALLBACK_MODEL]:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.post(OPENROUTER_URL, json=payload, headers=headers) as resp:
                    if resp.status == 429:
                        logging.warning(f"OpenRouter translation rate limited (429) on {model}")
                        continue
                    if resp.status != 200:
                        logging.warning(f"OpenRouter translation failed: HTTP {resp.status} on {model}")
                        continue
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        if content and content.strip():
                            return content.strip()
                    # Empty response, try fallback
                    continue
        except Exception as e:
            logging.error(f"OpenRouter translation error ({model}): {type(e).__name__}: {e}")
            continue

    return None


async def translate_to_polish(text: str) -> str | None:
    """Translate a single text from English to Polish."""
    if not text or not Config.OPENROUTER_API_KEY:
        return None
    return await _openrouter_request(f"{TRANSLATE_PROMPT}{text}")


async def batch_translate_to_polish(texts: list[str]) -> list[str | None]:
    """Translate multiple texts in a single API call using delimiter-based batching.
    
    Uses 1 API call for up to ~30 texts instead of 30 separate calls.
    """
    if not Config.OPENROUTER_API_KEY or not texts:
        return [None] * len(texts)

    if len(texts) == 1:
        result = await translate_to_polish(texts[0])
        return [result]

    # Build batch prompt
    numbered_texts = "\n|||NEXT|||\n".join(texts)
    prompt = f"{BATCH_TRANSLATE_PROMPT}{numbered_texts}"

    result = await _openrouter_request(prompt)
    if not result:
        return [None] * len(texts)

    # Parse response by delimiter
    parts = result.split("|||NEXT|||")
    translations = []
    for i in range(len(texts)):
        if i < len(parts):
            translated = parts[i].strip()
            translations.append(translated if translated else None)
        else:
            translations.append(None)

    return translations
