"""Реакция на квотную стену: уведомление админов (#117) и автовозврат (#119).

Квота подписки кончается иначе, чем кредиты провайдера, и лечится иначе:
пополнение баланса не помогает — нужен следующий период или другой пресет
(CONTEXT.md). Поэтому у события свой текст, а окно троттлинга считается
отдельно от прочих поводов: квотный инцидент не должен глушить сообщение о
расхождении с брифом.

Разница доходит и до действий. Активный пресет глобальный, поэтому квотная
стена валит протоколы у всех и держит их до появления администратора — бот
переводит активный пресет на резервный сам. Кредитная стена автовозврат не
запускает: там лечение минутное. Переключается настройка, а не идущий вызов —
фолбэк внутри одного прогона отвергнут в ADR-0007.
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


# ------------------------------------------------ автовозврат активного пресета


@pytest.fixture(autouse=True)
async def presets(monkeypatch, test_db, app_settings_repo):
    """Репозитории воркера — на временной базе теста; два включённых пресета.

    Автоматически на весь файл: реакция на квотную стену теперь ходит в
    настройки приложения за резервным пресетом, и тест про текст уведомления
    должен упираться в ту же базу, что тест про переключение.
    """
    import src.database as database
    from src.database.model_preset_repo import ModelPresetRepository

    preset_repo = ModelPresetRepository(test_db)
    await preset_repo.upsert(
        key="qwen_plus", name="Qwen: plus", model="qwen3.7-plus", base_url="q"
    )
    await preset_repo.upsert(
        key="openrouter", name="OpenRouter: gpt-5-mini", model="gpt-5-mini", base_url="o"
    )
    monkeypatch.setattr(database, "app_settings_repo", app_settings_repo)
    monkeypatch.setattr(database, "model_preset_repo", preset_repo)
    return app_settings_repo


async def test_quota_wall_returns_active_preset_to_the_reserve(sent, presets):
    """Стена у подписки — активный пресет уходит на резервный, бот не лежит."""
    await presets.set_active_model_key("qwen_plus", admin_id=42)
    await presets.set_fallback_model_key("openrouter", admin_id=42)

    await _worker()._notify_admins_provider_exhausted(_quota_exc())

    assert await presets.get_active_model_key() == "openrouter"
    body = str(sent.await_args_list[0].args[2])
    assert "OpenRouter: gpt-5-mini" in body  # админу видно, на что переключились
    # Звать в /models за уже сделанной работой — обещание невыполненного шага.
    assert "смените активный пресет" not in body.lower()


async def test_the_switch_is_journalled_without_a_human_author(sent, presets, test_db):
    """Переключил не человек — в журнале настроек автора нет, а не прежний админ."""
    import aiosqlite

    await presets.set_active_model_key("qwen_plus", admin_id=42)
    await presets.set_fallback_model_key("openrouter", admin_id=42)

    await _worker()._notify_admins_provider_exhausted(_quota_exc())

    async with aiosqlite.connect(test_db.db_path) as db:
        cursor = await db.execute(
            "SELECT updated_by FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
    assert row[0] is None


async def test_without_a_reserve_nothing_switches_but_the_alert_arrives(sent, presets):
    """Резерв не задан — тихо переехать на случайного провайдера хуже, чем постоять."""
    await presets.set_active_model_key("qwen_plus", admin_id=42)

    await _worker()._notify_admins_provider_exhausted(_quota_exc())

    assert await presets.get_active_model_key() == "qwen_plus"
    body = str(sent.await_args_list[0].args[2])
    assert "смените активный пресет" in body.lower()


async def test_reserve_equal_to_the_exhausted_preset_switches_nothing(sent, presets):
    """Резерв совпал с активным — переключать не на что, и обещать нечего."""
    await presets.set_active_model_key("qwen_plus", admin_id=42)
    await presets.set_fallback_model_key("qwen_plus", admin_id=42)

    await _worker()._notify_admins_provider_exhausted(_quota_exc())

    assert await presets.get_active_model_key() == "qwen_plus"
    body = str(sent.await_args_list[0].args[2])
    assert "переключён" not in body.lower()
    assert "смените активный пресет" in body.lower()


async def test_stale_reserve_does_not_switch_and_the_alert_still_arrives(
    sent, presets, test_db
):
    """Резерв выключили после настройки — автовозврату некуда идти, но алерт идёт."""
    from src.database.model_preset_repo import ModelPresetRepository

    await presets.set_active_model_key("qwen_plus", admin_id=42)
    await presets.set_fallback_model_key("openrouter", admin_id=42)
    await ModelPresetRepository(test_db).update_field("openrouter", "is_enabled", 0)

    await _worker()._notify_admins_provider_exhausted(_quota_exc())

    assert await presets.get_active_model_key() == "qwen_plus"
    assert sent.await_count == 2  # сбой автовозврата не съел уведомление
    assert "смените активный пресет" in str(sent.await_args_list[0].args[2]).lower()


async def test_storage_failure_during_switch_does_not_eat_the_alert(
    sent, presets, monkeypatch
):
    """Автовозврат — попытка, а не условие: упал он — уведомление всё равно уходит."""
    async def unavailable():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(presets, "get_fallback_model_key", unavailable)

    await _worker()._notify_admins_provider_exhausted(_quota_exc())

    assert sent.await_count == 2
    assert "квот" in str(sent.await_args_list[0].args[2]).lower()


async def test_credits_exhaustion_leaves_the_active_preset_alone(sent, presets):
    """Кредиты лечатся пополнением за минуту — уводить бота с провайдера незачем."""
    from src.exceptions.processing import LLMInsufficientCreditsError

    await presets.set_active_model_key("qwen_plus", admin_id=42)
    await presets.set_fallback_model_key("openrouter", admin_id=42)

    await _worker()._notify_admins_provider_exhausted(
        LLMInsufficientCreditsError(
            "Error code: 402 - requires more credits", provider="openai", model="gpt-5"
        )
    )

    assert await presets.get_active_model_key() == "qwen_plus"
    assert "баланс" in str(sent.await_args_list[0].args[2]).lower()


async def test_reserve_reaches_the_next_run_not_the_one_that_hit_the_wall(sent, presets):
    """Переключается настройка, а не идущий вызов: упавший прогон остался на своём.

    Прогон к этому моменту уже завершился ошибкой (реакция вызывается из
    ветки сбоя воркера) — модель внутри него не подменяется, резерв достаётся
    следующему обращению за активным пресетом.
    """
    from src.database import model_preset_repo
    from src.services.processing.llm_generation import resolve_active_preset

    await presets.set_active_model_key("qwen_plus", admin_id=42)
    await presets.set_fallback_model_key("openrouter", admin_id=42)

    run_that_hit_the_wall = await resolve_active_preset(presets, model_preset_repo)
    await _worker()._notify_admins_provider_exhausted(_quota_exc())
    next_run = await resolve_active_preset(presets, model_preset_repo)

    assert run_that_hit_the_wall["model"] == "qwen3.7-plus"
    assert next_run["model"] == "gpt-5-mini"
