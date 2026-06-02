"""Translation utility using Gemini 2.5 Flash-Lite for English→Polish translation.
"""
import logging
import aiohttp
from config import Config

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
TIMEOUT = aiohttp.ClientTimeout(total=15)

TRANSLATE_PROMPT = (
    "Translate the following anime synopsis/episode description from English to Polish. "
    "Return ONLY the translated text, nothing else. "
    "Keep proper nouns (character names, place names, attack names) unchanged. "
    "Use natural Polish that fits anime/manga context.\n\n"
)


async def translate_to_polish(text: str) -> str | None:
    """Translate text from English to Polish using Gemini.
    
    Returns translated text or None if translation fails/not configured.
    None signals the caller to use English fallback with short cache TTL.
    """
    if not text or not Config.GEMINI_API_KEY:
        return None

    params = {"key": Config.GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": f"{TRANSLATE_PROMPT}{text}"}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024,
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


async def batch_translate_to_polish(texts: list[str]) -> list[str | None]:
    """Translate multiple texts concurrently. Returns list of translations (None for failures)."""
    import asyncio
    if not Config.GEMINI_API_KEY:
        return [None] * len(texts)
    return await asyncio.gather(*[translate_to_polish(t) for t in texts])
