"""Авто-доставка протокола, когда карточку сопоставления так и не закрыли.

Протокол — продукт. Пользователь, ушедший от карточки, раньше терял готовую
расшифровку: сессия молча истекала, а возврат встречал «начните обработку
заново». Теперь срок ожидания заканчивается доставкой: обработка доводится до
конца с тем сопоставлением, которое успели ввести, а неназванные спикеры
остаются «Участник N» — ровно как при «Пропустить».

Модуль ничего не знает про Telegram-хендлеры: сервис, хранилище и бот приходят
аргументами, поэтому таймер тестируется без запуска бота.
"""

import asyncio
from typing import Any

from loguru import logger

# Запас до ленивого вытеснения в хранилище: таймер обязан успеть раньше, иначе
# первый же peek (а его делает ловец текста на каждом сообщении) выбросит
# сессию, и доставлять станет нечего.
_EVICTION_MARGIN_SECONDS = 60

_TIMEOUT_NOTICE = (
    "Не дождался имён спикеров — заканчиваю обработку.\n"
    "Неназванные участники в протоколе обозначены как «Участник N»."
)


def auto_deliver_delay_seconds(store: Any) -> float:
    """Через сколько секунд после паузы доставлять протокол без подтверждения."""
    ttl = getattr(store, "ttl_seconds", 3600)
    return max(ttl - _EVICTION_MARGIN_SECONDS, 1)


async def deliver_on_timeout(
    processing_service: Any,
    store: Any,
    *,
    user_id: int,
    bot: Any,
    chat_id: int,
    delay_seconds: float,
) -> None:
    """Дождаться срока и довести обработку, если карточку так и не закрыли.

    Best-effort и полностью тихо при штатном исходе: пользователь подтвердил или
    пропустил — сессии уже нет, таймер молча заканчивается. Любой сбой
    возобновления логируется, но не всплывает наружу: это фоновая задача.
    """
    try:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        session = store.take_regardless(user_id)
        if session is None:
            # Штатный исход: пользователь закрыл карточку сам.
            return

        logger.info(
            f"Карточка сопоставления пользователя {user_id} не закрыта за "
            f"{delay_seconds:.0f}с — доставляю протокол без подтверждения"
        )

        # Молчаливая доставка через час выглядит как сбой — сначала объясняем.
        try:
            await bot.send_message(chat_id=chat_id, text=_TIMEOUT_NOTICE)
        except Exception as e:
            logger.warning(f"Не удалось предупредить об авто-доставке: {e}")

        await processing_service.continue_processing_after_mapping_confirmation(
            session=session,
            confirmed_mapping=session.speaker_mapping or {},
            bot=bot,
            chat_id=chat_id,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Авто-доставка после таймаута карточки не удалась: {e}")
