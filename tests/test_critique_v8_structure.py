"""Критика v8: структурный дедуп секций и дисциплина шапки/рисков.

Живые протоколы 365–367: «Следующие шаги» дублируют «Задачи» парафразом в 100%
свежих status-прогонов (дословных дублей 0 — правило «дословно не повторяй»
бессильно по построению). Решение владельца: схлопнуть next_steps в задачи для
«Стандартного» и «Краткого резюме» (сроки живут внутри задач); Дейли не
трогаем. Плюс: additive-правила ужесточены до запрета пересказа, участники —
без маркеров списка, ярлык риска обязательно жирный, пустые строки шапки
схлопываются детерминированно.
"""

from src.prompts.prompts import FIELD_SPECIFIC_RULES
from src.services.brief_compiler import brief_to_template_content
from src.services.protocol_briefs import get_brief_for
from src.utils.text_processing import squeeze_blank_lines

# ---------------------------------------------------------------------------
# Брифы: next_steps схлопнут в задачи для Стандартного и Краткого резюме
# ---------------------------------------------------------------------------


def _section_keys(template_name: str) -> set[str]:
    return {s.key for s in get_brief_for(template_name).sections}


def test_standard_brief_has_no_next_steps():
    assert "next_steps" not in _section_keys("Стандартный протокол встречи")


def test_brief_summary_has_no_next_steps():
    assert "next_steps" not in _section_keys("Краткое резюме встречи")


def test_daily_keeps_next_steps():
    # Дейли не трогаем: материала по нему в критике v8 не было.
    assert "next_steps" in _section_keys("Дейли")


def test_compiled_content_drops_next_steps_section():
    for name in ("Стандартный протокол встречи", "Краткое резюме встречи"):
        content = brief_to_template_content(get_brief_for(name))
        assert "next_steps" not in content, name
        assert "Следующие шаги" not in content, name


# ---------------------------------------------------------------------------
# Правила полей: additive ужесточён до запрета пересказа; шапка и риски
# ---------------------------------------------------------------------------


def test_summary_sections_forbid_paraphrase_repetition():
    # «Дословно не повторяй» ловит только verbatim; дубли v8 — парафраз.
    for key in ("key_points", "next_steps"):
        rule = FIELD_SPECIFIC_RULES[key]
        assert "пересказ" in rule.lower(), key


def test_key_points_rule_demands_only_new_information():
    rule = FIELD_SPECIFIC_RULES["key_points"]
    assert "нет в других секциях" in rule


def test_participants_rule_forbids_list_markers():
    rule = FIELD_SPECIFIC_RULES["participants"]
    assert "без маркер" in rule.lower()


def test_risks_rule_requires_bold_type_label():
    rule = FIELD_SPECIFIC_RULES["risks_and_blockers"]
    assert "**Риск/Блокер**" in rule
    assert "жирн" in rule.lower()


# ---------------------------------------------------------------------------
# Пустые строки: детерминированное схлопывание (3+ переводов строки → 2)
# ---------------------------------------------------------------------------


def test_blank_runs_collapse_to_one_empty_line():
    assert squeeze_blank_lines("Шапка\n\n\n\n## Секция") == "Шапка\n\n## Секция"


def test_single_blank_line_untouched():
    text = "Шапка\n\n## Секция"
    assert squeeze_blank_lines(text) == text


def test_fenced_blank_lines_preserved():
    text = "```\nстрока\n\n\n\nещё\n```"
    assert squeeze_blank_lines(text) == text


def test_squeeze_idempotent():
    once = squeeze_blank_lines("a\n\n\n\nb")
    assert squeeze_blank_lines(once) == once


def test_squeeze_tolerates_unclosed_fence():
    # Незакрытый фенс: остаток текста считается кодом и не трогается.
    text = "a\n```\nкод\n\n\n\nещё"
    assert squeeze_blank_lines(text) == text


def test_brief_summary_exact_schema_keys():
    # Паритет с exact-keys тестом Стандартного (test_brief_compiler).
    from src.services.brief_compiler import brief_to_schema

    props = brief_to_schema(get_brief_for("Краткое резюме встречи"))["schema"][
        "properties"
    ]["protocol_data"]["properties"]
    assert set(props) == {
        "meeting_title",
        "date",
        "time",
        "participants",
        "decisions",
        "action_items",
        "key_points",
    }


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_md_download_from_history_squeezes_blank_runs(monkeypatch):
    # Протоколы, сохранённые ДО фикса, скачиваются как .md без лишних пустых строк.
    from src.services import result_sender

    captured = []

    async def fake_send_document(bot, chat_id, **kwargs):
        input_file = kwargs["document"]
        with open(input_file.path, "rb") as f:
            captured.append(f.read().decode("utf-8"))
        return object()

    monkeypatch.setattr(result_sender, "safe_send_document", fake_send_document)

    ok = await result_sender.send_protocol_file(
        object(), 1, "# Титул\n\n\n\n## ✅ Решения\n1. Пункт\n", "a.mp3", "file",
    )

    assert ok is True
    assert "\n\n\n" not in captured[0]
    assert "# Титул\n\n## ✅ Решения" in captured[0]


@pytest.mark.asyncio
async def test_completion_tail_squeezes_blank_runs():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.models.processing import ProcessingRequest, TranscriptionResult
    from src.services.processing.completion import CompletionDeps, complete_processing

    deps = CompletionDeps(
        llm_gen=SimpleNamespace(
            optimized_llm_generation=AsyncMock(return_value={"meeting_title": "Планёрка"}),
            resolve_model_display_name=AsyncMock(return_value="GPT"),
        ),
        formatter=SimpleNamespace(
            format_protocol=lambda *a, **k: "# Титул\n\n\n\n## ✅ Решения\n1. Пункт\n"
        ),
        history=SimpleNamespace(
            save_processing_history=AsyncMock(return_value=42),
            cleanup_temp_file=AsyncMock(),
        ),
    )

    async def delivery(result):
        return True

    outcome = await complete_processing(
        request=ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=delivery,
    )

    assert "\n\n\n" not in outcome.result.protocol_text
    assert "# Титул\n\n## ✅ Решения" in outcome.result.protocol_text
