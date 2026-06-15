"""User-facing messaging when the LLM provider runs out of credits (HTTP 402).

The worker must tell the user it's a temporary service-side issue and must NOT
leak the raw provider payload (which includes a user_id) nor advise sending a
smaller/different file — retrying with another file does not help.
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

# Raw OpenRouter 402 payload as it appears in str(exception) — note the user_id.
RAW_402 = (
    "Error code: 402 - {'error': {'message': 'This request requires more credits, "
    "or fewer max_tokens. You requested up to 16384 tokens, but can only afford "
    "6109.', 'code': 402}, 'user_id': 'user_2lpA5W2gt60hAGWIkHfhzCdz90y'}"
)


def _mgr():
    # Метод форматирования не использует __init__ — создаём инстанс без него.
    from src.services.task_queue_manager import TaskQueueManager

    return TaskQueueManager.__new__(TaskQueueManager)


def test_format_error_message_detects_credits_and_does_not_leak():
    msg = _mgr()._format_error_message(RAW_402)
    low = msg.lower()
    assert "недоступ" in low  # "сервис временно недоступен"
    assert "user_id" not in low
    assert "max_tokens" not in low


def test_recommendation_for_credits_is_not_generic_retry():
    rec = _mgr()._get_error_recommendation(RAW_402)
    low = rec.lower()
    assert "кредит" in low or "ресурс" in low
    # Generic advice ("try a different file") is wrong for a credits outage.
    assert "другой файл" not in low


def test_typed_credits_exception_message_is_routed():
    from src.exceptions.processing import LLMInsufficientCreditsError

    exc = LLMInsufficientCreditsError(RAW_402, provider="openai", model="gpt-5")
    assert "недоступ" in _mgr()._format_error_message(str(exc)).lower()


def test_unrelated_errors_keep_generic_handling():
    rec = _mgr()._get_error_recommendation("Файл слишком большой")
    assert "кредит" not in rec.lower()
