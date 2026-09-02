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
MODEL = "tencent/hy-mt2-30b-a3b"
FALLBACK_MODEL = "openai/gpt-4.1-nano"

TRANSLATE_PROMPT = (
    "Translate the following anime synopsis/episode description from English to Polish. "
    "Return ONLY the translated text, nothing else. "
    "Keep proper nouns (character names, place names, attack names) unchanged. "
    "Use natural Polish that fits anime/manga context.\n\n"
)

BATCH_TRANSLATE_PROMPT = (
    "Translate anime episode titles and descriptions from English to Polish.\n"
    "Use natural Polish that fits anime/manga context. Translate contextually, not literally.\n"
    "Pay attention to Polish grammar — ensure correct gender agreement "
    "(e.g. 'kometa' is feminine: 'moja cudowna kometa', NOT 'mój cudowny kometa').\n"
    "Important: translate based on meaning, not word-for-word. Examples:\n"
    "- 'draw a bow' = 'naciągnąć łuk' (NOT 'rysować łuk')\n"
    "- 'court' in royal context = 'dwór' (NOT 'sąd')\n"
    "- 'vessel' in supernatural context = 'naczynie' (NOT 'statek')\n"
    "- 'villainess' in anime/otome context = 'złoczyńczyni' (NOT 'panienka', NOT 'szlachcianka')\n\n"
    "Always translate titles to Polish. Keep character names and place names unchanged.\n"
    "Prefer natural-sounding Polish titles over literal translations. Adapt the title so it sounds good in Polish.\n"
    "Treat each episode independently — do NOT let one episode's phrasing influence another.\n"
    "Return ONLY the translation. Do NOT add alternatives, notes, comments, or parenthetical explanations.\n"
    "If TITLE is 'empty', return TITLE: empty (do NOT put the description there).\n"
    "If DESC is 'empty', return DESC: empty.\n\n"
    "INPUT:\n"
    "TITLE: The Boy Who Became Wind\n"
    "DESC: Tanjiro begins his journey to find a cure.\n"
    "---\n"
    "TITLE: empty\n"
    "DESC: The hero fights against impossible odds to save his friends.\n"
    "---\n"
    "TITLE: A New Dawn\n"
    "DESC: empty\n\n"
    "OUTPUT:\n"
    "TITLE: Chłopiec, który stał się wiatrem\n"
    "DESC: Tanjiro rozpoczyna podróż w poszukiwaniu lekarstwa.\n"
    "---\n"
    "TITLE: empty\n"
    "DESC: Bohater walczy z niemożliwymi przeciwnościami, aby uratować przyjaciół.\n"
    "---\n"
    "TITLE: Nowy świt\n"
    "DESC: empty\n\n"
    "Now translate the following. Use EXACTLY the format above (TITLE: and DESC: headers, --- separator):\n\n"
)

# Rate limiting: sliding window, 20 RPM max
_request_times: list[float] = []
_MAX_RPM = 18  # stay slightly under 20
_WINDOW = 60.0


# Patterns that indicate AI prompt leakage in translation output
_CORRUPTION_PATTERNS = [
    "Let's count them",
    "No extra text, no numbering",
    "We need to translate",
    "separated by exactly",
    "preserving proper nouns",
    "Return translations",
    "Use natural Polish",
    "\" in the source",
    "I'll copy the source",
    "translate each",
]


def _is_corrupted(text: str) -> bool:
    """Check if translated text contains AI prompt leakage."""
    if not text:
        return False
    for pattern in _CORRUPTION_PATTERNS:
        if pattern in text:
            return True
    return False


def _acquire_rate_slot():
    """Synchronous sliding window check. Returns seconds to wait, or 0 if slot available."""
    now = time.time()
    while _request_times and _request_times[0] < now - _WINDOW:
        _request_times.pop(0)
    if len(_request_times) >= _MAX_RPM:
        return _request_times[0] + _WINDOW - now + 0.1
    _request_times.append(now)
    return 0


async def _openrouter_request(prompt_text: str, model_override: str = None) -> str | None:
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

    models = [model_override] if model_override else [MODEL, FALLBACK_MODEL, "nvidia/nemotron-3-super-120b-a12b:free"]
    for model in models:
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
                            # Detect content filter refusal
                            lower = content.strip().lower()
                            if lower.startswith("sorry") or lower.startswith("i can't") or lower.startswith("i cannot") or "i'm not able to" in lower:
                                return "__CONTENT_REFUSED__"
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
    result = await _openrouter_request(f"{TRANSLATE_PROMPT}{text}")
    if result and _is_corrupted(result):
        logging.warning(f"[Translate] Corrupted single translation detected, discarding")
        return None
    return result


