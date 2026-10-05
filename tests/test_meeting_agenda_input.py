"""Повестка и проекты: введённое пользователем доходит до запроса на обработку.

Ввод повестки и проектов жил в отдельном меню; кнопку входа в него убрали при
упрощении настройки (1b3582d), а оставшийся без входа код удалили как мёртвый
(критика v11). Адаптер запуска при этом продолжал читать ``protocol_info``,
который больше никто не писал, — повестка и проекты уходили в запрос пустыми,
хотя генерация умеет ими пользоваться.

Теперь ввод — одна кнопка на экране «Участники встречи»: одно сообщение,
проекты — строкой «Проекты: …». Ключи состояния — как у темы и даты встречи.
"""

from types import SimpleNamespace

from src.handlers.callbacks.processing_callbacks import launch_input_from_state


def _state_data(**extra):
    return {"template_id": 0, "file_id": "TG", "file_name": "a.mp3", **extra}


def test_agenda_and_projects_from_dialog_reach_the_launch():
    _, choice = launch_input_from_state(
        _state_data(meeting_agenda="1. Статус релиза", project_list="Сорока")
    )

    assert choice.meeting.agenda == "1. Статус релиза"
    assert choice.meeting.projects == "Сорока"


def test_no_agenda_in_dialog_means_none():
    _, choice = launch_input_from_state(_state_data())

    assert (choice.meeting.agenda, choice.meeting.projects) == (None, None)


# ---------------------------------------------------------------------------
# Одно сообщение → повестка и проекты
# ---------------------------------------------------------------------------


def test_plain_text_is_the_agenda():
    from src.services.meeting_agenda import split_agenda_and_projects

    assert split_agenda_and_projects("1. Статус релиза\n2. Риски") == (
        "1. Статус релиза\n2. Риски", None,
    )


def test_projects_line_is_split_off():
    from src.services.meeting_agenda import split_agenda_and_projects

    text = "1. Статус релиза\n2. Риски\nПроекты: Сорока, Детский мир"

    assert split_agenda_and_projects(text) == ("1. Статус релиза\n2. Риски", "Сорока, Детский мир")


def test_projects_may_follow_on_their_own_lines():
    from src.services.meeting_agenda import split_agenda_and_projects

    text = "Итоги квартала\n\nпроекты:\nСорока\nДетский мир"

    assert split_agenda_and_projects(text) == ("Итоги квартала", "Сорока\nДетский мир")


def test_projects_only():
    from src.services.meeting_agenda import split_agenda_and_projects

    assert split_agenda_and_projects("Проекты — Сорока") == (None, "Сорока")


def test_blank_message_gives_nothing():
    from src.services.meeting_agenda import split_agenda_and_projects

    assert split_agenda_and_projects("  \n ") == (None, None)


# ---------------------------------------------------------------------------
# Экран «Участники встречи» → ввод повестки → обратно на экран
# ---------------------------------------------------------------------------


def _participants_screen():
    """Тестовые принадлежности экрана участников (FakeState, показ меню)."""
    import test_participants_entry_v11 as screen

    return screen


async def test_participants_screen_offers_agenda_input(monkeypatch):
    screen = _participants_screen()

    _, markup, _ = await screen._show(monkeypatch)

    assert "add_meeting_agenda" in screen._datas(markup)


def _handler(kind: str, name: str):
    import src.handlers.participants_handlers as ph

    router = ph.setup_participants_handlers()
    observer = getattr(router, kind)
    return next(h.callback for h in observer.handlers if h.callback.__name__ == name)


async def test_agenda_button_opens_the_input_step(monkeypatch):
    from unittest.mock import AsyncMock

    import src.handlers.participants_handlers as ph
    from src.handlers.participants_states import ParticipantsInput

    screen = _participants_screen()
    sent = {}

    async def fake_answer(message, text, **kwargs):
        sent["text"] = text
        sent["markup"] = kwargs.get("reply_markup")

    monkeypatch.setattr(ph, "safe_answer", fake_answer)
    state = screen.FakeState(state=ParticipantsInput.waiting_for_participants)
    callback = SimpleNamespace(answer=AsyncMock(), message=screen._message())

    await _handler("callback_query", "prompt_agenda_input")(callback, state)

    assert await state.get_state() == ParticipantsInput.waiting_for_agenda
    assert "Проекты:" in sent["text"]  # формат строки проектов объяснён
    assert "input_new_participants" in screen._datas(sent["markup"])  # путь назад


async def _send_agenda(monkeypatch, text):
    import src.handlers.participants_handlers as ph
    from src.handlers.participants_states import ParticipantsInput

    screen = _participants_screen()
    sent = []

    async def fake_answer(message, body, **kwargs):
        sent.append(body)
        return SimpleNamespace(message_id=777, chat=SimpleNamespace(id=42))

    monkeypatch.setattr(ph, "safe_answer", fake_answer)
    monkeypatch.setattr(
        ph, "UserService", lambda: screen._user_service(),
    )
    state = screen.FakeState(state=ParticipantsInput.waiting_for_agenda, data={"file_id": "TG"})
    message = screen._message()
    message.text = text

    await _handler("message", "handle_agenda_text")(message, state)
    return state, sent


async def test_agenda_message_is_saved_for_the_launch(monkeypatch):
    from src.handlers.participants_states import ParticipantsInput

    state, sent = await _send_agenda(
        monkeypatch, "1. Статус релиза\n2. Риски\nПроекты: Сорока",
    )
    data = await state.get_data()

    assert data["meeting_agenda"] == "1. Статус релиза\n2. Риски"
    assert data["project_list"] == "Сорока"
    assert data["file_id"] == "TG"  # запись в состоянии не задета
    # Обратно на экран «Участники встречи»: он и есть следующий шаг настройки.
    assert await state.get_state() == ParticipantsInput.waiting_for_participants
    assert any("Участники встречи" in body for body in sent)
    # И до запуска повестка доезжает тем же адаптером.
    _, choice = launch_input_from_state({**data, "template_id": 0, "file_name": "a.mp3"})
    assert (choice.meeting.agenda, choice.meeting.projects) == (
        "1. Статус релиза\n2. Риски", "Сорока",
    )


async def test_blank_agenda_message_keeps_the_input_step(monkeypatch):
    from src.handlers.participants_states import ParticipantsInput

    state, sent = await _send_agenda(monkeypatch, "   ")

    assert await state.get_state() == ParticipantsInput.waiting_for_agenda
    assert "meeting_agenda" not in await state.get_data()
    assert sent  # пользователь узнал, что повторить
