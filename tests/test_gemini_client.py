"""Unit tests for src/gemini_client.py — model fallback chain and cache keying."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.errors import APIError

import src.gemini_client as gc


def _api_error(code: int) -> APIError:
    """Build a minimal APIError with the given HTTP status code."""
    err = APIError.__new__(APIError)
    err.code = code
    err.message = f"HTTP {code}"
    return err


def _mock_response(text: str = "digest text") -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.usage_metadata = None
    return resp


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------

class TestIsRetryable:
    def test_429_is_retryable(self):
        assert gc._is_retryable(_api_error(429))

    def test_500_is_retryable(self):
        assert gc._is_retryable(_api_error(500))

    def test_503_is_retryable(self):
        assert gc._is_retryable(_api_error(503))

    def test_404_not_retryable(self):
        assert not gc._is_retryable(_api_error(404))

    def test_400_not_retryable(self):
        assert not gc._is_retryable(_api_error(400))


# ---------------------------------------------------------------------------
# generate — model fallback chain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_succeeds_on_first_model():
    gc._cache_by_prompt.clear()
    resp = _mock_response("market digest")

    with patch.object(gc, "_get_client") as mock_client_fn, \
         patch("src.gemini_client.asyncio.to_thread", new=AsyncMock(return_value=resp)):
        mock_client_fn.return_value = MagicMock()
        result = await gc.generate("test prompt")

    assert result == "market digest"


@pytest.mark.asyncio
async def test_generate_falls_back_on_429():
    """First model returns 429; second model should succeed."""
    gc._cache_by_prompt.clear()
    resp = _mock_response("fallback digest")
    call_count = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _api_error(429)
        return resp

    with patch.object(gc, "_get_client") as mock_client_fn, \
         patch("src.gemini_client.asyncio.to_thread", new=AsyncMock(side_effect=fake_to_thread)):
        mock_client_fn.return_value = MagicMock()
        # Use only 2 models for this test
        with patch.object(gc, "GEMINI_MODELS", ["model-a", "model-b"]):
            result = await gc.generate("test prompt")

    assert result == "fallback digest"
    assert call_count == 2


@pytest.mark.asyncio
async def test_generate_raises_when_all_models_exhausted():
    """RuntimeError is raised when every model fails with a retryable error."""
    gc._cache_by_prompt.clear()

    async def always_fail(fn, *args, **kwargs):
        raise _api_error(429)

    with patch.object(gc, "_get_client") as mock_client_fn, \
         patch("src.gemini_client.asyncio.to_thread", new=AsyncMock(side_effect=always_fail)):
        mock_client_fn.return_value = MagicMock()
        with patch.object(gc, "GEMINI_MODELS", ["model-a", "model-b"]):
            with pytest.raises(RuntimeError, match="All Gemini models exhausted"):
                await gc.generate("test prompt")


@pytest.mark.asyncio
async def test_generate_reraises_non_retryable_error():
    """A 400 Bad Request should propagate immediately, not try the next model."""
    gc._cache_by_prompt.clear()
    call_count = 0

    async def bad_request(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _api_error(400)

    with patch.object(gc, "_get_client") as mock_client_fn, \
         patch("src.gemini_client.asyncio.to_thread", new=AsyncMock(side_effect=bad_request)):
        mock_client_fn.return_value = MagicMock()
        with patch.object(gc, "GEMINI_MODELS", ["model-a", "model-b"]):
            with pytest.raises(APIError):
                await gc.generate("test prompt")

    assert call_count == 1  # second model never tried


# ---------------------------------------------------------------------------
# Cache keying — different system prompts get independent caches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_system_prompts_get_separate_cache_keys():
    gc._cache_by_prompt.clear()
    key1 = gc._prompt_key("system prompt A")
    key2 = gc._prompt_key("system prompt B")
    assert key1 != key2


def test_same_system_prompt_same_cache_key():
    key1 = gc._prompt_key("identical system prompt")
    key2 = gc._prompt_key("identical system prompt")
    assert key1 == key2
