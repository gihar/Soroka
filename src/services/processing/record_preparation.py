"""«Подготовка записи» — от запроса к локальному файлу и ответу кеша.

Из :class:`ProcessingRequest` модуль делает подготовленную запись: локальный
путь (внешняя запись уже лежит во временном каталоге, Telegram-файл
скачивается), размер, формат, хеш содержимого, ключ кеша полного результата и
сам кешированный результат, если он есть.

Модуль же владеет жизнью временного файла — одно правило в одном месте
(:data:`_DELETE_AFTER`). Раньше удаление решали три условия в трёх местах:
флаг «только проверка кеша» в ``process_file``, ``is_external_file`` в хвосте
«Завершения обработки» и сессия паузы, державшая путь к файлу.
"""

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import aiofiles
from loguru import logger

from src.exceptions.processing import ProcessingError
from src.models.processing import ProcessingRequest, ProcessingResult
from src.performance.async_optimization import OptimizedHTTPClient
from src.performance.cache_system import performance_cache


class RecordFate(Enum):
    """Чем для записи закончился прогон — от этого зависит судьба файла."""

    DELIVERED_FROM_CACHE = "cached"   # кеш-хит: протокол переотправлен
    PROTOCOL_ASSEMBLED = "protocol"   # протокол собран (в т.ч. после паузы)
    FAILED = "failed"                 # прогон упал после подготовки


# Удалять ли файл записи: (скачан прогоном?, исход прогона) → да/нет.
# Единственное место, где решается удаление.
#
# Telegram-файл прогон скачивает сам и при любом исходе может скачать заново
# по file_id — копия удаляется, как только прогон с ней закончил. Внешняя
# запись скачана при приёме ссылки и живёт в состоянии диалога: после
# доставки протокола (из кеша или собранного) она отработала, а после сбоя
# остаётся для повторного запуска — её подберёт очистка по возрасту.
_DELETE_AFTER = {
    (True, RecordFate.DELIVERED_FROM_CACHE): True,
    (True, RecordFate.PROTOCOL_ASSEMBLED): True,
    (True, RecordFate.FAILED): True,
    (False, RecordFate.DELIVERED_FROM_CACHE): True,
    (False, RecordFate.PROTOCOL_ASSEMBLED): True,
    (False, RecordFate.FAILED): False,
}


@dataclass
class PreparedRecord:
    """Запись, готовая к прогону: файл на диске и ответ кеша."""

    path: str
    size_bytes: int
    file_format: str
    file_hash: str
    cache_key: str
    cached_result: Optional[ProcessingResult]
    # Скачан ли файл самим прогоном (Telegram), а не при приёме записи.
    downloaded: bool

    async def release(self, fate: RecordFate) -> None:
        """Прогон закончил с записью: удалить файл, если так велит правило.

        Best-effort: неудача удаления не меняет исход прогона — файл подберёт
        периодическая очистка временного каталога по возрасту.
        """
        if _DELETE_AFTER[(self.downloaded, fate)]:
            await _delete(self.path)


async def prepare_record(
    request: ProcessingRequest, *, file_service: Any
) -> PreparedRecord:
    """Получить файл записи, посчитать хеш и спросить кеш полного результата.

    Сбой самой подготовки (хеш, кеш) убирает за собой скачанный ею файл —
    прогона ещё не было, и держать файл некому.

    Raises:
        ProcessingError: внешнего файла нет на диске или скачивание не удалось.
    """
    if request.is_external_file:
        path = request.file_path
        if not path or not os.path.exists(path):
            raise ProcessingError(
                f"Файл не найден: {path}", request.file_name, "file_preparation",
            )
        downloaded = False
    else:
        path = await _download_telegram_file(request, file_service)
        downloaded = True

    try:
        digest = await file_hash(path)
        logger.debug(f"Вычислен хеш файла: {digest}")
        cache_key = result_cache_key(request, digest)
        cached = await performance_cache.get(cache_key)
    except Exception:
        if downloaded:
            await _delete(path)
        raise

    return PreparedRecord(
        path=path,
        size_bytes=os.path.getsize(path),
        file_format=os.path.splitext(request.file_name)[1],
        file_hash=digest,
        cache_key=cache_key,
        cached_result=cached or None,
        downloaded=downloaded,
    )


async def file_hash(file_path: str) -> str:
    """Хеш содержимого файла записи — основа ключей кеша результата и транскрипции."""
    hash_obj = hashlib.sha256()
    async with aiofiles.open(file_path, "rb") as f:
        while chunk := await f.read(8192):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()[:16]


def result_cache_key(request: ProcessingRequest, file_hash: str) -> str:
    """Ключ кеша полного результата: содержимое записи + всё, что влияет на протокол.

    Префикс несёт версию формы результата (``full_result_v2``): после
    типизации диаризации (issue #59) старые pickle-записи хранятся под
    ``full_result:...`` и в новую форму не регидрируются.
    """
    key_data = {
        "file_hash": file_hash,
        "template_id": request.template_id,
        "llm_provider": request.llm_provider,
        "language": request.language,
        "participants_list": request.participants_list,
        "meeting_topic": request.meeting_topic,
        "meeting_date": request.meeting_date,
        "meeting_time": request.meeting_time,
        "speaker_mapping": request.speaker_mapping,
        "meeting_agenda": request.meeting_agenda,
        "project_list": request.project_list,
    }
    # Та же формула, что у performance_cache._generate_key: ключи прежних
    # записей кеша остаются действительными.
    digest = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
    return f"full_result_v2:{digest[:16]}"


async def _download_telegram_file(request: ProcessingRequest, file_service: Any) -> str:
    """Скачать Telegram-файл во временный каталог и вернуть путь.

    Имя копии уникально на прогон: прогон удаляет свою копию, когда закончил с
    ней, и два одновременных голосовых с одинаковым именем по общему пути
    удаляли бы файл друг у друга.
    """
    file_url = await file_service.get_telegram_file_url(request.file_id)
    temp_file_path = f"temp/{uuid.uuid4().hex[:12]}_{request.file_name}"

    async with OptimizedHTTPClient() as http_client:
        result = await http_client.download_file(file_url, temp_file_path)

    if not result["success"]:
        error_msg = result.get("error", "Неизвестная ошибка скачивания")
        raise ProcessingError(
            f"Ошибка скачивания: {error_msg}", request.file_name, "download",
        )

    logger.info(f"Файл скачан: {temp_file_path} ({result['bytes_downloaded']} байт)")
    return temp_file_path


async def _delete(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug(f"Удален временный файл: {path}")
    except Exception as e:
        logger.warning(f"Не удалось удалить временный файл {path}: {e}")
