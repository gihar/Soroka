"""Сверка ответа модели с ключами брифа системного шаблона (#113).

Строгая схема — обещание, а не гарантия: модель может ответить успехом и
валидным JSON, молча выбросив схему (замер ADR-0007). Раньше валидатор
сверялся с переменными шаблона и только писал в лог, поэтому потеря раздела
была молчаливой. Здесь закрепляем: набор ключей ответа сверяется с ключами
брифа — тем же источником, из которого строятся строгая схема и правила
промпта.
"""

import types
from unittest.mock import AsyncMock

from src.models.validation import BriefConformance
from src.services.admin_alerts import build_brief_mismatch_alert
from src.services.brief_compiler import brief_protocol_keys
from src.services.protocol_briefs import get_brief_for
from src.services.protocol_validator import ProtocolValidator

_STANDARD = "Стандартный протокол встречи"


def _validator() -> ProtocolValidator:
    return ProtocolValidator()


def _full_response(template_name: str = _STANDARD) -> dict:
    """Ответ модели, покрывающий бриф целиком (значения — непустые строки)."""
    brief = get_brief_for(template_name)
    return {key: f"содержимое поля {key}" for key in brief_protocol_keys(brief)}


# ==========================================================================
# Трассирующий тест: потерянный раздел назван поимённо
# ==========================================================================

def test_missing_section_key_is_reported():
    """Модель не вернула ключ секции → расхождение называет его."""
    response = _full_response()
    del response["decisions"]

    conformance = _validator().check_brief_conformance(response, _STANDARD)

    assert not conformance.matches
    assert "decisions" in conformance.missing_keys


# ==========================================================================
# Полный ответ: расхождения нет, служебные поля генератора его не создают
# ==========================================================================

def test_full_response_matches_the_brief():
    """Ответ покрывает бриф целиком → расхождения нет."""
    conformance = _validator().check_brief_conformance(_full_response(), _STANDARD)

    assert conformance.matches
    assert conformance.missing_keys == ()
    assert conformance.unexpected_keys == ()


def test_generator_service_fields_are_not_a_mismatch():
    """Служебные поля генератора (_meeting_type и пр.) — не ключи протокола."""
    response = {
        **_full_response(),
        "_meeting_type": "status",
        "_speaker_mapping": {"SPEAKER_1": "Иван"},
        "_analysis_confidence": 0.8,
        "_quality_score": 0.9,
    }

    assert _validator().check_brief_conformance(response, _STANDARD).matches


# ==========================================================================
# Бесшумный отказ: модель приняла схему и вернула собственный набор ключей
# ==========================================================================

def test_dropped_schema_shows_up_as_missing_and_unexpected_keys():
    """Ответ со своими ключами вместо заказанных → расхождение в обе стороны."""
    conformance = _validator().check_brief_conformance(
        {"summary": "Обсудили бюджет", "todo": "Подготовить смету"}, _STANDARD
    )

    assert not conformance.matches
    assert conformance.unexpected_keys == ("summary", "todo")
    assert "decisions" in conformance.missing_keys
    assert conformance.template_name == _STANDARD


# ==========================================================================
# Кастомный шаблон: брифа нет — сверять не с чем
# ==========================================================================

def test_custom_template_has_nothing_to_compare_with():
    """У кастомного шаблона брифа нет → сверки не происходит."""
    validator = _validator()

    assert validator.check_brief_conformance({"any": "value"}, "Мой шаблон") is None
    assert validator.check_brief_conformance({"any": "value"}, None) is None


# ==========================================================================
# Полнота: у системного шаблона ожидаемые поля — ключи брифа, у кастомного —
# переменные шаблона (как сегодня)
# ==========================================================================

_TRANSCRIPT = "Обсудили бюджет, сроки и решения по проекту."


def test_full_brief_response_has_no_missing_fields():
    """Полный по брифу ответ не порождает недостающих полей.

    Переменные шаблона несут meeting_date/meeting_time, которых модель не
    возвращает никогда: по ним полный ответ вечно числился неполным.
    """
    result = _validator().calculate_quality_score(
        protocol=_full_response(),
        transcription=_TRANSCRIPT,
        template_variables={"meeting_date": "", "meeting_time": "", "discussion": ""},
        template_name=_STANDARD,
    )

    assert result.missing_fields == []
    assert result.completeness_score == 1.0


def test_custom_template_completeness_still_counts_template_variables():
    """Кастомный шаблон (брифа нет) проверяется по переменным шаблона, как сегодня."""
    result = _validator().calculate_quality_score(
        protocol={"discussion": "Обсудили бюджет и сроки проекта."},
        transcription=_TRANSCRIPT,
        template_variables={"discussion": "", "action_items": ""},
        template_name="Мой шаблон",
    )

    assert result.missing_fields == ["action_items"]


# ==========================================================================
# Точка вызова: расхождение доходит до метрик обработки и до администраторов,
# а не только до лога — иначе потеря раздела остаётся молчаливой
# ==========================================================================

