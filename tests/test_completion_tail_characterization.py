"""Поведение хвоста конвейера «Завершение обработки» на стыке трёх путей (ADR-0003).

Тесты фиксируют, как каждый путь стыкуется с единым модулем completion через
свой публичный интерфейс (сам модуль детально протестирован в
tests/test_completion_module.py):

(а) основной путь (process_file): владеет проверкой кеша, делегированием
    _process_file_optimized и паузой на карточке; кеш/история/доставка/статус
    уехали в единый хвост. Кеш-хит доставляется тем же хвостом.
(б) возобновление: кеширует безусловно после успешной генерации и проставляет
    history_id ДО доставки (кнопки под протоколом) — изменения по ADR-0003.
(в) перегенерация: полная сборка результата и страховка замены спикеров —
    выровнена по основному пути (изменение по ADR-0003).

Стиль стабов — как в tests/test_manual_speaker_naming.py: сервис поднимается
через ``__new__`` (обходя самосборку конструктора), зависимости — фейки.
"""

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))  # noqa: E402

from src.models.processing import (  # noqa: E402
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services.mapping_session import MappingSession  # noqa: E402


def _canned_result() -> ProcessingResult:
    return ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text="# Протокол",
        template_used={"name": "Шаблон"},
        llm_provider_used="openai",
    )


# ---------------------------------------------------------------------------
# (а) Основной путь: process_file владеет кеш-проверкой, делегированием и паузой;
#     кеш/история/доставка уехали в единый хвост (внутри _process_file_optimized)
# ---------------------------------------------------------------------------


def _external_request(tmp_path):
    audio = tmp_path / "rec.mp3"
    audio.write_bytes(b"data")
    return ProcessingRequest(
        file_name="rec.mp3", llm_provider="openai", user_id=1,
        is_external_file=True, file_path=str(audio),
    )


