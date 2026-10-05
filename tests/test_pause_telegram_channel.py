"""Telegram-канал паузы: что именно уходит в чат пользователя.

Модуль паузы говорит с пользователем через канал; здесь проверяется, что
Telegram-адаптер доносит каждое обращение в тот чат, где стоит пауза.
Граница — хелперы Telegram (безопасная отправка, карточка, фрагменты, трекер).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.services.processing.pause_channel import TelegramPauseChannel

BOT = SimpleNamespace(name="бот")


async def test_silencing_stops_autoupdates_and_announces_the_pause(monkeypatch):
    import src.utils.telegram_safe as ts

    edits = []

    async def fake_edit(message, text, **kwargs):
        edits.append((message, text))
        return True

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    async def forever():
        await asyncio.sleep(3600)

    update_task = asyncio.ensure_future(forever())
    tracker = SimpleNamespace(
        update_task=update_task, message=SimpleNamespace(), bot=BOT, chat_id=7,
    )

    await TelegramPauseChannel.from_tracker(tracker).silence_tracker()

    assert tracker.update_task is None
    assert update_task.cancelled()
    assert edits[0][0] is tracker.message
    assert "Транскрипция завершена" in edits[0][1]


async def test_silencing_survives_a_failed_edit(monkeypatch):
    import src.utils.telegram_safe as ts

    monkeypatch.setattr(ts, "safe_edit_text", AsyncMock(side_effect=RuntimeError("edit")))
    tracker = SimpleNamespace(update_task=None, message=object(), bot=BOT, chat_id=7)

    await TelegramPauseChannel.from_tracker(tracker).silence_tracker()


async def test_card_and_previews_go_to_the_pause_chat(monkeypatch):
    import src.ux.speaker_audio_preview as preview
    import src.ux.speaker_mapping_ui as ui

    show = AsyncMock(return_value="карточка")
    previews = AsyncMock(return_value={"SPEAKER_1"})
    monkeypatch.setattr(ui, "show_mapping_confirmation", show)
    monkeypatch.setattr(preview, "send_speaker_audio_previews", previews)
    channel = TelegramPauseChannel(BOT, 7)

    card = await channel.show_card(user_id=1, record_name="a.mp3")
    delivered = await channel.send_previews(user_id=1, speakers=["SPEAKER_1"])

    assert card == "карточка"
    assert delivered == {"SPEAKER_1"}
    assert show.await_args.kwargs["chat_id"] == 7
    assert show.await_args.kwargs["bot"] is BOT
    assert show.await_args.kwargs["record_name"] == "a.mp3"
    assert previews.await_args.kwargs["chat_id"] == 7


async def test_explanations_are_plain_text(monkeypatch):
    import src.utils.telegram_safe as ts

    send = AsyncMock()
    monkeypatch.setattr(ts, "safe_send_message", send)

    await TelegramPauseChannel(BOT, 7).say("Заканчиваю предыдущую запись")

    kwargs = send.await_args.kwargs
    assert kwargs["chat_id"] == 7
    assert kwargs["text"] == "Заканчиваю предыдущую запись"
    assert kwargs["parse_mode"] is None


async def test_protocol_is_delivered_to_the_requesting_user(monkeypatch):
    import src.services.result_sender as rs

    send = AsyncMock(return_value=True)
    monkeypatch.setattr(rs, "send_result_to_user", send)
    request = SimpleNamespace(user_id=42)
    tracker = object()

    ok = await TelegramPauseChannel(BOT, 7).deliver(request, "результат", tracker)

    assert ok is True
    kwargs = send.await_args.kwargs
    assert (kwargs["chat_id"], kwargs["user_id"]) == (7, 42)
    assert kwargs["result"] == "результат"
    assert kwargs["progress_tracker"] is tracker


async def test_resume_gets_its_own_tracker_in_the_pause_chat(monkeypatch):
    import src.ux.progress_tracker as pt_mod

    create = AsyncMock(return_value="трекер")
    monkeypatch.setattr(pt_mod.ProgressFactory, "create_file_processing_tracker", create)

    tracker = await TelegramPauseChannel(BOT, 7).start_tracker()

    assert tracker == "трекер"
    assert create.await_args.kwargs == {"bot": BOT, "chat_id": 7}