async def _run_generation(monkeypatch, *, protocol_body, template_name):
    """Гоняет optimized_llm_generation → (метрики, вызовы уведомления, вызовы генерации)."""
    import src.services.processing.llm_generation as llm_gen
    from src.llm import protocol_generator as generator
    from src.models.processing import ProcessingRequest, TranscriptionResult

    generate_calls = []

    async def fake_generate(**kwargs):
        generate_calls.append(kwargs)
        return {**protocol_body, "_meeting_type": "status"}

    monkeypatch.setattr(generator, "generate", fake_generate)
    monkeypatch.setattr(
        llm_gen, "resolve_active_preset",
        AsyncMock(return_value={"name": "Qwen Plus", "model": "qwen3.7-plus", "key": "qwen"}),
    )
    monkeypatch.setattr(llm_gen.settings, "enable_protocol_validation", True)
    monkeypatch.setattr(llm_gen.settings, "log_cache_metrics", False)

    notify = AsyncMock()
    monkeypatch.setattr(llm_gen, "notify_brief_mismatch", notify)

    service = llm_gen.LLMGenerationService(
        user_service=None,
        template_service=types.SimpleNamespace(
            extract_template_variables=lambda content: ["discussion", "decisions"]
        ),
    )
    metrics = types.SimpleNamespace()
    await service.optimized_llm_generation(
        TranscriptionResult(transcription=_TRANSCRIPT),
        {"name": template_name, "content": ""},
        ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1),
        metrics,
    )
    return metrics, notify, generate_calls


async def test_mismatch_reaches_metrics_and_admins(monkeypatch):
    """Потерянный раздел попадает в метрики обработки и в уведомление админам."""
    body = _full_response()
    del body["decisions"]

    metrics, notify, _ = await _run_generation(
        monkeypatch, protocol_body=body, template_name=_STANDARD
    )

    assert metrics.protocol_brief_mismatch is True
    notify.assert_awaited_once()
    conformance = notify.await_args.args[0]
    assert "decisions" in conformance.missing_keys
    # Алерт обязан называть модель: пресетов несколько, виноват конкретный.
    assert notify.await_args.kwargs["model_name"] == "Qwen Plus"


async def test_full_response_alerts_nobody(monkeypatch):
    """Полный по брифу ответ не порождает ни расхождения в метриках, ни уведомления."""
    metrics, notify, _ = await _run_generation(
        monkeypatch, protocol_body=_full_response(), template_name=_STANDARD
    )

    assert metrics.protocol_brief_mismatch is False
    notify.assert_not_awaited()


async def test_mismatch_does_not_trigger_a_repair_call(monkeypatch):
    """Ремонтного повторного вызова к модели нет (ADR-0007): генерация ровно одна."""
    body = _full_response()
    del body["decisions"]

    _, _, generate_calls = await _run_generation(
        monkeypatch, protocol_body=body, template_name=_STANDARD
    )

    assert len(generate_calls) == 1


# ==========================================================================
# Текст и доставка алерта: администратору нужно знать, какой шаблон, какая
# модель и каких полей не хватило
# ==========================================================================

_MISMATCH = BriefConformance(
    template_name=_STANDARD,
    missing_keys=("decisions", "action_items"),
    unexpected_keys=("summary",),
)


def test_alert_names_template_model_and_keys():
    text = build_brief_mismatch_alert(_MISMATCH, model_name="Qwen Plus")

    assert _STANDARD in text
    assert "Qwen Plus" in text
    assert "decisions, action_items" in text
    assert "summary" in text


def test_alert_omits_the_empty_side_of_the_mismatch():
    """Только недостающие поля → строки о лишних в тексте нет."""
    text = build_brief_mismatch_alert(
        BriefConformance(template_name=_STANDARD, missing_keys=("decisions",)),
        model_name="Qwen Plus",
    )

    assert "Не пришли: decisions" in text
    assert "Лишние" not in text


async def test_alert_goes_to_every_admin(monkeypatch):
    import src.utils.telegram_safe as telegram_safe
    from src.services import admin_alerts

    sent = []

    async def fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram_safe, "safe_send_message", fake_send)
    monkeypatch.setattr(admin_alerts, "_get_alert_bot", lambda: object())
    monkeypatch.setattr(admin_alerts.settings, "admins", [111, 222])

    await admin_alerts.notify_brief_mismatch(_MISMATCH, model_name="Qwen Plus")

    assert [chat_id for chat_id, _ in sent] == [111, 222]
    assert all("decisions" in text for _, text in sent)


async def test_empty_admin_list_is_survivable(monkeypatch):
    """Список ADMINS пуст → уведомлять некого, но обработка не падает."""
    from src.services import admin_alerts

    monkeypatch.setattr(admin_alerts.settings, "admins", [])

    await admin_alerts.notify_brief_mismatch(_MISMATCH, model_name=None)
