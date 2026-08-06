"""Уведомление админов об исчерпании квоты подписки (#117).

Квота подписки кончается иначе, чем кредиты провайдера, и лечится иначе:
пополнение баланса не помогает — нужен следующий период или другой пресет
(CONTEXT.md). Поэтому у события свой текст, а окно троттлинга считается
отдельно от прочих поводов: квотный инцидент не должен глушить сообщение о
расхождении с брифом.
"""
import os
import sys
from unittest.mock import AsyncMock

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

RAW_QUOTA_429 = (
    "Error code: 429 - {'error': {'code': 'Throttling.AllocationQuota', "
    "'message': 'Free allocated quota exceeded, please increase your quota limit.'}}"
)


def _quota_exc():
    from src.exceptions.processing import LLMQuotaExhaustedError

    return LLMQuotaExhaustedError(RAW_QUOTA_429, provider="openai", model="qwen3.7-plus")


@pytest.fixture
def sent(monkeypatch):
    """Перехват доставки: адресаты и тексты, без похода в Telegram."""
    import src.utils.telegram_safe as telegram_safe
    from src.config import settings
    from src.services import admin_alerts

    delivered = AsyncMock()
    monkeypatch.setattr(telegram_safe, "safe_send_message", delivered)
    monkeypatch.setattr(admin_alerts, "_get_alert_bot", lambda: object())
    monkeypatch.setattr(settings, "admins", [111, 222])
    return delivered


async def test_quota_alert_offers_to_switch_preset(sent):
    """Совет админу — сменить активный пресет; пополнение баланса тут не лечит."""
    from src.services import admin_alerts

    await admin_alerts.notify_quota_exhausted(_quota_exc())

    assert {call.args[1] for call in sent.await_args_list} == {111, 222}
    body = str(sent.await_args_list[0].args[2])
    assert "квот" in body.lower()
    assert "пресет" in body.lower()
    assert "баланс" not in body.lower()
    assert "qwen3.7-plus" in body  # админу видно, какой адрес упёрся в стену


async def test_repeated_quota_incident_is_one_message_in_window(sent):
    """Падает вся очередь — админы получают одно сообщение, а не поток."""
    from src.services import admin_alerts

    await admin_alerts.notify_quota_exhausted(_quota_exc())
    await admin_alerts.notify_quota_exhausted(_quota_exc())

    assert sent.await_count == 2  # одна рассылка на двух админов


async def test_quota_incident_does_not_silence_brief_mismatch(sent):
    """Троттлинг считается по поводу: одно событие не глушит другое."""
    from src.models.validation import BriefConformance
    from src.services import admin_alerts

    await admin_alerts.notify_quota_exhausted(_quota_exc())
    await admin_alerts.notify_brief_mismatch(
        BriefConformance(template_name="Стандартный", missing_keys=("decisions",)),
        model_name="Qwen Plus",
    )

    texts = [str(call.args[2]) for call in sent.await_args_list]
    assert any("квот" in text.lower() for text in texts)
    assert any("decisions" in text for text in texts)


def _worker():
    """Воркер очереди без запуска: нужен только его разбор причины сбоя."""
    from src.services.task_queue_manager import TaskQueueManager

    return TaskQueueManager.__new__(TaskQueueManager)


async def test_worker_routes_quota_failure_to_quota_alert(sent):
    """Упавшая по квоте задача поднимает квотный алерт, а не кредитный."""
    await _worker()._notify_admins_provider_exhausted(_quota_exc())

    body = str(sent.await_args_list[0].args[2])
    assert "квот" in body.lower()
    assert "402" not in body
    assert "баланс" not in body.lower()


async def test_worker_keeps_credits_failure_on_the_credits_alert(sent):
    """Кредиты не переехали в квотную ветку: 402 остаётся кредитами."""
    from src.exceptions.processing import LLMInsufficientCreditsError

    await _worker()._notify_admins_provider_exhausted(
        LLMInsufficientCreditsError(
            "Error code: 402 - requires more credits", provider="openai", model="gpt-5"
        )
    )

    body = str(sent.await_args_list[0].args[2])
    assert "кредит" in body.lower() and "402" in body


async def test_worker_stays_silent_on_unrelated_failures(sent):
    """Сбой не про ресурс провайдера — админам писать не о чем."""
    await _worker()._notify_admins_provider_exhausted(RuntimeError("connection reset"))

    assert sent.await_count == 0
