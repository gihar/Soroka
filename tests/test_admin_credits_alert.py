"""Admin alerting when the LLM provider runs out of credits (HTTP 402).

On a credits outage every queued task fails, so admins must be told — but only
once per throttle window, otherwise they'd be flooded with one alert per task.
"""
import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))


def _mgr(bot=None):
    from src.services.task_queue_manager import TaskQueueManager

    m = TaskQueueManager.__new__(TaskQueueManager)
    m.bot = bot if bot is not None else object()
    m._last_credits_alert_at = None
    return m


def _credits_exc():
    from src.exceptions.processing import LLMInsufficientCreditsError

    return LLMInsufficientCreditsError(
        "Error code: 402 - requires more credits", provider="openai", model="gpt-5"
    )


def test_alert_sent_to_every_admin(monkeypatch):
    import src.utils.telegram_safe as ts
    from config import settings

    sent = AsyncMock()
    monkeypatch.setattr(ts, "safe_send_message", sent)
    monkeypatch.setattr(settings, "admins", [111, 222])

    mgr = _mgr()
    asyncio.run(mgr._notify_admins_insufficient_credits(_credits_exc()))

    assert sent.await_count == 2
    recipients = {call.args[1] for call in sent.await_args_list}
    assert recipients == {111, 222}
    body = str(sent.await_args_list[0].args[2]).lower()
    assert "кредит" in body and "402" in body


def test_repeated_alerts_are_throttled(monkeypatch):
    import src.utils.telegram_safe as ts
    from config import settings

    sent = AsyncMock()
    monkeypatch.setattr(ts, "safe_send_message", sent)
    monkeypatch.setattr(settings, "admins", [111])

    mgr = _mgr()
    mgr._last_credits_alert_at = datetime.now()  # just alerted → must stay silent
    asyncio.run(mgr._notify_admins_insufficient_credits(_credits_exc()))

    assert sent.await_count == 0


def test_no_admins_configured_is_noop(monkeypatch):
    import src.utils.telegram_safe as ts
    from config import settings

    sent = AsyncMock()
    monkeypatch.setattr(ts, "safe_send_message", sent)
    monkeypatch.setattr(settings, "admins", [])

    mgr = _mgr()
    asyncio.run(mgr._notify_admins_insufficient_credits(_credits_exc()))  # must not raise

    assert sent.await_count == 0
