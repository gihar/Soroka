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
from typing import Any, Optional

from loguru import logger

# Запас до ленивого вытеснения в хранилище: таймер обязан успеть раньше, иначе
# первый же peek (а его делает ловец текста на каждом сообщении) выбросит
# сессию, и доставлять станет нечего.
_EVICTION_MARGIN_SECONDS = 60

_TIMEOUT_NOTICE = (
    "Не дождался имён спикеров — заканчиваю обработку.\n"
    "Неназванные участники в протоколе обозначены как «Участник N»."
)

# Пользователь прислал новую запись, не закрыв карточку предыдущей. Раньше
# предыдущая сессия молча затиралась вместе с расшифровкой (критика v11);
# теперь она доводится до протокола, а цена досрочного конца названа вслух.
_SUPERSEDED_NOTICE = (
    "Заканчиваю предыдущую запись — вы прислали новую.\n"
    "Неназванные участники в её протоколе обозначены как «Участник N»."
)


def auto_deliver_delay_seconds(store: Any) -> float:
    """Через сколько секунд после паузы доставлять протокол без подтверждения."""
    ttl = getattr(store, "ttl_seconds", 3600)
    return max(ttl - _EVICTION_MARGIN_SECONDS, 1)


async def _deliver(
    processing_service: Any,
    session: Any,
    *,
    bot: Any,
    chat_id: int,
    notice: str,
) -> None:
    """Объяснить досрочный конец и довести обработку изъятой сессии.

    Единый хвост обоих поводов закончить без подтверждения — истёк срок или
    пришла новая запись. Молчаливая доставка выглядит как сбой, поэтому
    объяснение идёт первым; его неудача доставку не отменяет.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=notice)
    except Exception as e:
        logger.warning(f"Не удалось предупредить о досрочной доставке: {e}")

    await processing_service.continue_processing_after_mapping_confirmation(
        session=session,
        confirmed_mapping=session.speaker_mapping or {},
        bot=bot,
        chat_id=chat_id,
    )


async def deliver_on_timeout(
    processing_service: Any,
    store: Any,
    *,
    user_id: int,
    bot: Any,
    chat_id: int,
    delay_seconds: float,
    session_key: Optional[str] = None,
) -> None:
    """Дождаться срока и довести обработку, если карточку так и не закрыли.

    ``session_key`` привязывает таймер к своей записи: без него таймер первой
    записи забирал ту сессию, что окажется активной к сроку, — то есть вторую,
    ещё живую (критика v11).

    Best-effort и полностью тихо при штатном исходе: пользователь подтвердил или
    пропустил — сессии уже нет, таймер молча заканчивается. Любой сбой
    возобновления логируется, но не всплывает наружу: это фоновая задача.
    """
    try:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        session = store.take_regardless(user_id, session_key)
        if session is None:
            # Штатный исход: пользователь закрыл карточку сам.
            return

        logger.info(
            f"Карточка сопоставления пользователя {user_id} не закрыта за "
            f"{delay_seconds:.0f}с — доставляю протокол без подтверждения"
        )
        await _deliver(
            processing_service, session,
            bot=bot, chat_id=chat_id, notice=_TIMEOUT_NOTICE,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Авто-доставка после таймаута карточки не удалась: {e}")


async def finish_superseded_session(
    processing_service: Any,
    store: Any,
    *,
    user_id: int,
    bot: Any,
    chat_id: int,
) -> bool:
    """Довести предыдущую запись, если пользователь начал новую до её конца.

    Вызывается перед постановкой новой паузы. Возвращает True, если предыдущая
    сессия была и её удалось довести до протокола; False — если доводить было
    нечего или возобновление упало. В обоих случаях новая пауза продолжается:
    сбой старой записи не имеет права уронить новую.
    """
    session = store.take_regardless(user_id)
    if session is None:
        return False

    logger.info(
        f"Пользователь {user_id} начал новую запись, не закрыв карточку "
        "предыдущей — довожу предыдущую до протокола"
    )
    try:
        await _deliver(
            processing_service, session,
            bot=bot, chat_id=chat_id, notice=_SUPERSEDED_NOTICE,
        )
        return True
    except Exception as e:
        logger.error(f"Не удалось довести предыдущую запись: {e}")
        return False