def _patch_process_file_env(monkeypatch, pss, cached):
    monkeypatch.setattr(
        pss,
        "metrics_collector",
        SimpleNamespace(
            start_processing_metrics=lambda *a, **k: SimpleNamespace(
                start_time=0.0, end_time=0.0, total_duration=1.0
            ),
            finish_processing_metrics=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(
        pss,
        "monitoring_middleware",
        SimpleNamespace(record_protocol_request=lambda **k: None),
    )
    monkeypatch.setattr(
        pss,
        "performance_cache",
        SimpleNamespace(get=AsyncMock(return_value=cached), set=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_cache_hit_delivers_and_records_history(tmp_path, monkeypatch):
    """Кеш-хит: process_file доставляет кешированный результат тем же хвостом —
    свежая запись истории (её id даёт кнопки) и доставка, без повторной генерации."""
    import src.services.processing.completion as completion
    import src.services.processing.processing_service as pss
    import src.services.result_sender as rs

    service = pss.ProcessingService.__new__(pss.ProcessingService)
    service._ensure_monitoring_started = AsyncMock()
    service.llm_gen = SimpleNamespace(optimized_llm_generation=AsyncMock())
    service.formatter = SimpleNamespace()
    service.history = SimpleNamespace(
        calculate_file_hash=AsyncMock(return_value="deadbeef"),
        generate_result_cache_key=lambda request, file_hash: "cache-key",
        save_processing_history=AsyncMock(return_value=777),
        cleanup_temp_file=AsyncMock(),
    )

    cached = ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text="# Кешированный",
        template_used={"name": "T"},
        llm_provider_used="openai",
    )
    _patch_process_file_env(monkeypatch, pss, cached)
    mark_status = AsyncMock()
    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", mark_status)

    seen = {}

    async def fake_send(**kwargs):
        seen["history_id"] = kwargs["result"].history_id
        return True

    monkeypatch.setattr(rs, "send_result_to_user", fake_send)

    progress_tracker = SimpleNamespace(
        bot=SimpleNamespace(), chat_id=1, complete_all=AsyncMock()
    )

    result = await service.process_file(
        _external_request(tmp_path), progress_tracker=progress_tracker, task_id="T1"
    )

    assert result is cached
    # Свежая история проставлена ДО доставки (её id виден доставке → кнопки).
    # Инвариант: кеш-хит пишет НОВУЮ строку истории на каждой переотправке.
    service.history.save_processing_history.assert_awaited_once()
    assert seen["history_id"] == 777
    # Кеш-хит не генерирует заново.
    service.llm_gen.optimized_llm_generation.assert_not_awaited()
    # Статус задачи метится так же, как для свежего пути (task_id → хвост).
    assert mark_status.await_args.args[1] == "completed"


@pytest.mark.asyncio
async def test_fresh_miss_delegates_to_optimized(tmp_path, monkeypatch):
    """Промах кеша → process_file делегирует _process_file_optimized (там же
    единый хвост: кеш, история, доставка, статус) и возвращает его результат."""
    import src.services.processing.processing_service as pss

    service = pss.ProcessingService.__new__(pss.ProcessingService)
    service._ensure_monitoring_started = AsyncMock()
    canned = _canned_result()
    service._process_file_optimized = AsyncMock(return_value=canned)
    service.history = SimpleNamespace(
        calculate_file_hash=AsyncMock(return_value="deadbeef"),
        generate_result_cache_key=lambda request, file_hash: "cache-key",
    )
    _patch_process_file_env(monkeypatch, pss, cached=None)

    result = await service.process_file(
        _external_request(tmp_path), progress_tracker=None, task_id="T1"
    )

    service._process_file_optimized.assert_awaited_once()
    assert result is canned


@pytest.mark.asyncio
async def test_pause_sentinel_returns_none(tmp_path, monkeypatch):
    """Пауза на карточке сопоставления: _process_file_optimized → None, и
    process_file возвращает None (гейт карточки — снаружи хвоста, ADR-0003)."""
    import src.services.processing.processing_service as pss

    service = pss.ProcessingService.__new__(pss.ProcessingService)
    service._ensure_monitoring_started = AsyncMock()
    service._process_file_optimized = AsyncMock(return_value=None)
    service.history = SimpleNamespace(
        calculate_file_hash=AsyncMock(return_value="deadbeef"),
        generate_result_cache_key=lambda request, file_hash: "cache-key",
    )
    _patch_process_file_env(monkeypatch, pss, cached=None)

    result = await service.process_file(
        _external_request(tmp_path), progress_tracker=None, task_id="T1"
    )

    assert result is None


# ---------------------------------------------------------------------------
# (б) Возобновление: переведено на единый хвост (ADR-0003)
# ---------------------------------------------------------------------------


def _make_resume_session(*, cache_key, task_id) -> MappingSession:
    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)
    return MappingSession(
        request=request,
        transcription_result=TranscriptionResult(transcription="текст"),
        speaker_mapping={},
        meeting_type="general",
        temp_file_path=None,
        cache_key=cache_key,
        task_id=task_id,
        metrics=SimpleNamespace(total_duration=1.0),
        # Шаблон выбран в основном пути ДО паузы — возобновление берёт его из
        # сессии, не выбирая заново.
        template=SimpleNamespace(id=2, name="Дейли"),
    )


def _stub_resume_deps(service) -> None:
    """Зависимости генерации/учёта для возобновления через единый хвост."""
    service.llm_gen = SimpleNamespace(
        optimized_llm_generation=AsyncMock(return_value={"meeting_title": "Планёрка"}),
        resolve_model_display_name=AsyncMock(return_value="GPT"),
    )
    service.formatter = SimpleNamespace(format_protocol=lambda *a, **k: "# Протокол")
    service.history = SimpleNamespace(
        save_processing_history=AsyncMock(return_value=99),
        cleanup_temp_file=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_resume_caches_unconditionally_after_generation(monkeypatch):
    """ИЗМЕНЕНИЕ по ADR-0003 (решение 3): возобновление кеширует после успешной
    генерации НЕЗАВИСИМО от доставки — раньше кешировало ТОЛЬКО при доставке.
    Повторная загрузка того же файла попадёт в кеш и переотправится."""
    import src.services.processing.completion as completion
    import src.services.processing.processing_service as pss
    import src.services.result_sender as rs
    import src.ux.progress_tracker as pt_mod

    async def run(delivered: bool):
        service = pss.ProcessingService.__new__(pss.ProcessingService)
        _stub_resume_deps(service)

        cache = SimpleNamespace(set=AsyncMock())
        monkeypatch.setattr(completion, "performance_cache", cache)
        monkeypatch.setattr(
            completion.queue_repo, "update_queue_task_status", AsyncMock()
        )
        monkeypatch.setattr(
            pt_mod.ProgressFactory,
            "create_file_processing_tracker",
            AsyncMock(return_value=SimpleNamespace(start_stage=AsyncMock())),
        )
        monkeypatch.setattr(
            rs, "send_result_to_user", AsyncMock(return_value=delivered)
        )

        await service.continue_processing_after_mapping_confirmation(
            session=_make_resume_session(cache_key="ck", task_id="t1"),
            confirmed_mapping={}, bot=SimpleNamespace(), chat_id=1,
        )
        return cache

    # Кеш выставлен и при доставке, и при её провале — безусловно.
    assert (await run(True)).set.await_count == 1
    assert (await run(False)).set.await_count == 1


@pytest.mark.asyncio
async def test_resume_sets_history_id_before_delivery(monkeypatch):
    """ИЗМЕНЕНИЕ по ADR-0003: история пишется ДО доставки и history_id садится на
    результат — возобновлённый протокол теперь несёт кнопки действий. Раньше
    история писалась ПОСЛЕ доставки, её id отбрасывался, и кнопок не было."""
    import src.services.processing.completion as completion
    import src.services.processing.processing_service as pss
    import src.services.result_sender as rs
    import src.ux.progress_tracker as pt_mod

    service = pss.ProcessingService.__new__(pss.ProcessingService)
    _stub_resume_deps(service)
    service.history.save_processing_history = AsyncMock(return_value=555)

    monkeypatch.setattr(
        completion, "performance_cache", SimpleNamespace(set=AsyncMock())
    )
    monkeypatch.setattr(
        completion.queue_repo, "update_queue_task_status", AsyncMock()
    )
    monkeypatch.setattr(
        pt_mod.ProgressFactory,
        "create_file_processing_tracker",
        AsyncMock(return_value=SimpleNamespace(start_stage=AsyncMock())),
    )

    seen = {}

    async def fake_send(bot, chat_id, user_id, request, result, progress_tracker=None):
        seen["history_id"] = result.history_id
        return True

    monkeypatch.setattr(rs, "send_result_to_user", fake_send)

    await service.continue_processing_after_mapping_confirmation(
        session=_make_resume_session(cache_key="ck", task_id="t1"),
        confirmed_mapping={}, bot=SimpleNamespace(), chat_id=1,
    )

    # Доставка увидела history_id — значит история записана ДО неё.
    assert seen["history_id"] == 555


# ---------------------------------------------------------------------------
# (в) Перегенерация: урезанный результат, без replace_speakers (перевернётся)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regen_full_result_and_applies_replace_speakers(monkeypatch):
    """ПЕРЕВЁРНУТ по ADR-0003 (решение 2): перегенерация выровнена по основному
    пути. Раньше строила УРЕЗАННЫЙ результат (template_used={'name':…},
    llm_model_used=None) и НЕ звала replace_speakers_in_text. Теперь — полная
    сборка результата (template_used=model_dump/__dict__ целиком, llm_model_used
    резолвится) и страховка замены спикеров при сохранённом сопоставлении.
    Единый хвост completion.complete_processing делает дрейф невозможным."""
    import src.database as db_module
    import src.services.processing.completion as completion
    import src.services.processing.llm_generation as llm_gen_module
    import src.services.protocol_actions as protocol_actions

    row = {
        "id": 7,
        "user_id": 42,
        "file_name": "meeting.mp3",
        "transcription_text": "полная расшифровка встречи",
        "result_text": "# Старый протокол",
        "speaker_mapping": json.dumps(
            {"SPEAKER_00": "Иван Петров"}, ensure_ascii=False
        ),
        "meeting_type": "daily",
    }
    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(
        db_module.history_repo, "save_processing_result", AsyncMock(return_value=101)
    )

    template = SimpleNamespace(id=5, name="Дейли", content="# {{ meeting_title }}")

    class FakeTemplateService:
        async def get_template_by_id(self, _tid):
            return template

    class FakeLLMGen:
        def __init__(self, *a, **k):
            pass

        async def optimized_llm_generation(self, *a, **k):
            return {"meeting_title": "Планёрка"}

        async def resolve_model_display_name(self):
            return "gpt-5-mini"

    monkeypatch.setattr(llm_gen_module, "LLMGenerationService", FakeLLMGen)

    # Шпион на замену спикеров — теперь перегенерация её ЗОВЁТ (сопоставление есть).
    replace_spy = MagicMock(side_effect=lambda text, mapping: text)
    monkeypatch.setattr(completion, "replace_speakers_in_text", replace_spy)

    captured = {}

    async def fake_send(bot, chat_id, user_id, request, result, progress_tracker=None):
        captured["result"] = result
        return True

    monkeypatch.setattr(protocol_actions, "send_result_to_user", fake_send)

    ok = await protocol_actions.regenerate_protocol(
        bot=AsyncMock(), chat_id=1, telegram_user_id=42,
        history_id=7, template_id=5,
        user_service=SimpleNamespace(), template_service=FakeTemplateService(),
    )

    assert ok is True
    result = captured["result"]
    # Полная сборка результата (весь шаблон, резолв имени модели)
    assert result.template_used == vars(template)
    assert result.llm_model_used == "gpt-5-mini"
    # Страховка замены спикеров применяется к сохранённому сопоставлению
    replace_spy.assert_called_once()
    assert replace_spy.call_args.args[1] == {"SPEAKER_00": "Иван Петров"}
