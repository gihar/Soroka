"""Пресет как полный адрес провайдера: ключ и параметры (#114, ADR-0007).

Швы существующие: временная файловая база (как в характеризации хранилища) и
граница клиента модели (как в характеризации генератора). Внутрь хранилища и
кеша клиентов тесты не заглядывают — проверяют, что доехало до вызова.
"""
import pytest

from src.config import OpenAIModelPreset, settings


@pytest.fixture
def preset_repo(test_db):
    from src.database.model_preset_repo import ModelPresetRepository

    return ModelPresetRepository(test_db)


# --------------------------------------------------- ключ пресета из окружения


@pytest.mark.asyncio
async def test_config_preset_key_reaches_storage(preset_repo, monkeypatch):
    """Пресет объявлен в окружении вместе со своим ключом — ключ доезжает в хранилище."""
    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="qwen_plus",
            name="Qwen: plus",
            model="qwen3.7-plus",
            base_url="https://token-plan.example/compatible-mode/v1",
            api_key="sk-sp-qwen",
        )
    ])

    await preset_repo.sync_from_config()

    stored = await preset_repo.get_by_key("qwen_plus")
    assert stored["api_key"] == "sk-sp-qwen"


@pytest.mark.asyncio
async def test_resync_keeps_key_set_by_admin_command(preset_repo, monkeypatch):
    """Ключ, заданный вручную, переживает пересинк из конфигурации без ключа."""
    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="openrouter_gpt5",
            name="OpenRouter: gpt-5",
            model="openai/gpt-5",
            base_url="https://openrouter.ai/api/v1",
        )
    ])
    await preset_repo.sync_from_config()
    await preset_repo.upsert(
        key="openrouter_gpt5",
        name="OpenRouter: gpt-5",
        model="openai/gpt-5",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-набранный-руками",
    )

    await preset_repo.sync_from_config()

    stored = await preset_repo.get_by_key("openrouter_gpt5")
    assert stored["api_key"] == "sk-or-набранный-руками"


# --------------------------------------------- модели дешёвых шагов в пресете


@pytest.mark.asyncio
async def test_config_cheap_step_models_reach_storage(preset_repo, monkeypatch):
    """Модели этапа анализа и сопоставления объявлены в окружении — доезжают в хранилище."""
    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="openrouter_gpt5",
            name="OpenRouter: gpt-5",
            model="openai/gpt-5",
            base_url="https://openrouter.ai/api/v1",
            analysis_model="openai/gpt-5-mini",
            mapping_model="openai/gpt-5-nano",
        )
    ])

    await preset_repo.sync_from_config()

    stored = await preset_repo.get_by_key("openrouter_gpt5")
    assert stored["analysis_model"] == "openai/gpt-5-mini"
    assert stored["mapping_model"] == "openai/gpt-5-nano"


@pytest.mark.asyncio
async def test_preset_without_cheap_models_stores_them_empty(preset_repo):
    """Пресет без моделей дешёвых шагов хранит их пустыми — значит «основная модель»."""
    await preset_repo.upsert(
        key="qwen_plus", name="Qwen: plus", model="qwen3.7-plus",
        base_url="https://token-plan.example/compatible-mode/v1",
    )

    stored = await preset_repo.get_by_key("qwen_plus")
    assert not stored["analysis_model"]
    assert not stored["mapping_model"]


@pytest.mark.asyncio
async def test_resync_keeps_cheap_models_set_by_admin(preset_repo, monkeypatch):
    """Модели дешёвых шагов, заданные вручную, переживают пересинк из конфигурации."""
    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="openrouter_gpt5",
            name="OpenRouter: gpt-5",
            model="openai/gpt-5",
            base_url="https://openrouter.ai/api/v1",
        )
    ])
    await preset_repo.sync_from_config()
    await preset_repo.upsert(
        key="openrouter_gpt5", name="OpenRouter: gpt-5", model="openai/gpt-5",
        base_url="https://openrouter.ai/api/v1",
        analysis_model="openai/gpt-5-nano",
    )

    await preset_repo.sync_from_config()

    stored = await preset_repo.get_by_key("openrouter_gpt5")
    assert stored["analysis_model"] == "openai/gpt-5-nano"


