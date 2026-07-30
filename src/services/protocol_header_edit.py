"""Правка шапки доставленного протокола: дата и название.

Доставка — не точка невозврата. Единственный реквизит, который продукт не может
достать из аудио, — когда была встреча; когда его подставили днём обработки,
пользователю нужен способ это исправить, не отправляя запись заново.

Логика отделена от Telegram (как в ``completion``): репозиторий приходит
аргументом, наружу отдаётся описание исхода, а доставку выполняет хендлер.
"""

from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger

from src.services.protocol_header import parse_header_input, rewrite_protocol_header

HEADER_EDIT_PROMPT = (
    "Когда была встреча?\n"
    "Отправьте дату одной строкой — например, «27 июля 2026».\n"
    "Второй строкой можно добавить название встречи."
)


@dataclass(frozen=True)
class HeaderEditOutcome:
    """Итог правки: что показать пользователю и что переотправить.

    ``status``: ``ok`` — есть исправленный протокол; ``empty`` — ввод пуст,
    спрашиваем ещё раз; ``not_found`` — записи нет или она не принадлежит
    пользователю (история очищена / чужой id).
    """

    status: str
    protocol_text: Optional[str] = None
    file_name: Optional[str] = None
    date: Optional[str] = None
    title: Optional[str] = None


async def apply_header_edit(
    history_repo: Any,
    *,
    history_id: int,
    telegram_user_id: int,
    raw_input: str,
) -> HeaderEditOutcome:
    """Переписать шапку сохранённого протокола по вводу пользователя.

    Владение проверяет репозиторий (``get_result_for_user``) — тот же контракт,
    что у «PDF» и «Другой шаблон»: ``history_id`` приходит из callback_data.

    Сохранение в историю best-effort: даже если запись не удалась, исправленный
    протокол возвращается — пользователь просил документ, а не транзакцию.
    """
    date, title = parse_header_input(raw_input)
    if not date and not title:
        return HeaderEditOutcome(status="empty")

    row = await history_repo.get_result_for_user(history_id, telegram_user_id)
    if not row or not (row.get("result_text") or "").strip():
        return HeaderEditOutcome(status="not_found")

    protocol_text = rewrite_protocol_header(row["result_text"], date=date, title=title)

    try:
        saved = await history_repo.update_result_text(
            history_id, telegram_user_id, protocol_text
        )
        if not saved:
            logger.warning(
                f"Правка шапки {history_id}: обновление истории не применилось"
            )
    except Exception as e:
        logger.error(f"Правка шапки {history_id}: не удалось сохранить историю: {e}")

    return HeaderEditOutcome(
        status="ok",
        protocol_text=protocol_text,
        file_name=row.get("file_name") or "protocol",
        date=date,
        title=title,
    )
