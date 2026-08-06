"""Автовозврат активного пресета при квотной стене.

Активный пресет — глобальный, один на весь бот. Значит квотная стена у подписки
останавливает протоколы у всех и держит их до тех пор, пока администратор не
увидит уведомление и не переключит пресет руками. Здесь этот промежуток
закрывается: активный пресет уходит на резервный сам, а решение «на чём жить
дальше» остаётся за человеком.

Переключается именно настройка, а не идущий вызов: прогон, наткнувшийся на
стену, завершается ошибкой, и на резервном провайдере идут только следующие.
Фолбэк внутри одного прогона отвергнут в ADR-0007 — протокол оказался бы склеен
двумя моделями, а расход подписки незаметным.
"""

from typing import Optional

from loguru import logger

from src.exceptions.configuration import AdminConfigurationError


async def return_to_fallback() -> Optional[str]:
    """Перевести активный пресет на резервный. Вернуть его имя или None.

    None означает «переключения не было» — исход законный, а не сбой:
    резервный пресет не задан, совпал с активным или успел устареть.

    Автовозврат — попытка, а не условие: его сбой не должен обрушить
    уведомление админам о самой стене, единственное, что видно снаружи.
    Поэтому наружу отсюда не выходит ничего, кроме имени или None.
    """
    try:
        return await _switch_to_reserve()
    except AdminConfigurationError as e:
        # Резерв удалили или выключили после настройки: адрес устарел.
        logger.warning(f"Автовозврат не сработал: {e.message}")
        return None
    except Exception as e:
        logger.error(f"Автовозврат не сработал: {e}")
        return None


async def _switch_to_reserve() -> Optional[str]:
    """Сама подмена настройки: проверки, запись, имя нового пресета."""
    from src.database import app_settings_repo, model_preset_repo

    fallback_key = await app_settings_repo.get_fallback_model_key()
    if not fallback_key:
        # Тихо переехать на случайного провайдера хуже, чем постоять: без
        # заданного резерва остаётся одно уведомление (ADR-0007).
        logger.info("Автовозврат не сработал: резервный пресет не задан")
        return None

    active_key = await app_settings_repo.get_active_model_key()
    if fallback_key == active_key:
        logger.info(
            f"Автовозврат не сработал: резервный пресет '{fallback_key}' "
            "и есть активный"
        )
        return None

    # Имя читаем до подмены: после успешной записи сбой чтения превратил бы
    # состоявшееся переключение в «переключения не было».
    preset = await model_preset_repo.get_by_key(fallback_key)
    name = (preset or {}).get("name") or fallback_key

    await app_settings_repo.set_active_model_key(fallback_key, admin_id=None)
    logger.info(
        f"Автовозврат: активный пресет '{active_key}' → '{fallback_key}' "
        "после исчерпания квоты"
    )
    return name
