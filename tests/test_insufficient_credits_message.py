"""Голос отказа при исчерпании кредитов LLM (HTTP 402).

Требование прежнее: пользователю говорят, что это временный сбой на нашей
стороне, не показывают сырой payload провайдера (в нём user_id) и не советуют
прислать файл поменьше — с другим файлом это не лечится.

Проверяется живой путь. Раньше тесты целились в ``_format_error_message`` и
``_get_error_recommendation`` воркера; первый уходил только в лог, второй слал
пользователю ВТОРОЙ пузырь с литеральными `**звёздочками**`. Оба удалены
(критика v10), и требование теперь держит ``error_presentation`` — единственный
источник пользовательского текста об ошибке.
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

from src.services import error_presentation  # noqa: E402

# Raw OpenRouter 402 payload as it appears in str(exception) — note the user_id.
RAW_402 = (
    "Error code: 402 - {'error': {'message': 'This request requires more credits, "
    "or fewer max_tokens. You requested up to 16384 tokens, but can only afford "
    "6109.', 'code': 402}, 'user_id': 'user_2lpA5W2gt60hAGWIkHfhzCdz90y'}"
)


def test_credits_failure_does_not_leak_payload():
    msg = error_presentation.processing_failure_message("Анализ", RAW_402)
    low = msg.lower()
    assert "user_id" not in low
    assert "max_tokens" not in low


def test_credits_failure_is_not_generic_retry():
    msg = error_presentation.processing_failure_message("Анализ", RAW_402).lower()
    # Совет «попробуйте другой файл» на нехватку кредитов замыкает круг.
    assert "другой файл" not in msg
    assert "поменьше" not in msg


def test_typed_credits_exception_is_routed_the_same_way():
    from src.exceptions.processing import LLMInsufficientCreditsError

    exc = LLMInsufficientCreditsError(RAW_402, provider="openai", model="gpt-5")
    msg = error_presentation.processing_failure_message("Анализ", str(exc))
    assert "user_id" not in msg.lower()
    # Ветка «наша вина» обязана отличаться от совета про файл.
    assert "формат" not in msg.lower()


def test_unrelated_errors_keep_their_own_step():
    msg = error_presentation.processing_failure_message("Анализ", "Файл слишком большой")
    assert "кредит" not in msg.lower()