# ------------------------------------------- параметры провайдера в хранилище


@pytest.mark.asyncio
async def test_storage_keeps_provider_params_as_dicts(preset_repo):
    """Пресет несёт словарь полей тела и словарь заголовков; читаются словарями."""
    await preset_repo.upsert(
        key="qwen_plus",
        name="Qwen: plus",
        model="qwen3.7-plus",
        base_url="https://token-plan.example/compatible-mode/v1",
        extra_body={"enable_thinking": False},
        extra_headers={"X-Dashscope-Plan": "token"},
    )

    stored = await preset_repo.get_by_key("qwen_plus")
    assert stored["extra_body"] == {"enable_thinking": False}
    assert stored["extra_headers"] == {"X-Dashscope-Plan": "token"}


@pytest.mark.asyncio
async def test_preset_without_provider_params_reads_empty_dicts(preset_repo):
    """Пресет без параметров провайдера отдаёт пустые словари, а не NULL."""
    await preset_repo.upsert(
        key="plain", name="Plain", model="gpt-5", base_url="https://openrouter.ai/api/v1",
    )

    stored = await preset_repo.get_by_key("plain")
    assert stored["extra_body"] == {}
    assert stored["extra_headers"] == {}


@pytest.mark.asyncio
async def test_corrupted_provider_params_do_not_break_the_preset(test_db, preset_repo):
    """Испорченные параметры в базе не валят пресет: шаг идёт без них."""
    import aiosqlite

    await preset_repo.upsert(
        key="broken", name="Broken", model="gpt-5", base_url="https://openrouter.ai/api/v1",
    )
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "UPDATE model_presets SET extra_body = 'не JSON', extra_headers = '[1, 2]' "
            "WHERE key = 'broken'"
        )
        await db.commit()

    stored = await preset_repo.get_by_key("broken")
    assert stored["extra_body"] == {}
    assert stored["extra_headers"] == {}
    assert stored["model"] == "gpt-5", "остальной пресет читается как обычно"


@pytest.mark.asyncio
async def test_config_provider_params_reach_storage(preset_repo, monkeypatch):
    """Параметры провайдера объявлены в окружении — доезжают в хранилище как есть."""
    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="qwen_plus",
            name="Qwen: plus",
            model="qwen3.7-plus",
            base_url="https://token-plan.example/compatible-mode/v1",
            api_key="sk-sp-qwen",
            extra_body={"enable_thinking": False},
            extra_headers={"X-Dashscope-Plan": "token"},
        )
    ])

    await preset_repo.sync_from_config()

    stored = await preset_repo.get_by_key("qwen_plus")
    assert stored["extra_body"] == {"enable_thinking": False}
    assert stored["extra_headers"] == {"X-Dashscope-Plan": "token"}


@pytest.mark.asyncio
async def test_existing_database_migrates_without_manual_steps(tmp_path):
    """База с пресетами старой схемы принимает параметры провайдера после запуска."""
    import aiosqlite

    from src.database.database import Database
    from src.database.model_preset_repo import ModelPresetRepository

    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            CREATE TABLE model_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                model TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT,
                admin_only BOOLEAN DEFAULT 0,
                is_enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute(
            "INSERT INTO model_presets (key, name, model, base_url, api_key) "
            "VALUES ('legacy', 'Legacy', 'openai/gpt-5', "
            "'https://openrouter.ai/api/v1', 'sk-or-старый')"
        )
        await conn.commit()

    db = Database(db_path=db_path)
    await db.init_db()

    repo = ModelPresetRepository(db)
    migrated = await repo.get_by_key("legacy")
    assert migrated["api_key"] == "sk-or-старый", "старый пресет пережил миграцию"
    assert migrated["extra_body"] == {}
    assert migrated["extra_headers"] == {}
    assert not migrated["analysis_model"], "дешёвые шаги идут на основную модель"
    assert not migrated["mapping_model"]

    await repo.upsert(
        key="legacy", name="Legacy", model="openai/gpt-5",
        base_url="https://openrouter.ai/api/v1",
        extra_headers={"X-Title": "Soroka"},
        analysis_model="openai/gpt-5-mini",
    )
    updated = await repo.get_by_key("legacy")
    assert updated["extra_headers"] == {"X-Title": "Soroka"}
    assert updated["analysis_model"] == "openai/gpt-5-mini"


