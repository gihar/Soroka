"""Перманентные Telegram-ошибки (напр. VOICE_MESSAGES_FORBIDDEN) не должны ретраиться."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.reliability.telegram_rate_limiter import is_non_retryable_telegram_error


def test_voice_messages_forbidden_is_non_retryable():
    assert is_non_retryable_telegram_error(
        "Telegram server says - Bad Request: VOICE_MESSAGES_FORBIDDEN"
    ) is True


def test_transient_errors_are_retryable():
    assert is_non_retryable_telegram_error("Bad Request: message text is empty") is False
    assert is_non_retryable_telegram_error("connection reset") is False
    assert is_non_retryable_telegram_error("") is False
