"""Пауза на карточке сопоставления — жизненный цикл Сессии сопоставления.

Модуль владеет паузой целиком:

* **открыть** (:meth:`MappingPause.open`) — заглушить трекер основного
  прогона, прислать фрагменты записи, довести вытесненную предыдущую сессию,
  сохранить новую, показать карточку последним сообщением и завести таймер.
  Карточка не ушла — сказать об этом и продолжать без паузы;
* **закрыть с поводом** (:meth:`MappingPause.close`) — подтверждение, пропуск,
  истёк срок, вытеснение новой записью. Любой повод ведёт в единый хвост
  «Завершение обработки» (ADR-0003), сбой — в единую политику сбоя
  (``failure_policy``, ADR-0010).

Таймер и вытеснение живут здесь же и закрывают паузу этим же ``close`` — цикла
«таймер → сервис обработки → таймер» больше нет (ADR-0011).

Telegram модуль не знает: всё, что видит пользователь, идёт через
:class:`~src.services.processing.pause_channel.PauseChannel`, который
подставляется снаружи (в проде — Telegram-адаптер, в тестах — фейковый чат).
"""

import asyncio
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

from loguru import logger

from src.exceptions.processing import ProcessingError
from src.models.processing import ProcessingResult
from src.services.mapping_session import MappingSession, MappingSessionStore

from .completion import CompletionDeps, complete_processing
from .failure_policy import fail_processing, on_tracker
from .pause_channel import PauseChannel

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

_CARD_NOT_SENT_NOTICE = (
    "Не удалось отправить интерфейс подтверждения сопоставления.\n\n"
    "Продолжаю генерацию протокола с автоматическим сопоставлением спикеров."
)


class CloseReason(Enum):
    """Повод закрыть паузу. От него зависят имена в протоколе и объяснение."""

    CONFIRMED = "confirmed"    # «Подтвердить»: имена из карточки
    SKIPPED = "skipped"        # «Пропустить»: без имён
    EXPIRED = "expired"        # истёк срок: что успели назвать
    SUPERSEDED = "superseded"  # пришла новая запись: что успели назвать


# Досрочные поводы: пользователь ничего не нажимал, поэтому объяснение идёт
# первым — молчаливая доставка выглядит как сбой.
_EARLY_NOTICES = {
    CloseReason.EXPIRED: _TIMEOUT_NOTICE,
    CloseReason.SUPERSEDED: _SUPERSEDED_NOTICE,
}


def auto_deliver_delay_seconds(store: Any) -> float:
    """Через сколько секунд после паузы доставлять протокол без подтверждения."""
    ttl = getattr(store, "ttl_seconds", 3600)
    return max(ttl - _EVICTION_MARGIN_SECONDS, 1)


Schedule = Callable[[Coroutine[Any, Any, None]], Any]