# ------------------------------------- от объявления в окружении до вызова модели


@pytest.mark.asyncio
async def test_preset_declared_in_environment_serves_the_whole_path(
    test_db, preset_repo, app_settings_repo, monkeypatch
):
    """Пресет объявлен в окружении — весь путь идёт его ключом, адресом и параметрами.

    Общего ключа в окружении нет: деплой целиком на подписке — это ровно то, что
    #115 обещает показать.
    """
    import json
    from unittest.mock import MagicMock

    import openai

    import src.services.speaker_mapping_service as sms
    from src.models.diarization import Diarization, Segment
    from src.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
    from src.reliability.rate_limiter import RateLimitConfig, RateLimiter
    from src.reliability.retry import RetryConfig, RetryManager
    from src.services.processing.llm_generation import resolve_active_preset

    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_models", [
        OpenAIModelPreset(
            key="qwen_plus",
            name="Qwen: plus",
            model="qwen3.7-plus",
            base_url="https://token-plan.example/compatible-mode/v1",
            api_key="sk-sp-qwen",
            extra_body={"enable_thinking": False},
        )
    ])
    await preset_repo.sync_from_config()
    await app_settings_repo.set_active_model_key("qwen_plus", admin_id=42)

    from src.llm.protocol_generator import ProtocolGenerator

    gen = ProtocolGenerator(
        retry_manager=RetryManager(RetryConfig(max_attempts=1, base_delay=0.001, jitter=False)),
        circuit_breaker=CircuitBreaker(
            "test_env_preset",
            CircuitBreakerConfig(failure_threshold=3, recovery_timeout=0.05, timeout=5.0),
        ),
        rate_limiter=RateLimiter(
            "test_env_preset_api",
            RateLimitConfig(requests_per_window=1000, window_size=60.0, burst_limit=1000),
        ),
    )
    assert gen.default_client is None, "без общего ключа глобального клиента нет"
    assert gen.is_available() is True, "пригодный пресет объявлен — модуль готов"

    preset_client = MagicMock(name="preset_client")
    built = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: (built.append(kw), preset_client)[1])
    monkeypatch.setattr(settings, "log_cache_metrics", False)
    monkeypatch.setattr(sms, "protocol_generator", gen)

    def _response(payload):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = json.dumps(payload, ensure_ascii=False)
        return resp

    active = await resolve_active_preset(
        app_settings_repo=app_settings_repo, preset_repo=preset_repo
    )

    preset_client.chat.completions.create.return_value = _response(
        {"meeting_type": "status", "speaker_mappings": {"SPEAKER_0": "Анна Петрова"},
         "confidence_scores": {"SPEAKER_0": 0.95}, "unmapped_speakers": []}
    )
    mapping, meeting_type = await sms.SpeakerMappingService().map_speakers_to_participants(
        diarization_data=Diarization(segments=[
            Segment(speaker="SPEAKER_0", text="Привет, начнём статус.", start=0.0, end=2.0),
        ]),
        participants=[{"name": "Анна Петрова", "role": "менеджер"}],
        transcription_text="Привет, начнём статус.",
        preset=active,
    )
    assert mapping == {"SPEAKER_0": "Анна Петрова"}
    assert meeting_type == "status"

    preset_client.chat.completions.create.side_effect = [
        _response({"meeting_type": "status", "speaker_mappings": {},
                   "analysis_confidence": 0.9}),
        _response({"protocol_data": {"decisions": "решения"}, "quality_score": 0.8}),
    ]
    result = await gen.generate(
        preset=active, transcription="SPEAKER_0: привет.",
        template_variables={"decisions": ""},
    )

    assert result["decisions"] == "решения"
    assert built[0]["api_key"] == "sk-sp-qwen"
    assert built[0]["base_url"] == "https://token-plan.example/compatible-mode/v1"

    calls = preset_client.chat.completions.create.call_args_list
    assert len(calls) == 3, "сопоставление, анализ и генерация — все у пресета"
    for call in calls:
        assert call.kwargs["model"] == "qwen3.7-plus"
        assert call.kwargs["extra_body"] == {"enable_thinking": False}
