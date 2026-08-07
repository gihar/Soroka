"""Admin alerting when the LLM provider runs out of credits (HTTP 402).

On a credits outage every queued task fails, so admins must be told — but only
once per throttle window, otherwise they'd be flooded with one alert per task.

Delivery and throttling live in ``src.services.admin_alerts`` (the single admin
channel); the queue worker only decides that the failure is a credits outage.
The text itself is unchanged: топ-ап баланса лечит именно кредиты.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))


def _mgr():
    from src.services.task_queue_manager import TaskQueueManager

    return TaskQueueManager.__new__(TaskQueueManager)


def _credits_exc():
    from src.exceptions.processing import LLMInsufficientCreditsError

    return LLMInsufficientCreditsError(
        "Error code: 402 - requires more credits", provider="openai", model="gpt-5"
    )


def _capture(monkeypatch, admins):
    import src.utils.telegram_safe as ts
    from src.config import settings
    from src.services import admin_alerts

    sent = AsyncMock()
    monkeypatch.setattr(ts, "safe_send_message", sent)
    monkeypatch.setattr(admin_alerts, "_get_alert_bot", lambda: object())
    monkeypatch.setattr(settings, "admins", admins)
    return sent


def test_alert_sent_to_every_admin(monkeypatch):
    sent = _capture(monkeypatch, [111, 222])

    mgr = _mgr()
    asyncio.run(mgr._notify_admins_provider_exhausted(_credits_exc()))

    assert sent.await_count == 2
    recipients = {call.args[1] for call in sent.await_args_list}
    assert recipients == {111, 222}
    body = str(sent.await_args_list[0].args[2]).lower()
    assert "кредит" in body and "402" in body


def test_repeated_alerts_are_throttled(monkeypatch):
    sent = _capture(monkeypatch, [111])

    async def two_incidents():
        mgr = _mgr()
        await mgr._notify_admins_provider_exhausted(_credits_exc())
        await mgr._notify_admins_provider_exhausted(_credits_exc())

    asyncio.run(two_incidents())

    assert sent.await_count == 1  # второе падение в окне — молчание


def test_no_admins_configured_is_noop(monkeypatch):
    sent = _capture(monkeypatch, [])

    mgr = _mgr()
    asyncio.run(mgr._notify_admins_provider_exhausted(_credits_exc()))  # must not raise

    assert sent.await_count == 0
