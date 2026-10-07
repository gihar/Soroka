"""Качество протокола: что именно уходит модели (#127).

Шов — генерация протокола с подменённым SDK провайдера (тот же, что у
характеризации промптов генерации): тест видит системный и пользовательский
промпты обоих этапов. Качество ответа модели здесь не доказывается — только то,
какие правила и данные модель получила.
"""

import re

import pytest
import test_generation_prompts_characterization as characterization
from test_generation_prompts_characterization import capture

from src.prompts.prompts import FIELD_SPECIFIC_RULES
from src.services import protocol_briefs
from src.services.brief_compiler import brief_protocol_keys

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


# ---------------------------------------------------------------------------
# #132: анализ называет спикеров по наблюдаемым основаниям
# ---------------------------------------------------------------------------


async def _analysis(monkeypatch) -> dict:
    captured = await capture("everything_with_analysis", monkeypatch)
    analysis = captured["calls"][0]
    assert analysis["schema"] == "MeetingAnalysisSchema"
    return analysis


async def test_analysis_has_no_confidence_threshold(monkeypatch):
    """Схема анализа не несёт уверенности по спикеру — порог «≥ 0.7» был непроверяем."""
    analysis = await _analysis(monkeypatch)
    prompt = analysis["system"] + analysis["user"]

    assert "0.7" not in prompt
    assert "веренность" not in prompt


async def test_analysis_names_speakers_only_on_observable_grounds(monkeypatch):
    analysis = await _analysis(monkeypatch)
    prompt = analysis["system"] + analysis["user"]

    assert "по имени" in prompt  # обращение: «Иван, сделаешь?»
    assert "представился" in prompt
    assert "роль" in prompt  # однозначное совпадение с ролью из списка
    assert "unmapped_speakers" in prompt  # без основания — несопоставлен


async def test_analysis_states_type_logic_once(monkeypatch):
    analysis = await _analysis(monkeypatch)

    combined = analysis["system"] + analysis["user"]
    assert combined.count("доминирующ") == 1
    # Инструкция генерации, к анализу не относящаяся
    assert "цифры, даты" not in analysis["system"]


# ---------------------------------------------------------------------------
# #133: правила согласованы с брифом шаблона
# ---------------------------------------------------------------------------

BRIEFS = [
    b for b in vars(protocol_briefs).values() if isinstance(b, protocol_briefs.ProtocolBrief)
]


async def _brief_generation(brief, monkeypatch, meeting_type="business") -> dict:
    case = f"brief:{brief.template_name}"
    monkeypatch.setitem(
        characterization.CASES, case,
        ({"speaker_mapping": characterization.MAPPING}, meeting_type,
         {"name": brief.template_name, "content": "{{ meeting_title }}"}),
    )
    return _generation(await capture(case, monkeypatch))


@pytest.mark.parametrize("brief", BRIEFS, ids=lambda b: b.template_name)
async def test_rules_mention_only_sections_of_the_template(brief, monkeypatch):
    """Правило «перенеси в issues» при шаблоне без issues — пункт теряется или ложится не туда."""
    system = (await _brief_generation(brief, monkeypatch))["system"]

    mentioned = set(re.findall(r"\b[a-z_]+\b", system)) & set(FIELD_SPECIFIC_RULES)
    assert mentioned <= set(brief_protocol_keys(brief))


def _brief(name):
    return next(b for b in BRIEFS if b.template_name == name)


async def test_key_points_leave_risks_to_the_risk_section(monkeypatch):
    system = (await _brief_generation(_brief("Стандартный протокол встречи"), monkeypatch))["system"]
    key_points = system.split("key_points —", 1)[1].split("\n\n", 1)[0]

    carries = key_points.split("чего нет в других секциях (", 1)[1].split(")", 1)[0]
    assert "риск" not in carries  # риски не в перечне того, что несут выводы
    assert "НЕ переноси сюда риски и блокеры" in key_points


async def test_lecture_has_one_attribution_rule(monkeypatch):
    """Лекция — конспект без атрибуции: общий принцип «кто что сказал» ей не противоречит."""
    system = (await _brief_generation(_brief("Лекция и презентация"), monkeypatch, "educational"))["system"]

    assert "кроме образовательных" in system


