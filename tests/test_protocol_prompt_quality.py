"""Качество протокола: что именно уходит модели (#127).

Шов — генерация протокола с подменённым SDK провайдера (тот же, что у
характеризации промптов генерации): тест видит системный и пользовательский
промпты обоих этапов. Качество ответа модели здесь не доказывается — только то,
какие правила и данные модель получила.
"""

from test_generation_prompts_characterization import capture

UNLABELED = "Добрый день, начнём. Да, по плану релиз в пятницу, я возьму проверку."


def _generation(captured) -> dict:
    return captured["calls"][-1]


# ---------------------------------------------------------------------------
# #130: старая запись истории без меток спикеров
# ---------------------------------------------------------------------------


async def test_unlabeled_text_with_stored_mapping_warns_the_model(monkeypatch):
    """Текст без меток + сохранённое сопоставление: модель не приписывает реплики.

    Так перегенерируются записи, сохранённые до #130: сопоставление есть, меток
    в тексте нет. Блок «SPEAKER_1 = Имя» привязать не к чему — вместо него имена
    идут как участники, а модель предупреждена.
    """
    captured = await capture("type_and_mapping", monkeypatch, transcript=UNLABELED)
    user = _generation(captured)["user"]

    assert "SPEAKER_1 =" not in user
    assert "Алексей Тимченко" in user and "Анна Смирнова" in user
    assert "нет меток спикеров" in user
    assert "не приписывай" in user


async def test_labeled_text_keeps_the_speakers_block(monkeypatch):
    captured = await capture("type_and_mapping", monkeypatch)
    user = _generation(captured)["user"]

    assert "SPEAKER_1 = Алексей Тимченко" in user
    assert "нет меток спикеров" not in user


# ---------------------------------------------------------------------------
# #128: версия промпта
# ---------------------------------------------------------------------------


async def _version(case_id, monkeypatch, **kwargs) -> str:
    captured = await capture(case_id, monkeypatch, full_result=True, **kwargs)
    return captured["llm_result"]["_prompt_version"]


async def test_prompt_version_ignores_the_meeting_itself(monkeypatch):
    """Одинаковые шаблон и тип, разные записи — одна версия; другой тип — другая."""
    plain = await _version("type_and_mapping", monkeypatch)
    other_meeting = await _version("type_and_mapping", monkeypatch, transcript="SPEAKER_1: Другое.")
    business = await _version("everything_analysis_skipped", monkeypatch)

    assert plain and plain == other_meeting
    # Тип встречи меняет специфику в промпте — это другая версия
    assert business != plain


async def test_prompt_version_changes_with_any_rule(monkeypatch):
    import src.prompts.prompts as prompts

    before = await _version("type_without_mapping", monkeypatch)
    monkeypatch.setitem(prompts.FIELD_SPECIFIC_RULES, "decisions", "decisions — другое правило")
    after_rule = await _version("type_without_mapping", monkeypatch)

    assert before != after_rule


# ---------------------------------------------------------------------------
# #131: ответственные и безымянные спикеры
# ---------------------------------------------------------------------------

THREE_SPEAKERS = (
    "SPEAKER_1: Начнём.\nSPEAKER_2: Я возьму проверку.\nSPEAKER_3: А я подготовлю отчёт."
)


async def test_owner_rule_never_asks_to_clarify(monkeypatch):
    """«Отв.: уточнить» терял, кто взял задачу: теперь — имя, «Участник N» или «не назначен»."""
    captured = await capture("brief_template_with_participants", monkeypatch)
    system = _generation(captured)["system"]

    assert "уточнить" not in system
    assert "Отв.: Участник N" in system
    assert "Отв.: не назначен" in system


def test_owner_rule_is_one_rule_for_every_task_field():
    from src.prompts.prompts import FIELD_SPECIFIC_RULES, OWNER_RULE

    for key in ("tasks", "tasks_od", "action_items"):
        assert OWNER_RULE in FIELD_SPECIFIC_RULES[key], key
        assert "уточнить" not in FIELD_SPECIFIC_RULES[key], key


async def test_generation_knows_participants_and_roles(monkeypatch):
    """Анализ пропущен — а участники с ролями всё равно доходят до генерации."""
    captured = await capture("everything_analysis_skipped", monkeypatch)
    user = _generation(captured)["user"]

    assert [c["schema"] for c in captured["calls"]] == ["ProtocolDataSchema"]
    assert "Алексей Тимченко (Руководитель)" in user  # канон «Имя Фамилия» с ролью
    assert "Борис" in user  # промолчавший участник тоже в списке


async def test_generation_names_the_unnamed_speakers(monkeypatch):
    captured = await capture("type_and_mapping", monkeypatch, transcript=THREE_SPEAKERS)
    user = _generation(captured)["user"]

    assert "SPEAKER_3" in user.split("<transcription>")[0]
    assert "Участник 3" in user
