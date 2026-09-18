"""Отказ провайдера доходит до администратора — с обоих путей и без диагноза.

Прод 08–15.09.2026: пятнадцать ударов в стену, ноль уведомлений. Причин было
две, и классификация — меньшая из них.

Первая: решение «уведомить админов» жило в одном месте — в ``except`` воркера
очереди. Но задача, вставшая на карточке сопоставления, из воркера уходит
(``paused = True; return``), и дальше её ведёт коллбэк. Четырнадцать сбоев из
пятнадцати случились там, где уведомлять было некому. Опознай мы ошибку
идеально, админ всё равно не узнал бы ничего.

Вторая: алерт уходил, только если сбой опознан как кредиты или квота. Всё
незнакомое падало молча, сколько бы задач ни сгорело. Поэтому под известными
классами появилась сетка: отказ провайдера, не подошедший ни под один класс и не
похожий на временный сбой, сам по себе повод написать администратору.

Автовозврат сетка не запускает: диагноза у незнакомого отказа нет по
определению, а «тихо переехать на случайного провайдера хуже, чем постоять»
(ADR-0007).
"""

from unittest.mock import AsyncMock

import pytest

RAW_403 = (
    "Error code: 403 - {'error': {'type': 'AccessDenied.Unpurchased', "
    "'message': 'Access to model denied.'}}"
)
RAW_UNKNOWN = (
    "Error code: 451 - {'error': {'message': 'Model unavailable in your region'}}"
)


@pytest.fixture
def sent(monkeypatch):
    """Перехват доставки алертов: тексты без похода в Telegram."""
    import src.utils.telegram_safe as telegram_safe
    from src.config import settings
    from src.services import admin_alerts

    delivered = AsyncMock()
    monkeypatch.setattr(telegram_safe, "safe_send_message", delivered)
    monkeypatch.setattr(admin_alerts, "_get_alert_bot", lambda: object())
    monkeypatch.setattr(settings, "admins", [111])
    return delivered


@pytest.fixture
def presets(monkeypatch, test_db, app_settings_repo):
    """Репозитории реакции — на временной базе теста; два включённых пресета."""
    import src.database as database
    from src.database.model_preset_repo import ModelPresetRepository

    preset_repo = ModelPresetRepository(test_db)
    monkeypatch.setattr(database, "app_settings_repo", app_settings_repo)
    monkeypatch.setattr(database, "model_preset_repo", preset_repo)
    return app_settings_repo, preset_repo


async def _two_presets(presets):
    settings_repo, preset_repo = presets
    await preset_repo.upsert(key="wall", name="Qwen: max", model="qwen3.8-max", base_url="q")
    await preset_repo.upsert(
        key="reserve", name="OpenRouter: gpt-5-mini", model="gpt-5-mini", base_url="o"
    )
    await settings_repo.set_active_model_key("wall", admin_id=42)
    return settings_repo


def _texts(sent):
    return [str(call.args[2]) for call in sent.await_args_list]


# ------------------------------------------------- сетка под незнакомым отказом


async def test_an_unknown_provider_refusal_reaches_the_admin(sent):
    """Главный урок инцидента: незнакомое больше не падает молча."""
    from src.services import provider_failure

    await provider_failure.report_llm_failure(RuntimeError(RAW_UNKNOWN))

    body = _texts(sent)[0]
    assert "451" in body
    assert "лог" in body.lower()


async def test_a_transient_api_error_is_not_an_incident(sent):
    """Таймауты и rate limit — обычная жизнь провайдера, а не событие для админа."""
    from src.services import provider_failure

    for text in (
        "Error code: 429 - rate limited",
        "Request timeout after 600s",
        "Connection reset by peer",
    ):
        await provider_failure.report_llm_failure(RuntimeError(text))

    assert sent.await_count == 0


async def test_a_failure_that_is_not_the_providers_stays_out_of_the_net(sent):
    """Сетка ловит отказы провайдера, а не битые файлы и нехватку памяти.

    Реакция вызывается из общей ветки сбоя, куда приходит что угодно: сожми
    сетку шире — и админ получит поток жалоб на чужие mp4.
    """
    from src.services import provider_failure

    for text in (
        "moov atom not found",
        "Файл слишком большой",
        "Критическое использование памяти: 99.4%",
    ):
        await provider_failure.report_llm_failure(RuntimeError(text))

    assert sent.await_count == 0


async def test_an_unknown_refusal_does_not_move_the_active_preset(sent, presets):
    """Диагноза нет — переезд на догадке уведёт с рабочего провайдера."""
    settings_repo = await _two_presets(presets)
    await settings_repo.set_fallback_model_key("reserve", admin_id=42)

    from src.services import provider_failure

    await provider_failure.report_llm_failure(RuntimeError(RAW_UNKNOWN))

    assert await settings_repo.get_active_model_key() == "wall"
    assert sent.await_count == 1  # но написать админу — написали