class MappingPause:
    """Открыть и закрыть паузу на карточке сопоставления.

    Args:
        deps: зависимости единого хвоста (генерация, форматирование, история).
        store: хранилище сессий; по умолчанию — общее процессное.
        delay_seconds: срок ожидания карточки; по умолчанию — чуть меньше TTL
            хранилища (:func:`auto_deliver_delay_seconds`).
        schedule: как запустить фоновый таймер; по умолчанию
            ``asyncio.create_task``.
    """

    def __init__(
        self,
        *,
        deps: CompletionDeps,
        store: Optional[MappingSessionStore] = None,
        delay_seconds: Optional[float] = None,
        schedule: Schedule = asyncio.create_task,
    ):
        if store is None:
            from src.services.mapping_session import mapping_sessions

            store = mapping_sessions
        self._deps = deps
        self._store = store
        self._delay = (
            delay_seconds if delay_seconds is not None
            else auto_deliver_delay_seconds(store)
        )
        self._schedule = schedule

    # ------------------------------------------------------------------
    # Открыть
    # ------------------------------------------------------------------

    async def open(
        self, session: MappingSession, *, channel: Optional[PauseChannel]
    ) -> bool:
        """Поставить обработку на паузу и показать карточку.

        Возвращает True, если обработка приостановлена (карточка показана),
        False — если продолжать без паузы: нет канала к пользователю или
        карточку не удалось отправить.

        ``session.task_id`` должен быть задан ДО вызова: к моменту, когда
        пользователь сможет нажать «Подтвердить», он уже в сохранённой сессии.
        """
        if channel is None:
            logger.warning(
                "UI подтверждения включен, но канала к пользователю нет "
                "- продолжаю без паузы"
            )
            return False

        logger.info(
            "UI подтверждения сопоставления включен - "
            "сохраняю сессию и показываю интерфейс"
        )
        user_id = session.request.user_id
        diarization = session.transcription_result.diarization

        await channel.silence_tracker()

        # Фрагменты записи уходят ДО карточки: по факту доставки решаем, кому в
        # карточке нужна текстовая цитата (цитата спикера показывается один
        # раз). Ошибка превью не мешает паузе: карточка выйдет со всеми цитатами.
        session.speakers_with_audio = await self._send_previews(session, channel)

        # Пользователь мог прислать новую запись, не закрыв карточку
        # предыдущей: она доводится до протокола, прежде чем слот займёт новая.
        await self._finish_superseded(user_id, channel)

        session_key = self._store.save(user_id, session)

        mapped = set(session.speaker_mapping)
        unmapped = [s for s in diarization.speakers if s not in mapped]
        card = await channel.show_card(
            user_id=user_id,
            speaker_mapping=session.speaker_mapping,
            # Список может быть не передан: карточка всё равно показывается
            # (ADR-0002), participants=[] — иначе клавиатура упадёт на None.
            participants=session.request.participants_list or [],
            diarization=diarization,
            unmapped_speakers=unmapped or None,
            speakers_text=diarization.speakers_text,
            speakers_with_audio=session.speakers_with_audio,
            record_name=session.request.file_name,
        )

        if card is None:
            logger.warning(
                f"Не удалось отправить UI подтверждения сопоставления для "
                f"пользователя {user_id}. Продолжаю обработку без паузы."
            )
            await self._say(channel, _CARD_NOT_SENT_NOTICE)
            # Пауза не состоялась: выбрасываем без отметки «закрыта доставкой».
            self._store.discard(user_id, session_key)
            return False

        # Ссылку на карточку кладём в сессию: ручной ввод имени перерисовывает
        # её на месте (сообщение с именем — отдельное).
        session.confirmation_message = card
        logger.info("Обработка приостановлена - ожидаю подтверждения от пользователя")

        # Пауза не бессрочна: не закроют карточку — протокол доедет сам с
        # «Участник N». Таймер безопасен при штатном исходе: изъятие атомарно,
        # закрытая пользователем сессия вернёт таймеру None.
        self._schedule(self._expire_later(user_id, session_key, channel))
        return True

    async def _send_previews(
        self, session: MappingSession, channel: PauseChannel
    ) -> set:
        diarization = session.transcription_result.diarization
        try:
            return set(await channel.send_previews(
                user_id=session.request.user_id,
                speakers=diarization.speakers,
                diarization=diarization,
                temp_file_path=session.temp_file_path,
                speakers_text=diarization.speakers_text,
            ))
        except Exception as preview_error:
            logger.warning(
                f"Не удалось отправить фрагменты записи спикеров: {preview_error}"
            )
            return set()

    async def _finish_superseded(self, user_id: int, channel: PauseChannel) -> None:
        """Довести предыдущую запись пользователя, если её карточка ещё открыта.

        Сбой старой записи не имеет права уронить новую: его доводит до всех
        политика сбоя внутри ``close``, а здесь он только логируется.
        """
        previous = self._store.take_regardless(user_id)
        if previous is None:
            return
        logger.info(
            f"Пользователь {user_id} начал новую запись, не закрыв карточку "
            "предыдущей — довожу предыдущую до протокола"
        )
        try:
            await self.close(previous, CloseReason.SUPERSEDED, channel=channel)
        except Exception as e:
            logger.error(f"Не удалось довести предыдущую запись: {e}")

    async def _expire_later(
        self, user_id: int, session_key: str, channel: PauseChannel
    ) -> None:
        """Дождаться срока и закрыть паузу, если карточку так и не закрыли.

        ``session_key`` привязывает таймер к своей записи: таймер первой записи
        не имеет права забрать вторую (критика v11). Фоновая задача: любой сбой
        логируется и наружу не всплывает — до пользователя и администратора его
        уже довела политика сбоя внутри ``close``.
        """
        try:
            if self._delay > 0:
                await asyncio.sleep(self._delay)

            # Без оглядки на TTL: в сессии готовая расшифровка — самая дорогая
            # часть конвейера, выбрасывать её нельзя.
            session = self._store.take_regardless(user_id, session_key)
            if session is None:
                return  # Штатный исход: пользователь закрыл карточку сам.

            logger.info(
                f"Карточка сопоставления пользователя {user_id} не закрыта за "
                f"{self._delay:.0f}с — доставляю протокол без подтверждения"
            )
            await self.close(session, CloseReason.EXPIRED, channel=channel)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Авто-доставка после таймаута карточки не удалась: {e}")

    # ------------------------------------------------------------------
    # Закрыть
    # ------------------------------------------------------------------

    async def close(
        self,
        session: MappingSession,
        reason: CloseReason,
        *,
        channel: PauseChannel,
    ) -> ProcessingResult:
        """Закрыть паузу с поводом и довести обработку до протокола.

        ``session`` уже изъята из хранилища (take) — вызывающий ею владеет.
        Возвращает собранный результат. При сбое — единая политика сбоя
        (статус задачи, пользователь, администратор) и ``ProcessingError``
        наружу: колбэк карточки правит по нему саму карточку.
        """
        notice = _EARLY_NOTICES.get(reason)
        if notice:
            await self._say(channel, notice)

        user_id = session.request.user_id
        tracker = None
        try:
            logger.info(
                f"Продолжение обработки для пользователя {user_id} "
                f"после карточки сопоставления (повод: {reason.value})"
            )
            request = session.request
            request.speaker_mapping = _names_for(session, reason)

            tracker = await channel.start_tracker()

            # Шаблон выбран в основном пути ДО паузы — берём его из сессии, не
            # выбирая заново (выбор шаблона один раз, ADR-0003).
            template = session.template
            request.template_id = template.id

            if tracker:
                await tracker.start_stage("analysis")

            async def deliver(result) -> bool:
                return await channel.deliver(request, result, tracker)

            # Единый хвост «Завершение обработки»: генерация → страховка
            # спикеров → кеш → история → доставка → статус задачи → трекер.
            outcome = await complete_processing(
                request=request,
                transcription_result=session.transcription_result,
                template=template,
                meeting_type=session.meeting_type,
                deps=self._deps,
                delivery=deliver,
                cache_key=session.cache_key,
                task_id=session.task_id,
                metrics=session.metrics,
                temp_file_path=session.temp_file_path,
                progress_tracker=tracker,
            )

            if outcome.delivered:
                logger.info(f"Обработка успешно завершена для пользователя {user_id}")
            else:
                logger.warning(
                    f"Протокол сгенерирован, но не доставлен пользователю {user_id}"
                )
            return outcome.result

        except Exception as e:
            # Трекер продолжения уже завёлся — сбой гасит его, как в воркере
            # (иначе «Анализ…» крутился бы до гарда под сообщением о сбое).
            # Не завёлся — говорим о сбое отдельным сообщением в чат.
            notify_user = (
                on_tracker(tracker, default_stage="analysis")
                if tracker else channel.report_failure
            )
            await fail_processing(
                e, task_id=session.task_id, notify_user=notify_user
            )
            if isinstance(e, ProcessingError):
                raise
            raise ProcessingError(str(e), "unknown", "resume_error") from e

    async def _say(self, channel: PauseChannel, text: str) -> None:
        """Объяснение пользователю best-effort: его сбой не отменяет обработку."""
        try:
            await channel.say(text)
        except Exception as e:
            logger.warning(f"Не удалось отправить пояснение пользователю: {e}")


def _names_for(session: MappingSession, reason: CloseReason) -> Dict[str, str]:
    """Какие имена поедут в протокол при этом поводе.

    Пропуск — никаких; остальные поводы — что успели назвать в карточке
    (досрочным неназванные спикеры остаются «Участник N», как при пропуске).
    """
    if reason is CloseReason.SKIPPED:
        return {}
    return session.speaker_mapping or {}
