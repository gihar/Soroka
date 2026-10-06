"""Жизнь временного файла записи: когда прогон его удаляет.

Запись приходит двумя путями: Telegram-файл скачивается самим прогоном во
временный каталог, внешняя (по ссылке) уже лежит там, скачанная при приёме.
Тесты гоняют конвейер целиком и смотрят на одно — существует ли файл после
прогона: кеш-хит, протокол, пауза на карточке и её закрытие, сбой.

Правило: скачанный прогоном Telegram-файл удаляется всегда, когда прогон с ним
закончил; внешняя запись — после доставки протокола (из кеша или собранного),
а при сбое остаётся: её держит состояние диалога.

Внешний мир — фейки: распознавание речи, Telegram (адрес файла, скачивание,
чат), пользователи, шаблоны, генерация.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.exceptions.processing import ProcessingError
from src.models.diarization import Diarization, Segment
from src.models.processing import ProcessingRequest, ProcessingResult, TranscriptionResult
from src.services.mapping_session import MappingSessionStore

AUDIO = b"telegram-audio"


def _with_speakers() -> TranscriptionResult:
    return TranscriptionResult(
        transcription="текст",
        diarization=Diarization(segments=[
            Segment(start=0.0, end=5.0, speaker="SPEAKER_1", text="привет"),
        ]),
    )


def _without_speakers() -> TranscriptionResult:
    return TranscriptionResult(transcription="текст")


def _cached_result() -> ProcessingResult:
    return ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text="# Из кеша",
        template_used={"name": "T"},
        llm_provider_used="openai",
    )


class _Chat:
    """Чат пользователя (канал паузы): протокол всегда доходит."""

    def __init__(self):
        self.delivered = []

    async def silence_tracker(self):
        return None

    async def send_previews(self, **kwargs):
        return set()

    async def show_card(self, **kwargs):
        return SimpleNamespace(name="карточка")

    async def say(self, text):
        return None

    async def start_tracker(self):
        return SimpleNamespace(
            start_stage=AsyncMock(), complete_all=AsyncMock(), error=AsyncMock(),
            current_stage=None,
        )

    async def deliver(self, request, result, tracker):
        self.delivered.append(result)
        return True

    async def report_failure(self, error):
        return None


class _Downloads:
    """Скачивание из Telegram: кладёт байты по пути назначения."""

    def __init__(self, ok=True):
        self.ok = ok
        self.paths = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def download_file(self, url, file_path, *args, **kwargs):
        if not self.ok:
            return {"success": False, "error": "404"}
        self.paths.append(file_path)
        with open(file_path, "wb") as f:
            f.write(AUDIO)
        return {"success": True, "bytes_downloaded": len(AUDIO), "duration": 0.0}


class _ResultCache:
    """Процессный кеш: полный результат есть или нет, транскрипций нет."""

    def __init__(self, cached=None, broken=False):
        self.cached = cached
        self.broken = broken

    async def get(self, key):
        if self.broken:
            raise RuntimeError("кеш недоступен")
        if key.startswith("full_result_v2") and self.cached is not None:
            return self.cached
        return None

    async def set(self, *args, **kwargs):
        return None


class World:
    """Конвейер записи с фейковым внешним миром."""

    def __init__(self, monkeypatch, tmp_path):
        import src.services.processing.completion as completion
        import src.services.processing.processing_service as pss
        from src.database import queue_repo
        from src.performance.memory_management import memory_optimizer
        from src.performance.metrics import metrics_collector

        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.chat = _Chat()
        self.store = MappingSessionStore()
        self.timers = []
        self.transcription = _without_speakers()
        self.transcription_error = None
        self.generation_error = None

        monkeypatch.chdir(tmp_path)
        (tmp_path / "temp").mkdir()
        monkeypatch.setattr(metrics_collector, "is_monitoring", True)
        monkeypatch.setattr(memory_optimizer, "is_optimizing", True)
        monkeypatch.setattr(queue_repo, "update_queue_task_status", AsyncMock())
        monkeypatch.setattr(completion, "performance_cache", _ResultCache())
        self.pss = pss
        self.cache(None)
        self.downloads(ok=True)

    # --- внешний мир -------------------------------------------------------

    def cache(self, cached, broken=False):
        import src.services.processing.record_preparation as preparation

        cache = _ResultCache(cached, broken)
        self.monkeypatch.setattr(preparation, "performance_cache", cache)
        self.monkeypatch.setattr(self.pss, "performance_cache", cache)

    def downloads(self, ok):
        import src.services.processing.record_preparation as preparation

        self.fetched = _Downloads(ok)
        self.monkeypatch.setattr(preparation, "OptimizedHTTPClient", self.fetched)

    def external_file(self, name="ссылка.mp3"):
        path = self.tmp_path / "temp" / name
        path.write_bytes(b"external-audio")
        return path

    def telegram_file(self):
        """Куда прогон скачал Telegram-файл (последнее скачивание)."""
        assert self.fetched.paths, "прогон ничего не скачивал"
        return self.tmp_path / self.fetched.paths[-1]

    # --- сценарии ----------------------------------------------------------

    def _deps(self):
        async def generate(*args, **kwargs):
            if self.generation_error:
                raise self.generation_error
            return {"meeting_title": "Планёрка"}

        return SimpleNamespace(
            llm_gen=SimpleNamespace(
                optimized_llm_generation=generate,
                resolve_model_display_name=AsyncMock(return_value="GPT"),
            ),
            formatter=SimpleNamespace(format_protocol=lambda *a, **k: "# Протокол"),
            history=SimpleNamespace(
                save_processing_history=AsyncMock(return_value=1),
            ),
        )

    def pause(self):
        from src.services.processing.completion import CompletionDeps
        from src.services.processing.mapping_pause import MappingPause

        deps = self._deps()
        return MappingPause(
            deps=CompletionDeps(
                llm_gen=deps.llm_gen, formatter=deps.formatter, history=deps.history,
            ),
            store=self.store,
            schedule=self.timers.append,
        )

    def service(self):
        from src.services.processing.processing_service import ProcessingService

        service = ProcessingService(
            mapping_pause=self.pause(), channel_for=lambda tracker: self.chat,
        )
        deps = self._deps()
        service.llm_gen = deps.llm_gen
        service.formatter = deps.formatter
        service.history = deps.history

        async def transcribe(*args, **kwargs):
            if self.transcription_error:
                raise self.transcription_error
            return self.transcription

        service.transcription_service = SimpleNamespace(
            transcribe_with_diarization=transcribe
        )
        service.user_service = SimpleNamespace(
            get_user_by_telegram_id=AsyncMock(
                return_value=SimpleNamespace(speaker_mapping_enabled=True)
            )
        )
        service.template_service = SimpleNamespace(
            get_template_by_id=AsyncMock(return_value=SimpleNamespace(id=5, name="Дейли"))
        )
        service.file_service = SimpleNamespace(
            get_telegram_file_url=AsyncMock(return_value="https://telegram/file")
        )
        return service

    async def run(self, request):
        tracker = SimpleNamespace(start_stage=AsyncMock(), complete_all=AsyncMock())
        try:
            return await self.service().process_file(request, tracker, task_id="task-1")
        finally:
            await _settle()

    async def close_pause(self):
        from src.services.processing.mapping_pause import CloseReason

        try:
            return await self.pause().close(
                self.store.take(42), CloseReason.CONFIRMED, channel=self.chat
            )
        finally:
            await _settle()


async def _settle():
    """Дать фоновым задачам прогона (удаление файла) доработать."""
    for _ in range(5):
        await asyncio.sleep(0)


def _telegram_request(name="голос.mp3"):
    return ProcessingRequest(
        file_id="F1", file_name=name, llm_provider="openai", user_id=42, template_id=5,
    )


def _external_request(path):
    return ProcessingRequest(
        file_name=path.name, llm_provider="openai", user_id=42, template_id=5,
        is_external_file=True, file_path=str(path),
    )


@pytest.fixture
def world(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path)
    yield w
    for timer in w.timers:
        timer.close()


# ---------------------------------------------------------------------------
# Кеш-хит
# ---------------------------------------------------------------------------


async def test_telegram_cache_hit_deletes_the_download(world):
    world.cache(_cached_result())

    outcome = await world.run(_telegram_request())

    assert outcome.result.protocol_text == "# Из кеша"
    assert not world.telegram_file().exists()


async def test_external_cache_hit_deletes_the_file(world):
    """Протокол доставлен из кеша — запись прогону больше не нужна, как и после
    генерации. Раньше файл оставался до очистки по возрасту."""
    path = world.external_file()
    world.cache(_cached_result())

    await world.run(_external_request(path))

    assert not path.exists()


# ---------------------------------------------------------------------------
# Протокол собран
# ---------------------------------------------------------------------------


async def test_external_file_is_deleted_after_the_protocol(world):
    path = world.external_file()

    outcome = await world.run(_external_request(path))

    assert outcome.paused is False and world.chat.delivered
    assert not path.exists()


async def test_telegram_download_is_deleted_after_the_protocol(world):
    """Скачанный прогоном файл после протокола удаляется: раньше он лежал во
    временном каталоге до очистки по возрасту или до рестарта бота."""
    await world.run(_telegram_request())

    assert world.chat.delivered
    assert not world.telegram_file().exists()


# ---------------------------------------------------------------------------
# Пауза на карточке и её закрытие
# ---------------------------------------------------------------------------


async def test_paused_run_keeps_the_file_for_the_card(world):
    """Фрагменты записи режутся из файла — на паузе он нужен."""
    path = world.external_file()
    world.transcription = _with_speakers()

    outcome = await world.run(_external_request(path))

    assert outcome.paused is True
    assert path.exists()
    assert world.store.peek(42).temp_file_path == str(path)


async def test_pause_remembers_size_and_format_of_the_record(world):
    path = world.external_file()
    world.transcription = _with_speakers()

    await world.run(_external_request(path))

    metrics = world.store.peek(42).metrics
    assert metrics.file_size_bytes == len(b"external-audio")
    assert metrics.file_format == ".mp3"


async def test_external_file_is_deleted_when_the_pause_closes(world):
    path = world.external_file()
    world.transcription = _with_speakers()
    await world.run(_external_request(path))

    await world.close_pause()

    assert world.chat.delivered
    assert not path.exists()


async def test_telegram_download_is_deleted_when_the_pause_closes(world):
    world.transcription = _with_speakers()
    await world.run(_telegram_request())
    assert world.telegram_file().exists()  # на паузе файл нужен фрагментам

    await world.close_pause()

    assert not world.telegram_file().exists()


async def test_failed_close_keeps_the_external_file(world):
    path = world.external_file()
    world.transcription = _with_speakers()
    await world.run(_external_request(path))
    world.generation_error = RuntimeError("LLM упал")

    with pytest.raises(ProcessingError):
        await world.close_pause()

    assert path.exists()


async def test_failed_close_deletes_the_telegram_download(world):
    """Telegram-запись перезапускается по file_id — скачанная копия не нужна."""
    world.transcription = _with_speakers()
    await world.run(_telegram_request())
    world.generation_error = RuntimeError("LLM упал")

    with pytest.raises(ProcessingError):
        await world.close_pause()

    assert not world.telegram_file().exists()


# ---------------------------------------------------------------------------
# Сбой прогона
# ---------------------------------------------------------------------------


async def test_failure_before_the_cache_answer_deletes_the_telegram_download(world):
    world.cache(None, broken=True)

    with pytest.raises(RuntimeError):
        await world.run(_telegram_request())

    assert not world.telegram_file().exists()


async def test_failure_before_the_cache_answer_keeps_the_external_file(world):
    path = world.external_file()
    world.cache(None, broken=True)

    with pytest.raises(RuntimeError):
        await world.run(_external_request(path))

    assert path.exists()


async def test_failure_after_the_cache_miss_keeps_the_external_file(world):
    """Внешняя запись после сбоя остаётся — её держит состояние диалога."""
    path = world.external_file()
    world.transcription_error = RuntimeError("распознавание упало")

    with pytest.raises(RuntimeError):
        await world.run(_external_request(path))

    assert path.exists()


async def test_failure_after_the_cache_miss_deletes_the_telegram_download(world):
    world.transcription_error = RuntimeError("распознавание упало")

    with pytest.raises(RuntimeError):
        await world.run(_telegram_request())

    assert not world.telegram_file().exists()


# ---------------------------------------------------------------------------
# Запись не получена
# ---------------------------------------------------------------------------


async def test_missing_external_file_is_a_preparation_error(world):
    with pytest.raises(ProcessingError) as caught:
        await world.run(_external_request(world.tmp_path / "temp" / "нет.mp3"))

    assert "Файл не найден" in str(caught.value)


async def test_failed_telegram_download_is_a_download_error(world):
    world.downloads(ok=False)

    with pytest.raises(ProcessingError) as caught:
        await world.run(_telegram_request())

    assert "Ошибка скачивания" in str(caught.value)


# ---------------------------------------------------------------------------
# Одновременные прогоны
# ---------------------------------------------------------------------------


async def test_same_named_telegram_records_get_separate_files(world):
    """Два голосовых с одинаковым именем идут разными прогонами одновременно.

    Каждый прогон удаляет свою скачанную копию, когда закончил с ней, — если
    бы обе лежали по одному пути, первый прогон удалил бы файл второго.
    """
    from src.services.processing.record_preparation import prepare_record

    file_service = SimpleNamespace(
        get_telegram_file_url=AsyncMock(return_value="https://telegram/file")
    )
    first = await prepare_record(_telegram_request("голос.mp3"), file_service=file_service)
    second = await prepare_record(_telegram_request("голос.mp3"), file_service=file_service)

    assert first.path != second.path
    assert first.file_format == second.file_format == ".mp3"