async def test_known_classes_keep_their_own_alerts(sent):
    """Сетка — остаток, а не замена: опознанное идёт своей веткой."""
    from src.services import provider_failure

    await provider_failure.report_llm_failure(
        RuntimeError("Error code: 402 - requires more credits")
    )

    body = _texts(sent)[0]
    assert "кредит" in body.lower()
    assert "лог" not in body.lower()


# ------------------------------------------ второй путь: возобновление после паузы


def _service():
    """Сервис обработки без запуска: нужен только его обработчик сбоя."""
    from src.services.processing.processing_service import ProcessingService

    return ProcessingService.__new__(ProcessingService)


async def test_a_failure_after_the_mapping_pause_also_reaches_the_admin(sent, monkeypatch):
    """Четырнадцать сбоев из пятнадцати шли здесь — и не уведомляли никого."""
    import src.services.processing.processing_service as processing_service
    from src.exceptions.processing import LLMAccessNotPurchasedError

    monkeypatch.setattr(processing_service, "safe_send_message", AsyncMock())

    with pytest.raises(Exception):
        await _service()._handle_resume_failure(
            LLMAccessNotPurchasedError(RAW_403, provider="openai", model="qwen3.8-max"),
            user_id=1, chat_id=2, bot=object(), task_id=None,
        )

    assert sent.await_count == 1
    assert "подписк" in _texts(sent)[0].lower()


async def test_the_user_still_hears_about_it_before_the_admin_does(sent, monkeypatch):
    """Уведомление админов — добавка к сообщению пользователю, а не замена."""
    import src.services.processing.processing_service as processing_service

    to_user = AsyncMock()
    monkeypatch.setattr(processing_service, "safe_send_message", to_user)

    with pytest.raises(Exception):
        await _service()._handle_resume_failure(
            RuntimeError(RAW_403), user_id=1, chat_id=2, bot=object(), task_id=None,
        )

    assert to_user.await_count == 1
    assert "файл менять не нужно" in str(to_user.await_args.kwargs["text"])


async def test_a_broken_alert_does_not_swallow_the_failure(sent, monkeypatch):
    """Уведомление админов best-effort: его сбой не отменяет ProcessingError."""
    import src.services.processing.processing_service as processing_service
    from src.services import provider_failure

    monkeypatch.setattr(processing_service, "safe_send_message", AsyncMock())
    monkeypatch.setattr(
        provider_failure, "report_llm_failure",
        AsyncMock(side_effect=RuntimeError("telegram down")),
    )

    from src.exceptions.processing import ProcessingError

    with pytest.raises(ProcessingError):
        await _service()._handle_resume_failure(
            RuntimeError(RAW_403), user_id=1, chat_id=2, bot=object(), task_id=None,
        )


# ------------------------------------------------ резерв, которого не назначили


async def test_the_alert_says_when_there_is_no_reserve_at_all(sent, presets):
    """Прод стоял 11 дней с незаданным резервом — админ об этом ниоткуда не узнавал."""
    settings_repo = await _two_presets(presets)

    from src.services import provider_failure

    await provider_failure.report_llm_failure(RuntimeError(RAW_403))

    assert await settings_repo.get_active_model_key() == "wall"
    body = _texts(sent)[0]
    assert "резервный пресет не задан" in body.lower()


async def test_a_configured_reserve_is_used_and_named(sent, presets):
    """Резерв задан — бот переезжает сам, и алерт говорит куда."""
    settings_repo = await _two_presets(presets)
    await settings_repo.set_fallback_model_key("reserve", admin_id=42)

    from src.services import provider_failure

    await provider_failure.report_llm_failure(RuntimeError(RAW_403))

    assert await settings_repo.get_active_model_key() == "reserve"
    body = _texts(sent)[0]
    assert "OpenRouter: gpt-5-mini" in body
    assert "резервный пресет не задан" not in body.lower()


# ------------------------------------- карточка не спорит с сообщением под ней


async def test_the_card_takes_its_text_from_the_classifier(monkeypatch):
    """Карточка врала «отправьте заново», пока сообщение под ней звало ждать.

    Из-за этого человек 15.09 нажимал «повторить» одиннадцать раз подряд.
    """
    from src.handlers.callbacks import speaker_mapping_callbacks as callbacks

    edited = AsyncMock()
    monkeypatch.setattr(callbacks, "safe_edit_text", edited)

    @callbacks.card_handler(on_error="edit")
    async def failing_core(callback, callback_data, state, user_id, session):
        raise RuntimeError(RAW_403)

    class _Data:
        user_id = 7

    class _Callback:
        from_user = type("U", (), {"id": 7})()
        message = object()

        async def answer(self, *args, **kwargs):
            return None

    await failing_core(_Callback(), _Data(), None)

    text = str(edited.await_args.args[1])
    assert "повторная попытка помогает" not in text
    assert "файл менять не нужно" in text