@pytest.mark.parametrize("meeting_type", ["technical", "business", "brainstorm", "status", "management"])
async def test_type_specifics_fit_the_template(meeting_type, monkeypatch):
    """Специфика типа не требует разделов, которых в шаблоне нет."""
    user = (await _brief_generation(_brief("Стандартный протокол встречи"), monkeypatch, meeting_type))["user"]
    specifics = user.split("СПЕЦИФИКА", 1)[1].split("<transcription>", 1)[0]

    for demand in ("Выделяй выбранные идеи отдельно", "Планы на следующие периоды",
                   "Статус исполнения ранее данных поручений", "Директивные решения дословно",
                   "Ответственные лица и их роли"):
        assert demand not in specifics


def test_meeting_title_prefers_the_users_topic():
    assert "Тема встречи" in FIELD_SPECIFIC_RULES["meeting_title"]


# ---------------------------------------------------------------------------
# #134: контракт ответа без балласта
# ---------------------------------------------------------------------------


async def test_answer_schema_carries_only_the_protocol(monkeypatch):
    """Самооценка, «использованный контекст» и сомнения модели никто не читал.

    Только системные шаблоны (бриф-схема, 73 из 86 протоколов прода): корень
    legacy-схемы без мета-полей остался бы без required — строгий режим
    провайдеров на нём не проверен.
    """
    captured = await capture("brief_template_with_participants", monkeypatch, full_result=True)
    generation_schema = captured["schemas"][-1]

    assert set(generation_schema["properties"]) == {"protocol_data"}
    assert generation_schema["additionalProperties"] is False
    assert "_quality_score" not in captured["llm_result"]


async def test_fields_list_has_no_empty_descriptions_or_phantom_keys(monkeypatch):
    user = _generation(await capture("type_and_mapping", monkeypatch))["user"]
    fields = user.split("<fields>", 1)[1].split("</fields>", 1)[0]

    assert not re.search(r"^- \w+: *$", fields, re.MULTILINE)
    assert "meeting_date" not in fields and "meeting_time" not in fields
    assert "- date" in fields and "- time" in fields


# ---------------------------------------------------------------------------
# #135: обсуждение и риски без дублей
# ---------------------------------------------------------------------------


def _rule(system: str, key: str) -> str:
    rules = system.split("ПРАВИЛА ДЛЯ ПОЛЕЙ:", 1)[1]
    return rules.split(f"\n{key} —", 1)[1].split("\n\n", 1)[0]


async def test_discussion_ends_with_the_last_topic(monkeypatch):
    """В 16 из 40 длинных протоколов обсуждение кончалось «Итогами», пересказывая задачи."""
    system = (await _brief_generation(_brief("Стандартный протокол встречи"), monkeypatch))["system"]
    discussion = _rule(system, "discussion")

    assert "блоком итогов" in discussion
    assert "Процедурные реплики" in discussion
    assert "АБСОЛЮТНАЯ ПОЛНОТА" in discussion  # полнота тем не снижается


async def test_risks_are_not_open_questions(monkeypatch):
    """Раздел рисков был заполнен в 37 из 37 и пересказывал «Открытые вопросы»."""
    system = (await _brief_generation(_brief("Стандартный протокол встречи"), monkeypatch))["system"]
    risks = _rule(system, "risks_and_blockers")

    assert "может сорваться" in risks
    assert "открытых вопросов" in risks  # вопрос без ответа — не риск
    assert "если он прозвучал" in risks  # план снижения не выдумывается
    assert "оставь поле пустым" in risks


async def test_speechmatics_labels_keep_attribution(monkeypatch):
    """Speechmatics держит родные метки S1/S2 — это тоже метки, атрибуция сохраняется.

    Ревью: проверка «есть ли метки» знала только SPEAKER_N, и запись Speechmatics
    с известным сопоставлением получала запрет приписывать реплики.
    """
    monkeypatch.setitem(
        characterization.CASES, "speechmatics",
        ({"speaker_mapping": {"S1": "Алексей Тимченко"}}, "business",
         characterization.CUSTOM_TEMPLATE),
    )
    captured = await capture(
        "speechmatics", monkeypatch, transcript="S1: Начнём.\n\nS2: Я возьму проверку.",
    )
    user = _generation(captured)["user"]

    assert "S1 = Алексей Тимченко" in user
    assert "нет меток спикеров" not in user
    assert "S2 → Участник 2" in user
