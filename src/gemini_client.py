import asyncio
import hashlib
import logging
from typing import Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError

from src.config import GEMINI_API_KEY, GEMINI_MODELS

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None
# Per-prompt cache: sha256(system_prompt) → cache resource name (or None if creation failed)
_cache_by_prompt: dict[str, Optional[str]] = {}


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _prompt_key(system_prompt: str) -> str:
    return hashlib.sha256(system_prompt.encode()).hexdigest()[:16]


def _is_retryable(exc: APIError) -> bool:
    """Return True for quota / transient server errors worth falling back on."""
    return exc.code in (429, 500, 503)


async def _create_cache(model: str, system_prompt: str) -> Optional[str]:
    """Create a Gemini context cache for the system prompt; return its name."""
    client = _get_client()
    try:
        cache = await asyncio.to_thread(
            client.caches.create,
            model=model,
            config=types.CreateCachedContentConfig(
                system_instruction=system_prompt,
                ttl="86400s",  # 24 hours — refreshed each run
            ),
        )
        logger.info("Context cache created: %s", cache.name)
        return cache.name
    except Exception as exc:
        logger.warning("Context cache unavailable (%s) — falling back to inline system prompt", exc)
        return None


async def generate(
    prompt: str,
    system_prompt: str = "",
    use_cache: bool = True,
    response_mime_type: str | None = None,
) -> str:
    """
    Send a prompt to Gemini and return the text response.

    Tries each model in GEMINI_MODELS in order, falling back on quota/server
    errors. If system_prompt is provided and use_cache=True, caches it on the
    first call for that prompt to reduce token cost on repeated calls.
    Pass response_mime_type="application/json" to request structured JSON output.
    """
    client = _get_client()
    prompt_key = _prompt_key(system_prompt) if system_prompt else ""

    for model in GEMINI_MODELS:
        try:
            config_kwargs: dict = {}

            if system_prompt:
                if use_cache:
                    if prompt_key not in _cache_by_prompt:
                        _cache_by_prompt[prompt_key] = await _create_cache(model, system_prompt)

                    cache_name = _cache_by_prompt.get(prompt_key)
                    if cache_name:
                        config_kwargs["cached_content"] = cache_name
                    else:
                        config_kwargs["system_instruction"] = system_prompt
                else:
                    config_kwargs["system_instruction"] = system_prompt

            if response_mime_type:
                config_kwargs["response_mime_type"] = response_mime_type

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
            )

            logger.info("Response from model=%s, tokens=%s", model, getattr(response, "usage_metadata", "n/a"))
            return response.text

        except APIError as exc:
            if _is_retryable(exc):
                logger.warning("Model %s unavailable (%s %s) — trying next", model, exc.code, exc)
                # Cache may be model-specific; clear it so next model creates its own
                _cache_by_prompt.pop(prompt_key, None)
                continue
            raise

    raise RuntimeError(f"All Gemini models exhausted: {GEMINI_MODELS}")


# ---------------------------------------------------------------------------
# Phase 1.3 smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    SYSTEM_PROMPT = (
        "You are an expert financial analyst delivering concise, professional "
        "US stock market briefings. Format output clearly using bullet points "
        "and bold text for easy reading on a mobile device."
    )

    TEST_PROMPT = (
        "Summarize this news item: Apple stock rose 3% today after reporting "
        "record quarterly earnings of $2.18 per share, beating analyst estimates "
        "by 12 cents. The CEO cited strong iPhone 16 demand in emerging markets."
    )

    async def _smoke_test() -> None:
        print(f"Testing with model chain: {GEMINI_MODELS}\n")

        # Test 1: basic generation with inline system prompt (no cache)
        print("=== Test 1: Inline system prompt ===")
        result = await generate(TEST_PROMPT, system_prompt=SYSTEM_PROMPT, use_cache=False)
        print(result)

        # Test 2: context caching (second call reuses cache)
        print("\n=== Test 2: Context cache (first call — creates cache) ===")
        result2 = await generate(TEST_PROMPT, system_prompt=SYSTEM_PROMPT, use_cache=True)
        print(result2)

        print("\n=== Test 3: Context cache (second call — reuses cache) ===")
        result3 = await generate("What was the main driver of Apple's earnings beat?", system_prompt=SYSTEM_PROMPT, use_cache=True)
        print(result3)

        print("\nSmoke test passed.")

    asyncio.run(_smoke_test())
