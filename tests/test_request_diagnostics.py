"""Диагностика реквизитов встречи: компактно и без ложных тревог.

Прод, 27.07.2026: 6 из 18 WARNING за двое суток — это `participants_list: None
(НЕ ПЕРЕДАН!)` на **необязательном** поле. Отладочная инструментация кричала об
исправном сценарии и вытесняла из логов настоящие проблемы, а те же поля
логировались трижды за запрос пятью копиями одного блока.
"""
from loguru import logger

from src.utils.request_diagnostics import log_meeting_inputs


def _capture(level: str, fn):
    records = []
    sink_id = logger.add(
        lambda m: records.append(m.record["message"]), level=level, format="{message}"
    )
    try:
        fn()
    finally:
        logger.remove(sink_id)
    return records


def test_absent_optional_fields_are_not_a_warning():
    """Встреча без участников — нормальный сценарий, не повод для WARNING."""
    warnings = _capture("WARNING", lambda: log_meeting_inputs("очередь"))
    assert warnings == []


def test_absent_fields_logged_once_and_compactly():
    infos = _capture("INFO", lambda: log_meeting_inputs("очередь"))
    assert len(infos) == 1, "одна строка на запрос, а не двенадцать"
    assert "не заданы" in infos[0]
    assert "НЕ ПЕРЕДАН" not in infos[0]


def test_present_fields_summarised_in_one_line():
    infos = _capture("INFO", lambda: log_meeting_inputs(
        "callback",
        participants_list=[{"name": "Иван"}, {"name": "Анна"}, {"name": "Пётр"}],
        meeting_topic="Планёрка",
        meeting_date="27.07.2026",
        meeting_agenda="1. Бюджет",
    ))

    assert len(infos) == 1
    line = infos[0]
    assert "callback" in line
    assert "участники: 3" in line
    assert "Планёрка" in line
    assert "27.07.2026" in line
    assert "повестка" in line
    # Незаданные поля не перечисляются — строка несёт только факты.
    assert "project_list" not in line


def test_speaker_mapping_reported_when_known():
    infos = _capture("INFO", lambda: log_meeting_inputs(
        "обработка", speaker_mapping={"SPEAKER_00": "Иван Петров"},
    ))
    assert "сопоставление: 1" in infos[0]


def test_no_debug_instrumentation_left_in_handlers():
    """Пять копий блока сведены к вызову helper'а — крик из прода не вернётся."""
    import inspect

    import src.handlers.callbacks.processing_callbacks as pc
    import src.handlers.message_handlers as mh
    import src.services.processing.processing_service as ps

    for module in (pc, mh, ps):
        src_text = inspect.getsource(module)
        assert "НЕ ПЕРЕДАН" not in src_text, module.__name__
        assert "НЕ ПОПАЛ В REQUEST" not in src_text, module.__name__
