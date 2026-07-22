"""Критика v6: дисциплина полей генерации (правила промпта).

Живые протоколы прода 355–361 вскрыли не вёрстку, а наполнение полей:
дубли-клоны задач по числу ответственных, «Участник N» как ответственный,
утечка капс-словаря «РЕШЕНО», межсекционный повтор. Правила полей —
единственный рычаг: тексты из FIELD_SPECIFIC_RULES едут в системный промпт
(и легаси-путь, и бриф-путь через section.instruction).
"""

from src.prompts.prompts import FIELD_SPECIFIC_RULES, build_generation_system_prompt

# Поля-поручения: одна работа = один пункт, владельцы перечислением, канон «Отв.:».
_OWNER_FIELDS = ("action_items", "tasks", "tasks_od")


# ---------------------------------------------------------------------------
# Слияние владельцев: одна работа — ОДИН пункт, клонирование запрещено
# ---------------------------------------------------------------------------

def test_owner_fields_forbid_cloning_per_assignee():
    for key in _OWNER_FIELDS:
        rule = FIELD_SPECIFIC_RULES[key]
        assert "ОДИН пункт" in rule, key
        # Перечисление владельцев показано образцом.
        assert "Илья, Мария" in rule, key
        # Явный запрет дублирования пункта под каждого исполнителя.
        assert "дублируй" in rule.lower(), key


# ---------------------------------------------------------------------------
# «Участник N» как ответственный: несопоставленную метку не назначать
# ---------------------------------------------------------------------------

def test_owner_fields_forbid_unmapped_label_as_owner():
    for key in _OWNER_FIELDS:
        rule = FIELD_SPECIFIC_RULES[key]
        assert "Участник" in rule, key
        assert "уточнить" in rule, key


# ---------------------------------------------------------------------------
# Унификация подписи ответственного: канон «Отв.:», не «Ответственный:»
# ---------------------------------------------------------------------------

def test_owner_fields_use_otv_canon():
    for key in _OWNER_FIELDS:
        rule = FIELD_SPECIFIC_RULES[key]
        assert "Отв.:" in rule, key
        assert "Ответственный:" not in rule, key


# ---------------------------------------------------------------------------
# «РЕШЕНО»-утечка: капс-словарь классификатора не диктуется, префиксы запрещены
# ---------------------------------------------------------------------------

def test_decisions_rule_drops_caps_classifier_vocabulary():
    rule = FIELD_SPECIFIC_RULES["decisions"]
    # Капс-слова классификатора утекали дословно в артефакты (3/5 живых).
    for caps in ("РЕШЕНО", "ОБСУЖДАЛОСЬ", "ПРЕДЛОЖЕНО"):
        assert caps not in rule


def test_decisions_rule_keeps_decided_only_semantics():
    rule = FIELD_SPECIFIC_RULES["decisions"]
    # Семантика «только утверждённое» сохранена без провоцирующего капса.
    assert "утвердили" in rule
    assert "НЕ включай" in rule


def test_decisions_rule_forbids_status_prefixes_in_output():
    rule = FIELD_SPECIFIC_RULES["decisions"]
    # Заголовок ✅ Решения уже несёт смысл — маркер-префиксы в выводе запрещены.
    assert "заголовок секции" in rule.lower()


# ---------------------------------------------------------------------------
# Межсекционный дедуп: Выводы и Шаги — только additive к Решениям/Задачам
# ---------------------------------------------------------------------------

def test_summary_sections_forbid_verbatim_repetition():
    for key in ("key_points", "next_steps"):
        rule = FIELD_SPECIFIC_RULES[key]
        assert "дословно" in rule.lower(), key
        assert "не повторяй" in rule.lower(), key


# ---------------------------------------------------------------------------
# ASR-нормализация: очевидные фонетические искажения терминов — к канону
# ---------------------------------------------------------------------------

def test_system_prompt_normalizes_asr_term_distortions():
    prompt = build_generation_system_prompt()
    assert "cutover" in prompt.lower()  # образец канона («котовер» → cutover)
    assert "искажени" in prompt.lower()  # инструкция про искажения распознавания
    # Не поощряем выдумывание — только очевидные искажения.
    assert "не выдумывай" in prompt.lower()


# ---------------------------------------------------------------------------
# Peak-end: заметки-ловушка завершают существом, а не ограничением системы
# ---------------------------------------------------------------------------

def test_additional_notes_ends_on_substance_not_limitation():
    rule = FIELD_SPECIFIC_RULES["additional_notes"]
    # Живой 357 (ОД) заканчивался «поддерживать список вручную» — слабый финал
    # документа поручений. Правило требует завершать существом решения.
    assert "контрольная точка" in rule.lower()
    # Ограничение не должно стоять последним пунктом.
    assert "ограничени" in rule.lower()
    assert "последн" in rule.lower()
