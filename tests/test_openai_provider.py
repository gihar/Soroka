"""Tests for OpenAIProvider preset handling and cache invalidation."""
import asyncio
import importlib
import sys
from unittest.mock import MagicMock

import pytest


def _load_real_openai_provider():
    """Load the real OpenAIProvider class, evicting any stub that another test
    (e.g. tests/test_llm_manager.py) may have injected into sys.modules."""
    mod_name = "src.llm.providers.openai_provider"
    cached = sys.modules.get(mod_name)
    # test_llm_manager.py inserts a bare types.ModuleType named "fake" as a stub.
    if cached is not None and not getattr(cached, "__file__", None):
        del sys.modules[mod_name]
    module = importlib.import_module(mod_name)
    return module.OpenAIProvider


def test_invalidate_cache_for_removes_matching_entry():
    """invalidate_cache_for(base_url, api_key_hash) removes that cached client."""
    OpenAIProvider = _load_real_openai_provider()

    p = OpenAIProvider.__new__(OpenAIProvider)
    p.default_client = None
    p._client_cache = {
        ("https://api.openai.com/v1", 12345): MagicMock(),
        ("https://other.com/v1", 67890): MagicMock(),
    }
    p._http_clients = []

    p.invalidate_cache_for(base_url="https://api.openai.com/v1", api_key_hash=12345)
    assert ("https://api.openai.com/v1", 12345) not in p._client_cache
    assert ("https://other.com/v1", 67890) in p._client_cache


def test_invalidate_cache_for_missing_entry_is_noop():
    """No-op when there's nothing to invalidate."""
    OpenAIProvider = _load_real_openai_provider()

    p = OpenAIProvider.__new__(OpenAIProvider)
    p.default_client = None
    p._client_cache = {}
    p._http_clients = []

    p.invalidate_cache_for(base_url="nope", api_key_hash=None)  # must not raise


def test_invalidate_cache_for_base_url_clears_all_matching():
    """invalidate_cache_for_base_url removes every entry for the given base_url."""
    OpenAIProvider = _load_real_openai_provider()

    p = OpenAIProvider.__new__(OpenAIProvider)
    p.default_client = None
    p._client_cache = {
        ("https://a.com/v1", 1): "x",
        ("https://a.com/v1", 2): "y",
        ("https://b.com/v1", 3): "z",
    }
    p._http_clients = []

    p.invalidate_cache_for_base_url("https://a.com/v1")
    assert ("https://a.com/v1", 1) not in p._client_cache
    assert ("https://a.com/v1", 2) not in p._client_cache
    assert ("https://b.com/v1", 3) in p._client_cache


# --- 402 / insufficient credits handling -----------------------------------


class _Status402Error(Exception):
    """Mimics openai.APIStatusError for HTTP 402 (status_code attribute)."""

    status_code = 402

    def __init__(self):
        super().__init__("Error code: 402 - insufficient quota")


class _Message402Error(Exception):
    """402 surfaced only in the message text (no status_code attribute)."""

    def __init__(self):
        super().__init__(
            "Error code: 402 - {'error': {'message': 'This request requires "
            "more credits, or fewer max_tokens.'}}"
        )


class _OtherError(Exception):
    pass


def _provider_with_failing_client(exc):
    OpenAIProvider = _load_real_openai_provider()
    p = OpenAIProvider.__new__(OpenAIProvider)
    p.default_client = None
    client = MagicMock()
    client.chat.completions.create.side_effect = exc
    return p, client


def _run_call(p, client):
    return asyncio.run(
        p._call_openai("sys", "usr", {"name": "x"}, "Analysis", model="m", client=client)
    )


def test_call_openai_raises_insufficient_credits_on_402_status():
    """A 402 with status_code is mapped to LLMInsufficientCreditsError."""
    from src.exceptions.processing import LLMInsufficientCreditsError

    p, client = _provider_with_failing_client(_Status402Error())
    with pytest.raises(LLMInsufficientCreditsError):
        _run_call(p, client)


def test_call_openai_raises_insufficient_credits_on_402_message():
    """A 402 detected only from the message is still mapped to the typed error."""
    from src.exceptions.processing import LLMInsufficientCreditsError

    p, client = _provider_with_failing_client(_Message402Error())
    with pytest.raises(LLMInsufficientCreditsError):
        _run_call(p, client)


def test_call_openai_reraises_non_credit_errors_unchanged():
    """Unrelated errors propagate as-is (not masked as a credits error)."""
    p, client = _provider_with_failing_client(_OtherError("boom"))
    with pytest.raises(_OtherError):
        _run_call(p, client)