async def batch_translate_to_polish(texts: list[str]) -> list[str | None]:
    """Translate multiple texts in a single API call using delimiter-based batching.
    
    Uses simple |||NEXT||| delimiter format for plain text translations (descriptions).
    """
    if not Config.OPENROUTER_API_KEY or not texts:
        return [None] * len(texts)

    if len(texts) == 1:
        result = await translate_to_polish(texts[0])
        return [result]

    BATCH_SIMPLE_PROMPT = (
        "Below are multiple anime descriptions in English, each separated by |||NEXT|||.\n"
        "Translate each one independently from English to Polish.\n"
        "Keep proper nouns (character names, place names) unchanged.\n"
        "Use natural Polish that fits anime/manga context.\n"
        "Return translations in the same order, separated by the EXACT delimiter: |||NEXT|||\n"
        "Do NOT add numbering, labels, or any extra text — just the translations separated by |||NEXT|||\n\n"
    )

    # Build batch prompt
    numbered_texts = "\n|||NEXT|||\n".join(texts)
    prompt = f"{BATCH_SIMPLE_PROMPT}{numbered_texts}"

    result = await _openrouter_request(prompt)
    if not result:
        return [None] * len(texts)

    # Parse response by delimiter
    parts = result.split("|||NEXT|||")
    
    # Validate: if model returned wrong number of parts, fall back to individual translations
    if len(parts) != len(texts):
        logging.warning(f"[Translate] Batch mismatch: expected {len(texts)} parts, got {len(parts)}. Falling back to individual.")
        results = []
        for text in texts:
            r = await translate_to_polish(text)
            results.append(r)
        return results
    translations = []
    for i in range(len(texts)):
        if i < len(parts):
            translated = parts[i].strip()
            if translated and _is_corrupted(translated):
                logging.warning(f"[Translate] Corrupted batch translation at index {i}, discarding")
                translations.append(None)
            else:
                translations.append(translated if translated else None)
        else:
            translations.append(None)

    return translations


async def batch_translate_episodes(episodes: list[dict]) -> list[dict]:
    """Translate episodes (title + description) in a single structured API call.
    
    Args:
        episodes: list of {"title": str, "overview": str|None} dicts
    
    Returns:
        list of {"title": str|None, "overview": str|None} with translated values.
        None means translation failed for that field.
    """
    if not Config.OPENROUTER_API_KEY or not episodes:
        return [{"title": None, "overview": None}] * len(episodes)

    # Build structured prompt
    parts = []
    for ep in episodes:
        title = ep.get("title") or ""
        overview = ep.get("overview") or ""
        parts.append(f"TITLE: {title if title else 'empty'}\nDESC: {overview if overview else 'empty'}")
    
    prompt = BATCH_TRANSLATE_PROMPT + "\n---\n".join(parts)

    result = await _openrouter_request(prompt)
    if not result:
        return [{"title": None, "overview": None}] * len(episodes)
    if result == "__CONTENT_REFUSED__":
        return [{"title": "__CONTENT_REFUSED__", "overview": "__CONTENT_REFUSED__"}] * len(episodes)

    # Parse structured response
    blocks = result.split("---")
    translations = []
    for i in range(len(episodes)):
        if i < len(blocks):
            block = blocks[i].strip()
            title_line = None
            desc_line = None
            for line in block.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.upper().startswith("TITLE:") or line.upper().startswith("TYTUŁ:") or line.upper().startswith("TITUL:"):
                    sep = line.index(":") + 1
                    title_line = line[sep:].strip()
                elif line.upper().startswith("DESC:") or line.upper().startswith("OPIS:"):
                    sep = line.index(":") + 1
                    desc_line = line[sep:].strip()
                elif desc_line is not None and line:
                    desc_line += " " + line
            if desc_line and desc_line.lower() in ("empty", "puste", "pusty", "brak"):
                desc_line = None
            if title_line and title_line.lower() in ("empty", "puste", "pusty", "brak"):
                title_line = None
            # Validate: discard corrupted translations
            if title_line and _is_corrupted(title_line):
                title_line = None
            if desc_line and _is_corrupted(desc_line):
                desc_line = None
            translations.append({"title": title_line or None, "overview": desc_line or None})
        else:
            translations.append({"title": None, "overview": None})

    return translations
