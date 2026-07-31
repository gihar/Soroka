"""Критика v11: экраны перестали обещать то, чего не делают.

Три независимых случая с одним корнем — интерфейс утверждает, а код не
выполняет:

- «Настройки сброшены • Шаблон по умолчанию сброшен • Другие настройки
  восстановлены» — сбрасывался только режим вывода протокола;
- меню команд обещает «/feedback — Написать разработчику», а написать было
  негде: диалог заканчивался цифрой, поле comment никто не заполнял;
- экран «Загрузите файл с участниками .txt или .csv» имел обработчик, но тот
  недостижим: media_handler ловит документы без фильтра состояния и включён
  раньше, а .txt не входит в SUPPORTED_DOCUMENT_EXTENSIONS.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.handlers.callbacks.settings_callbacks as sc
import src.ux.feedback_system as fs


class FakeState:
    def __init__(self, state=None, data=None):
        self._state = state
        self._data = dict(data or {})

    async def get_state(self):
        return self._state

    async def set_state(self, state):
        self._state = state

    async def update_data(self, **values):
        self._data.update(values)
        return self._data

    async def get_data(self):
        return dict(self._data)

    async def clear(self):
        self._state = None
        self._data = {}


def _callback(data="x"):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=42), answer=AsyncMock(),
        ),
        answer=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# Сброс настроек делает то, о чём отчитывается
# ---------------------------------------------------------------------------


def _reset_handler(user_service):
    router = sc.setup_settings_callbacks(
        user_service=user_service, template_service=MagicMock(),
        processing_service=MagicMock(),
    )
    return next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "settings_reset_callback"
    )


@pytest.mark.asyncio
async def test_reset_clears_every_setting_it_claims(monkeypatch):
    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text

    monkeypatch.setattr(sc, "safe_edit_text", fake_edit)
    reset_template = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "src.database.user_repo.reset_default_template", reset_template,
        raising=False,
    )

    user_service = SimpleNamespace(
        update_user_protocol_output_preference=AsyncMock(),
        update_speaker_mapping_preference=AsyncMock(),
    )
    await _reset_handler(user_service)(_callback("settings_reset"))

    user_service.update_user_protocol_output_preference.assert_awaited_once()
    user_service.update_speaker_mapping_preference.assert_awaited_once()
    reset_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_reports_only_what_happened(monkeypatch):
    """Если что-то не сбросилось — не отчитываться об этом."""
    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text

    monkeypatch.setattr(sc, "safe_edit_text", fake_edit)
    monkeypatch.setattr(
        "src.database.user_repo.reset_default_template",
        AsyncMock(side_effect=RuntimeError("БД недоступна")), raising=False,
    )

    user_service = SimpleNamespace(
        update_user_protocol_output_preference=AsyncMock(),
        update_speaker_mapping_preference=AsyncMock(),
    )
    await _reset_handler(user_service)(_callback("settings_reset"))

    assert "Шаблон по умолчанию" not in captured["text"]


@pytest.mark.asyncio
async def test_reset_survives_a_total_failure(monkeypatch):
    async def fake_edit(message, text, **kwargs):
        pass

    monkeypatch.setattr(sc, "safe_edit_text", fake_edit)
    monkeypatch.setattr(
        "src.database.user_repo.reset_default_template",
        AsyncMock(side_effect=RuntimeError("нет")), raising=False,
    )
    user_service = SimpleNamespace(
        update_user_protocol_output_preference=AsyncMock(side_effect=RuntimeError("нет")),
        update_speaker_mapping_preference=AsyncMock(side_effect=RuntimeError("нет")),
    )

    await _reset_handler(user_service)(_callback("settings_reset"))  # не падает


# ---------------------------------------------------------------------------
# /feedback принимает текст
# ---------------------------------------------------------------------------


def _fb_handler(name: str, collector=None):
    router = fs.setup_feedback_handlers(collector or MagicMock())
    for observer in (router.callback_query, router.message):
        for h in observer.handlers:
            if h.callback.__name__ == name:
                return h.callback
    raise AssertionError(f"хендлер {name} не зарегистрирован")


@pytest.mark.asyncio
async def test_bug_report_asks_for_text_right_away(monkeypatch):
    """Серьёзность бага пользователем не калибруется — нужен текст, не цифра."""
    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text

    monkeypatch.setattr(fs, "safe_edit_text", fake_edit)
    state = FakeState()

    await _fb_handler("handle_feedback_type")(
        _callback("feedback_type_bug_report"), state
    )

    from src.handlers.participants_states import FeedbackInput

    assert await state.get_state() == FeedbackInput.waiting_for_comment
    assert "опишите" in captured["text"].lower()


@pytest.mark.asyncio
async def test_rating_types_still_ask_for_a_rating(monkeypatch):
    async def fake_edit(message, text, **kwargs):
        pass

    monkeypatch.setattr(fs, "safe_edit_text", fake_edit)
    state = FakeState()

    await _fb_handler("handle_feedback_type")(
        _callback("feedback_type_protocol_quality"), state
    )

    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_rating_is_followed_by_a_question(monkeypatch):
    """После цифры продукт наконец спрашивает, что именно не так."""
    async def fake_edit(message, text, **kwargs):
        pass

    monkeypatch.setattr(fs, "safe_edit_text", fake_edit)
    state = FakeState()

    await _fb_handler("handle_rating")(
        _callback("feedback_rating_protocol_quality_3"), state
    )

    from src.handlers.participants_states import FeedbackInput

    assert await state.get_state() == FeedbackInput.waiting_for_comment


@pytest.mark.asyncio
async def test_comment_reaches_the_collector(monkeypatch):
    collected = []
    collector = SimpleNamespace(add_feedback=collected.append)
    state = FakeState(data={"feedback_type": "bug_report", "feedback_rating": None})
    message = SimpleNamespace(
        text="Кнопка PDF ничего не делает",
        from_user=SimpleNamespace(id=42),
        answer=AsyncMock(),
    )

    await _fb_handler("receive_feedback_comment", collector)(message, state)

    assert len(collected) == 1
    assert collected[0].comment == "Кнопка PDF ничего не делает"
    assert collected[0].feedback_type == "bug_report"


@pytest.mark.asyncio
async def test_comment_closes_the_dialog(monkeypatch):
    collector = SimpleNamespace(add_feedback=lambda entry: None)
    state = FakeState(data={"feedback_type": "suggestion"})
    message = SimpleNamespace(
        text="Добавьте экспорт в Notion",
        from_user=SimpleNamespace(id=42), answer=AsyncMock(),
    )

    await _fb_handler("receive_feedback_comment", collector)(message, state)

    assert await state.get_state() is None
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_rating_is_kept_together_with_the_comment():
    collected = []
    collector = SimpleNamespace(add_feedback=collected.append)
    state = FakeState(data={"feedback_type": "protocol_quality", "feedback_rating": 4})
    message = SimpleNamespace(
        text="Секция решений отличная, задачи теряются",
        from_user=SimpleNamespace(id=42), answer=AsyncMock(),
    )

    await _fb_handler("receive_feedback_comment", collector)(message, state)

    assert collected[0].rating == 4


@pytest.mark.asyncio
async def test_skipping_the_comment_still_saves_the_rating(monkeypatch):
    async def fake_edit(message, text, **kwargs):
        pass

    monkeypatch.setattr(fs, "safe_edit_text", fake_edit)
    collected = []
    collector = SimpleNamespace(add_feedback=collected.append)
    state = FakeState(data={"feedback_type": "protocol_quality", "feedback_rating": 5})

    await _fb_handler("skip_feedback_comment", collector)(
        _callback("feedback_comment_skip"), state
    )

    assert collected and collected[0].rating == 5
    assert collected[0].comment is None
    assert await state.get_state() is None


def test_feedback_prompt_offers_a_way_out():
    keyboard = fs.FeedbackUI.create_comment_keyboard()
    datas = {b.callback_data for row in keyboard.inline_keyboard for b in row}
    assert "feedback_comment_skip" in datas


# ---------------------------------------------------------------------------
# Экран загрузки файла с участниками
# ---------------------------------------------------------------------------


def test_file_upload_screen_is_gone():
    """Экран обещал .txt/.csv, а media_handler забирал документы раньше."""
    import inspect

    import src.handlers.participants_handlers as ph

    source = inspect.getsource(ph)
    assert "upload_participants_file" not in source


def test_txt_is_still_not_an_accepted_media_format():
    """Обратная сторона: снятое обещание не должно превратиться в новое."""
    from src.services.file_service import FileService

    assert ".txt" not in FileService.SUPPORTED_DOCUMENT_EXTENSIONS


def test_participants_can_still_be_sent_as_text():
    """Способ передать список никуда не делся — он стал единственным."""
    import inspect

    import src.handlers.participants_handlers as ph

    source = inspect.getsource(ph.show_participants_menu)
    assert "по одному на строку" in source


# ---------------------------------------------------------------------------
# Отзыв без оценки должен доезжать до БД
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feedback_without_a_rating_reaches_the_database(tmp_path):
    """«Сообщить об ошибке» пишет rating=None — схема обязана это принять."""
    from src.database.database import Database
    from src.database.feedback_repo import FeedbackRepository

    db = Database(str(tmp_path / "bot.db"))
    await db.init_db()
    repo = FeedbackRepository(db)

    await repo.save_feedback(
        user_id=42, rating=None, feedback_type="bug_report",
        comment="Кнопка PDF ничего не делает",
    )

    rows = await repo.get_all_feedback()
    assert rows[0]["comment"] == "Кнопка PDF ничего не делает"
    assert rows[0]["rating"] is None


@pytest.mark.asyncio
async def test_migration_relaxes_an_existing_not_null_column(tmp_path):
    """На старой БД NOT NULL снимается перестройкой, данные переезжают."""
    import aiosqlite

    from src.database.database import Database

    path = str(tmp_path / "bot.db")
    async with aiosqlite.connect(path) as raw:
        await raw.execute("""
            CREATE TABLE feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                feedback_type TEXT NOT NULL,
                comment TEXT,
                protocol_id TEXT,
                processing_time REAL,
                file_format TEXT,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await raw.execute(
            "INSERT INTO feedback (user_id, rating, feedback_type, comment) "
            "VALUES (1, 5, 'protocol_quality', 'старый отзыв')"
        )
        await raw.commit()

    await Database(path).init_db()

    async with aiosqlite.connect(path) as raw:
        raw.row_factory = aiosqlite.Row
        cursor = await raw.execute("PRAGMA table_info(feedback)")
        rating = next(c for c in await cursor.fetchall() if c["name"] == "rating")
        assert not rating["notnull"], "NOT NULL обязан быть снят"

        cursor = await raw.execute("SELECT comment, rating FROM feedback")
        rows = await cursor.fetchall()
        assert [(r["comment"], r["rating"]) for r in rows] == [("старый отзыв", 5)]


@pytest.mark.asyncio
async def test_migration_runs_once(tmp_path):
    from src.database.database import Database

    path = str(tmp_path / "bot.db")
    db = Database(path)
    await db.init_db()
    await db.init_db()  # повторный старт бота — не падает и ничего не теряет

    from src.database.feedback_repo import FeedbackRepository

    await FeedbackRepository(db).save_feedback(
        user_id=1, rating=None, feedback_type="suggestion", comment="идея",
    )
    assert len(await FeedbackRepository(db).get_all_feedback()) == 1
