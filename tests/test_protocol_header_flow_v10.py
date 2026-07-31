"""Критика v10: «Дата и название» — правка шапки после доставки.

Доставка не должна быть точкой невозврата. Дата и титул живут в двух строках
рендера, поэтому их правка не требует ни расшифровки, ни LLM: перезаписываем
шапку сохранённого текста и отдаём протокол заново.

Владение проверяется репозиторием (history_id приходит из callback_data, её
может прислать кто угодно) — тот же контракт, что у «PDF» и «Другой шаблон».
"""


import pytest

from src.services.protocol_header_edit import apply_header_edit
from src.services.result_sender import _protocol_actions_keyboard

_STORED = (
    "# Встреча 30 июля\n"
    "**Дата:** 30 июля 2026\n"
    "\n"
    "## ✅ Решения\n"
    "Запускаем.\n"
)


class FakeHistoryRepo:
    """Репозиторий истории с проверкой владельца, как настоящий."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else {
            (1, 42): {
                "id": 1,
                "file_name": "встреча.mp3",
                "result_text": _STORED,
                "transcription_text": "текст",
            }
        }
        self.updated = []

    async def get_result_for_user(self, history_id, telegram_id):
        return self.rows.get((history_id, telegram_id))

    async def update_result_text(self, history_id, telegram_id, result_text):
        if (history_id, telegram_id) not in self.rows:
            return False
        self.updated.append((history_id, telegram_id, result_text))
        return True


# ---------------------------------------------------------------------------
# Кнопка под доставленным протоколом
# ---------------------------------------------------------------------------


def test_actions_keyboard_offers_header_edit():
    keyboard = _protocol_actions_keyboard(7, "messages")
    labels = [b.text for row in keyboard.inline_keyboard for b in row]
    assert "Дата и название" in labels


def test_header_edit_button_carries_history_id():
    keyboard = _protocol_actions_keyboard(7, "messages")
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "proto_header_7" in data


def test_header_edit_absent_without_history():
    """Без записи истории кнопке не на что ссылаться."""
    assert _protocol_actions_keyboard(None, "messages") is None


def test_existing_actions_survive():
    keyboard = _protocol_actions_keyboard(7, "messages")
    labels = [b.text for row in keyboard.inline_keyboard for b in row]
    assert {"PDF", "Word", "Другой шаблон"} <= set(labels)


# ---------------------------------------------------------------------------
# Применение правки
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_rewrites_date_and_persists():
    repo = FakeHistoryRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="27 июля 2026"
    )

    assert outcome.status == "ok"
    assert "**Дата:** 27 июля 2026" in outcome.protocol_text
    assert repo.updated, "исправленный протокол обязан сохраниться в историю"
    assert "27 июля 2026" in repo.updated[0][2]


@pytest.mark.asyncio
async def test_edit_rewrites_title_from_second_line():
    repo = FakeHistoryRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42,
        raw_input="27 июля 2026\nПланёрка по смете",
    )

    assert outcome.protocol_text.startswith("# Планёрка по смете\n")
    assert outcome.title == "Планёрка по смете"


@pytest.mark.asyncio
async def test_edit_keeps_body_intact():
    repo = FakeHistoryRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="27 июля 2026"
    )

    assert "## ✅ Решения\nЗапускаем." in outcome.protocol_text


@pytest.mark.asyncio
async def test_edit_returns_file_name_for_redelivery():
    repo = FakeHistoryRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="27 июля 2026"
    )

    assert outcome.file_name == "встреча.mp3"


@pytest.mark.asyncio
async def test_foreign_history_id_is_refused():
    """Чужая запись — отказ, и ничего не сохраняется."""
    repo = FakeHistoryRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=999, raw_input="27 июля 2026"
    )

    assert outcome.status == "not_found"
    assert outcome.protocol_text is None
    assert repo.updated == []


@pytest.mark.asyncio
async def test_cleared_history_is_refused():
    repo = FakeHistoryRepo(rows={(1, 42): {"file_name": "a.mp3", "result_text": "  "}})

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="27 июля 2026"
    )

    assert outcome.status == "not_found"


@pytest.mark.asyncio
async def test_empty_input_asks_again_without_touching_history():
    repo = FakeHistoryRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="   "
    )

    assert outcome.status == "empty"
    assert repo.updated == []


@pytest.mark.asyncio
async def test_numeric_date_is_normalized_before_saving():
    """«27.07.2026» рядом с «30 июля 2026» — разнобой в одном документе."""
    repo = FakeHistoryRepo()

    outcome = await apply_header_edit(
        repo, history_id=1, telegram_user_id=42, raw_input="27.07.2026"
    )

    assert "**Дата:** 27 июля 2026" in outcome.protocol_text


@pytest.mark.asyncio
async def test_failed_persist_still_returns_corrected_text():
    """БД могла отказать — пользователь всё равно получает исправленный протокол."""

    class RefusingRepo(FakeHistoryRepo):
        async def update_result_text(self, *args, **kwargs):
            return False

    outcome = await apply_header_edit(
        RefusingRepo(), history_id=1, telegram_user_id=42, raw_input="27 июля 2026"
    )

    assert outcome.status == "ok"
    assert "27 июля 2026" in outcome.protocol_text


# ---------------------------------------------------------------------------
# Приглашение к вводу
# ---------------------------------------------------------------------------


def test_prompt_asks_for_date_and_explains_the_second_line():
    from src.services.protocol_header_edit import HEADER_EDIT_PROMPT

    assert "Когда была встреча" in HEADER_EDIT_PROMPT
    # Пользователь должен узнать про вторую строку, иначе название не поправить.
    assert "названи" in HEADER_EDIT_PROMPT.lower()
