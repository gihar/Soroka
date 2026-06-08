# Speaker Audio Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При показе UI сопоставления спикеров авто-присылать по одному голосовому сообщению (~15 с, OGG/Opus) на каждого спикера — фрагмент его речи из оригинальной записи — чтобы пользователь сопоставлял спикеров по голосу.

**Architecture:** Три маленьких изолированных модуля (чистая логика выбора окна + нарезка ffmpeg; безопасная отправка voice; оркестратор) вклиниваются в `processing_service._handle_speaker_mapping_confirmation` перед показом клавиатуры. Всё обёрнуто в `try/except` — превью никогда не ломает сопоставление. Данные (`temp_file_path`, сегменты диаризации, `speakers_text`) уже лежат в `mapping_state_cache`, новых хранилищ не нужно.

**Tech Stack:** Python 3.11, aiogram 3, ffmpeg (уже runtime-зависимость), pydantic-settings, pytest (`asyncio_mode = "auto"`), loguru.

**Spec:** `docs/superpowers/specs/2026-06-08-speaker-audio-preview-design.md`

---

## File Structure

| Файл | Ответственность | Действие |
|------|-----------------|----------|
| `src/config.py` | 4 новых настройки фичи | Modify |
| `src/services/audio_fragment_service.py` | Чистый выбор окна + нарезка ffmpeg | Create |
| `src/utils/telegram_safe.py` | `safe_send_voice` — безопасная отправка голосового | Modify |
| `src/ux/speaker_audio_preview.py` | Оркестратор: окно → нарезка → отправка → удаление | Create |
| `src/services/processing/processing_service.py` | Вызов оркестратора перед `show_mapping_confirmation` | Modify |
| `tests/test_audio_fragment_service.py` | Юнит `select_fragment_window` + интеграция `cut_voice_fragment` | Create |
| `tests/test_safe_send_voice.py` | Юнит `safe_send_voice` | Create |
| `tests/test_speaker_audio_preview.py` | Юнит оркестратора | Create |
| `tests/test_mapping_audio_preview_wiring.py` | Юнит вклинивания (порядок + изоляция ошибок) | Create |

**Соглашения проекта (важно для воркера):**
- Тесты начинаются с `sys.path.insert(0, ...)` и импортируют из `src.` (см. `tests/test_speaker_mapping_failure.py`).
- `asyncio_mode = "auto"`, но в проекте к async-тестам ставят `@pytest.mark.asyncio` — делайте так же.
- Запуск всех тестов: `pytest tests/ -v`. ruff: `ruff check src tests`.
- Коммиты — без приписок об авторстве (атрибуция отключена глобально), conventional commits.

---

## Task 1: Конфигурация фичи

**Files:**
- Modify: `src/config.py` (блок «Сопоставление участников (speaker mapping)», после строки с `enable_speaker_mapping_confirmation`, ~стр. 145)

- [ ] **Step 1: Добавить настройки**

В `src/config.py` сразу после строки:

```python
    enable_speaker_mapping_confirmation: bool = Field(False, description="Показывать UI для подтверждения сопоставления спикеров перед генерацией протокола")
```

добавить:

```python

    # Аудиофрагменты спикеров при сопоставлении (показываются вместе с UI подтверждения)
    speaker_audio_preview_enabled: bool = Field(True, description="Присылать голосовые фрагменты речи каждого спикера при показе UI сопоставления")
    speaker_preview_max_seconds: int = Field(15, description="Длина вырезаемого аудиофрагмента спикера (секунды)")
    speaker_preview_min_segment_seconds: float = Field(1.5, description="Минимальная длительность сегмента, считающегося 'весомым' для выбора начала фрагмента (секунды)")
    speaker_preview_bitrate: str = Field("32k", description="Битрейт Opus для голосовых фрагментов спикеров")
```

- [ ] **Step 2: Проверить, что настройки читаются**

Run: `python -c "from src.config import settings; print(settings.speaker_audio_preview_enabled, settings.speaker_preview_max_seconds, settings.speaker_preview_min_segment_seconds, settings.speaker_preview_bitrate)"`
Expected: `True 15 1.5 32k`

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat(config): add speaker audio preview settings"
```

---

## Task 2: `select_fragment_window` — выбор окна (чистая функция)

**Files:**
- Create: `src/services/audio_fragment_service.py`
- Test: `tests/test_audio_fragment_service.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_audio_fragment_service.py`:

```python
"""Тесты выбора окна и нарезки аудиофрагмента спикера."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.audio_fragment_service import select_fragment_window


def _seg(start, end, speaker, text=""):
    return {"start": start, "end": end, "speaker": speaker, "text": text}


def test_picks_first_weighty_segment_start():
    segments = [
        _seg(0.0, 0.5, "SPEAKER_1", "да"),          # короткий, пропускаем
        _seg(2.0, 7.0, "SPEAKER_1", "длинная фраза"),  # первый весомый
        _seg(10.0, 12.0, "SPEAKER_2", "другой"),
    ]
    window = select_fragment_window(segments, "SPEAKER_1", max_seconds=15.0, min_segment_seconds=1.5)
    assert window == (2.0, 15.0)


def test_fallback_to_first_segment_when_all_short():
    segments = [
        _seg(3.0, 3.4, "SPEAKER_1", "ага"),
        _seg(5.0, 5.3, "SPEAKER_1", "да"),
    ]
    window = select_fragment_window(segments, "SPEAKER_1", max_seconds=15.0, min_segment_seconds=1.5)
    assert window == (3.0, 15.0)


def test_duration_is_capped_at_max_seconds():
    segments = [_seg(1.0, 999.0, "SPEAKER_1", "очень длинный монолог")]
    window = select_fragment_window(segments, "SPEAKER_1", max_seconds=10.0, min_segment_seconds=1.5)
    assert window == (1.0, 10.0)


def test_no_segments_for_speaker_returns_none():
    segments = [_seg(0.0, 5.0, "SPEAKER_2", "только второй")]
    assert select_fragment_window(segments, "SPEAKER_1") is None


def test_empty_segments_returns_none():
    assert select_fragment_window([], "SPEAKER_1") is None


def test_invalid_timestamps_return_none():
    segments = [
        {"start": None, "end": None, "speaker": "SPEAKER_1", "text": "битый"},
        {"speaker": "SPEAKER_1", "text": "без таймстампов"},
    ]
    assert select_fragment_window(segments, "SPEAKER_1") is None


def test_input_segments_not_mutated():
    segments = [_seg(2.0, 7.0, "SPEAKER_1"), _seg(0.0, 0.5, "SPEAKER_1")]
    snapshot = [dict(s) for s in segments]
    select_fragment_window(segments, "SPEAKER_1")
    assert segments == snapshot
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `pytest tests/test_audio_fragment_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.audio_fragment_service'`

- [ ] **Step 3: Реализовать `select_fragment_window`**

Создать `src/services/audio_fragment_service.py`:

```python
"""Выбор окна и нарезка короткого аудиофрагмента речи спикера.

Чистая логика выбора (``select_fragment_window``) отделена от ввода-вывода
(``cut_voice_fragment``) — первую легко тестировать без ffmpeg.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


def _segment_duration(segment: Dict[str, Any]) -> Optional[float]:
    """Длительность сегмента в секундах или None, если таймстампы невалидны."""
    start = segment.get("start")
    end = segment.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    duration = float(end) - float(start)
    if duration <= 0:
        return None
    return duration


def select_fragment_window(
    segments: List[Dict[str, Any]],
    speaker_id: str,
    *,
    max_seconds: float = 15.0,
    min_segment_seconds: float = 1.5,
) -> Optional[Tuple[float, float]]:
    """Выбрать окно (start, duration) для голосового фрагмента спикера.

    Берёт сегменты спикера по возрастанию ``start``. Начинает фрагмент с первого
    «весомого» сегмента (длиннее ``min_segment_seconds``); если таких нет — с самого
    первого валидного сегмента спикера. Длительность ограничена ``max_seconds``
    (ffmpeg сам остановится на конце файла, если запись короче).

    Возвращает None, если у спикера нет сегментов с валидными таймстампами.
    Не мутирует входные данные.
    """
    speaker_segments = [
        s for s in segments
        if s.get("speaker") == speaker_id and _segment_duration(s) is not None
    ]
    if not speaker_segments:
        return None

    speaker_segments = sorted(speaker_segments, key=lambda s: float(s["start"]))

    weighty = next(
        (s for s in speaker_segments if _segment_duration(s) >= min_segment_seconds),
        None,
    )
    chosen = weighty if weighty is not None else speaker_segments[0]

    return (float(chosen["start"]), float(max_seconds))
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `pytest tests/test_audio_fragment_service.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/services/audio_fragment_service.py tests/test_audio_fragment_service.py
git commit -m "feat(audio): select_fragment_window for speaker preview clips"
```

---

## Task 3: `cut_voice_fragment` — нарезка через ffmpeg (async)

**Files:**
- Modify: `src/services/audio_fragment_service.py`
- Test: `tests/test_audio_fragment_service.py`

- [ ] **Step 1: Добавить падающий интеграционный тест**

В конец `tests/test_audio_fragment_service.py` добавить:

```python
import shutil
import subprocess


def _ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe не установлены в окружении",
)
async def test_cut_voice_fragment_produces_valid_ogg(tmp_path):
    from src.services.audio_fragment_service import cut_voice_fragment

    # Сгенерировать 20-секундный тон как исходник
    src = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-y", str(src)],
        capture_output=True, text=True, check=True,
    )

    out = tmp_path / "clip.ogg"
    ok = await cut_voice_fragment(str(src), start=5.0, duration=8.0, out_path=str(out))

    assert ok is True
    assert out.exists() and out.stat().st_size > 0
    # Длительность близка к запрошенным 8 с
    assert abs(_ffprobe_duration(str(out)) - 8.0) < 1.0


@pytest.mark.asyncio
async def test_cut_voice_fragment_missing_source_returns_false(tmp_path):
    from src.services.audio_fragment_service import cut_voice_fragment

    out = tmp_path / "clip.ogg"
    ok = await cut_voice_fragment(str(tmp_path / "nope.wav"), start=0.0, duration=5.0, out_path=str(out))
    assert ok is False
    assert not out.exists()
```

- [ ] **Step 2: Запустить — новые тесты падают**

Run: `pytest tests/test_audio_fragment_service.py -k cut_voice_fragment -v`
Expected: FAIL — `ImportError: cannot import name 'cut_voice_fragment'`

- [ ] **Step 3: Реализовать `cut_voice_fragment`**

В `src/services/audio_fragment_service.py` добавить функцию (в конец файла):

```python
async def cut_voice_fragment(
    src_path: str,
    start: float,
    duration: float,
    out_path: str,
    *,
    bitrate: str = "32k",
) -> bool:
    """Вырезать фрагмент [start, start+duration] из src_path в OGG/Opus (out_path).

    Использует ffmpeg через ``asyncio.create_subprocess_exec`` — не блокирует
    event loop. ``-ss`` стоит ДО ``-i`` для быстрого seek; ``-vn`` отбрасывает
    видеодорожку (исходник может быть .mp4/.mov).

    Возвращает True при успехе (код возврата 0 и непустой выходной файл), иначе
    False. Исключения не пробрасывает.
    """
    if not os.path.exists(src_path):
        logger.warning(f"cut_voice_fragment: исходный файл не найден: {src_path}")
        return False

    cmd = [
        "ffmpeg",
        "-ss", str(start),
        "-i", src_path,
        "-t", str(duration),
        "-vn",
        "-ac", "1",
        "-c:a", "libopus",
        "-b:a", bitrate,
        "-y",
        out_path,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="replace") if stderr else ""
            logger.error(f"cut_voice_fragment: ffmpeg вернул {process.returncode}: {err[-500:]}")
            return False

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            logger.error(f"cut_voice_fragment: пустой/отсутствующий выход: {out_path}")
            return False

        return True

    except Exception as e:
        logger.error(f"cut_voice_fragment: ошибка запуска ffmpeg: {e}")
        return False
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `pytest tests/test_audio_fragment_service.py -v`
Expected: PASS (9 passed; интеграционный — PASS, если ffmpeg есть, иначе SKIPPED)

- [ ] **Step 5: Commit**

```bash
git add src/services/audio_fragment_service.py tests/test_audio_fragment_service.py
git commit -m "feat(audio): cut_voice_fragment via async ffmpeg to ogg/opus"
```

---

## Task 4: `safe_send_voice` — безопасная отправка голосового

**Files:**
- Modify: `src/utils/telegram_safe.py` (добавить функцию после `safe_send_document`, ~стр. 289)
- Test: `tests/test_safe_send_voice.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_safe_send_voice.py`:

```python
"""Тест безопасной отправки голосового сообщения."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_safe_send_voice_calls_rate_limited_send(monkeypatch):
    import src.utils.telegram_safe as ts

    calls = {}

    async def fake_safe_send_with_retry(method, **kwargs):
        calls["method"] = method
        calls["kwargs"] = kwargs
        return "SENT"

    monkeypatch.setattr(
        ts.telegram_rate_limiter, "safe_send_with_retry", fake_safe_send_with_retry
    )

    class FakeBot:
        async def send_voice(self, **kwargs):
            return None

    bot = FakeBot()
    result = await ts.safe_send_voice(
        bot, chat_id=123, voice="path/clip.ogg", caption="🔊 SPEAKER_1"
    )

    assert result == "SENT"
    assert calls["method"] == bot.send_voice
    assert calls["kwargs"]["chat_id"] == 123
    assert calls["kwargs"]["voice"] == "path/clip.ogg"
    assert calls["kwargs"]["caption"] == "🔊 SPEAKER_1"


@pytest.mark.asyncio
async def test_safe_send_voice_swallows_exceptions(monkeypatch):
    import src.utils.telegram_safe as ts

    async def boom(method, **kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(ts.telegram_rate_limiter, "safe_send_with_retry", boom)

    class FakeBot:
        async def send_voice(self, **kwargs):
            return None

    result = await ts.safe_send_voice(FakeBot(), chat_id=1, voice="x.ogg")
    assert result is None
```

- [ ] **Step 2: Запустить — должен упасть**

Run: `pytest tests/test_safe_send_voice.py -v`
Expected: FAIL — `AttributeError: module 'src.utils.telegram_safe' has no attribute 'safe_send_voice'`

- [ ] **Step 3: Реализовать `safe_send_voice`**

В `src/utils/telegram_safe.py` после функции `safe_send_document` (после строки 289) добавить:

```python
async def safe_send_voice(
    bot,
    chat_id: int,
    voice: Union[str, FSInputFile],
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
    disable_notification: Optional[bool] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасная отправка голосового сообщения через bot

    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        voice: Путь к OGG/Opus файлу или FSInputFile
        caption: Подпись к голосовому
        parse_mode: Режим парсинга
        disable_notification: Отключить уведомление
        **kwargs: Дополнительные параметры

    Returns:
        Отправленное сообщение или None при ошибке
    """
    try:
        result = await telegram_rate_limiter.safe_send_with_retry(
            bot.send_voice,
            chat_id=chat_id,
            voice=voice,
            caption=caption,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            **kwargs
        )

        if result is None:
            logger.warning(f"Не удалось отправить голосовое в чат {chat_id}")

        return result

    except Exception as e:
        logger.error(f"Критическая ошибка в safe_send_voice: {e}")
        return None
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `pytest tests/test_safe_send_voice.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/utils/telegram_safe.py tests/test_safe_send_voice.py
git commit -m "feat(telegram): safe_send_voice wrapper"
```

---

## Task 5: Оркестратор `send_speaker_audio_previews`

**Files:**
- Create: `src/ux/speaker_audio_preview.py`
- Test: `tests/test_speaker_audio_preview.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_speaker_audio_preview.py`:

```python
"""Тесты оркестратора аудиопревью спикеров."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.ux.speaker_audio_preview as preview


def _diarization():
    return {
        "speakers": ["SPEAKER_1", "SPEAKER_2"],
        "segments": [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_1", "text": "привет всем"},
            {"start": 6.0, "end": 9.0, "speaker": "SPEAKER_2", "text": "да, начнём"},
        ],
    }


@pytest.mark.asyncio
async def test_no_temp_file_sends_nothing(monkeypatch):
    sent = []

    async def fake_send_voice(*a, **k):
        sent.append(k)
        return "MSG"

    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1", "SPEAKER_2"],
        diarization_data=_diarization(),
        temp_file_path=None,
        speakers_text={},
    )
    assert sent == []


@pytest.mark.asyncio
async def test_sends_one_voice_per_speaker_in_order(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    sent_order = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        # имитируем успешную нарезку — создаём непустой файл
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        sent_order.append(caption)
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1", "SPEAKER_2"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={"SPEAKER_1": "привет всем", "SPEAKER_2": "да, начнём"},
    )

    assert len(sent_order) == 2
    assert "SPEAKER_1" in sent_order[0]
    assert "SPEAKER_2" in sent_order[1]


@pytest.mark.asyncio
async def test_one_speaker_cut_failure_does_not_block_others(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    sent = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        # SPEAKER_1 (start=0.0) падает, SPEAKER_2 (start=6.0) успешен
        if start == 0.0:
            return False
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        sent.append(caption)
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1", "SPEAKER_2"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert len(sent) == 1
    assert "SPEAKER_2" in sent[0]


@pytest.mark.asyncio
async def test_temp_clips_are_deleted(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    created_paths = []

    async def fake_cut(src_path, start, duration, out_path, **k):
        created_paths.append(out_path)
        with open(out_path, "wb") as f:
            f.write(b"ogg")
        return True

    async def fake_send_voice(bot, chat_id, voice, caption=None, **k):
        return "MSG"

    monkeypatch.setattr(preview, "cut_voice_fragment", fake_cut)
    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)
    # Пишем клипы во временную папку теста, а не в ./temp
    monkeypatch.setattr(preview, "_preview_dir", lambda: str(tmp_path))

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )

    assert created_paths, "клип должен был создаться"
    for p in created_paths:
        assert not os.path.exists(p), f"временный клип не удалён: {p}"


@pytest.mark.asyncio
async def test_disabled_by_config_sends_nothing(monkeypatch, tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"fake-audio")

    sent = []

    async def fake_send_voice(*a, **k):
        sent.append(k)
        return "MSG"

    monkeypatch.setattr(preview, "safe_send_voice", fake_send_voice)
    monkeypatch.setattr(preview.settings, "speaker_audio_preview_enabled", False)

    await preview.send_speaker_audio_previews(
        bot=object(), chat_id=1, user_id=7,
        speakers=["SPEAKER_1"],
        diarization_data=_diarization(),
        temp_file_path=str(src),
        speakers_text={},
    )
    assert sent == []
```

- [ ] **Step 2: Запустить — должны упасть**

Run: `pytest tests/test_speaker_audio_preview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ux.speaker_audio_preview'`

- [ ] **Step 3: Реализовать оркестратор**

Создать `src/ux/speaker_audio_preview.py`:

```python
"""Оркестратор аудиопревью спикеров.

При показе UI сопоставления присылает по одному голосовому сообщению на каждого
спикера: окно выбирается из сегментов диаризации, фрагмент режется из оригинального
файла через ffmpeg и отправляется как voice. Фича вспомогательная — любая ошибка
логируется и проглатывается, сопоставление это не ломает.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional

from loguru import logger

from src.config import settings
from src.services.audio_fragment_service import cut_voice_fragment, select_fragment_window
from src.utils.telegram_safe import safe_send_voice

_MAX_CAPTION_SNIPPET = 120


def _preview_dir() -> str:
    """Каталог для временных клипов (тот же temp/, что чистит cleanup_service)."""
    return settings.temp_dir


def _build_caption(speaker_id: str, speakers_text: Optional[Dict[str, str]]) -> str:
    """Подпись голосового: '🔊 SPEAKER_N' + короткий однострочный сниппет текста."""
    caption = f"🔊 {speaker_id}"
    if speakers_text:
        text = (speakers_text.get(speaker_id) or "").strip().replace("\n", " ")
        if text:
            snippet = text[:_MAX_CAPTION_SNIPPET]
            if len(text) > _MAX_CAPTION_SNIPPET:
                snippet += "…"
            caption = f"{caption}\n«{snippet}»"
    return caption


async def _prepare_clip(
    speaker_id: str,
    diarization_data: Dict[str, Any],
    temp_file_path: str,
    user_id: int,
) -> Optional[str]:
    """Выбрать окно и вырезать клип спикера. Возвращает путь к .ogg или None."""
    segments = diarization_data.get("segments", [])
    window = select_fragment_window(
        segments,
        speaker_id,
        max_seconds=float(settings.speaker_preview_max_seconds),
        min_segment_seconds=float(settings.speaker_preview_min_segment_seconds),
    )
    if window is None:
        logger.debug(f"Аудиопревью: нет окна для {speaker_id}, пропускаю")
        return None

    start, duration = window
    out_path = os.path.join(_preview_dir(), f"preview_{user_id}_{speaker_id}.ogg")

    ok = await cut_voice_fragment(
        temp_file_path, start, duration, out_path,
        bitrate=settings.speaker_preview_bitrate,
    )
    if not ok:
        logger.warning(f"Аудиопревью: не удалось вырезать клип для {speaker_id}")
        return None
    return out_path


async def send_speaker_audio_previews(
    bot: Any,
    chat_id: int,
    user_id: int,
    speakers: List[str],
    diarization_data: Dict[str, Any],
    temp_file_path: Optional[str],
    speakers_text: Optional[Dict[str, str]] = None,
) -> None:
    """Прислать голосовые фрагменты речи каждого спикера.

    Никогда не пробрасывает исключения — фича вспомогательная и не должна мешать
    показу UI сопоставления.
    """
    try:
        if not settings.speaker_audio_preview_enabled:
            return
        if not temp_file_path or not os.path.exists(temp_file_path):
            logger.info("Аудиопревью: исходный файл недоступен, пропускаю превью")
            return

        # Нарезаем все клипы параллельно, чтобы не задерживать показ UI.
        from aiogram.types import FSInputFile

        clip_paths = await asyncio.gather(
            *[
                _prepare_clip(speaker_id, diarization_data, temp_file_path, user_id)
                for speaker_id in speakers
            ],
            return_exceptions=True,
        )

        # Отправляем по порядку спикеров; каждый клип удаляем сразу после отправки.
        for speaker_id, clip in zip(speakers, clip_paths):
            if isinstance(clip, Exception):
                logger.warning(f"Аудиопревью: ошибка подготовки клипа {speaker_id}: {clip}")
                continue
            if not clip:
                continue
            try:
                await safe_send_voice(
                    bot,
                    chat_id=chat_id,
                    voice=FSInputFile(clip),
                    caption=_build_caption(speaker_id, speakers_text),
                    parse_mode=None,
                )
            except Exception as send_error:
                logger.warning(f"Аудиопревью: ошибка отправки {speaker_id}: {send_error}")
            finally:
                try:
                    if os.path.exists(clip):
                        os.remove(clip)
                except OSError as rm_error:
                    logger.debug(f"Аудиопревью: не удалось удалить клип {clip}: {rm_error}")

    except Exception as e:
        logger.error(f"Аудиопревью: непредвиденная ошибка, пропускаю превью: {e}", exc_info=True)
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `pytest tests/test_speaker_audio_preview.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ux/speaker_audio_preview.py tests/test_speaker_audio_preview.py
git commit -m "feat(ux): orchestrate speaker audio previews"
```

---

## Task 6: Вклинивание в `_handle_speaker_mapping_confirmation`

**Files:**
- Modify: `src/services/processing/processing_service.py` (метод `_handle_speaker_mapping_confirmation`, перед вызовом `show_mapping_confirmation`, ~стр. 503-514)
- Test: `tests/test_mapping_audio_preview_wiring.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_mapping_audio_preview_wiring.py`:

```python
"""Превью аудио вызывается ПЕРЕД показом UI сопоставления и не ломает его при ошибке."""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_service():
    # Метод не использует self — создаём инстанс без __init__.
    from src.services.processing.processing_service import ProcessingService
    return ProcessingService.__new__(ProcessingService)


def _make_args():
    request = SimpleNamespace(
        user_id=7,
        participants_list=[{"name": "Иван Иванов"}],
        model_dump=lambda: {},
    )
    transcription_result = SimpleNamespace(
        diarization={
            "speakers": ["SPEAKER_1", "SPEAKER_2"],
            "segments": [
                {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_1", "text": "привет"},
                {"start": 6.0, "end": 9.0, "speaker": "SPEAKER_2", "text": "да"},
            ],
        },
        transcription="t",
        formatted_transcript="f",
        speakers_text={"SPEAKER_1": "привет", "SPEAKER_2": "да"},
        speakers_summary="s",
    )
    progress_tracker = SimpleNamespace(
        update_task=None,
        message=SimpleNamespace(),
        bot=SimpleNamespace(),
        chat_id=42,
    )
    processing_metrics = SimpleNamespace(to_dict=lambda: {})
    return request, transcription_result, progress_tracker, processing_metrics


def _patch_common(monkeypatch, call_log, previews_raises=False):
    import src.services.mapping_state_cache as msc
    import src.utils.telegram_safe as ts
    import src.ux.speaker_audio_preview as preview
    import src.ux.speaker_mapping_ui as ui

    async def fake_save_state(user_id, state_data):
        call_log.append("save_state")

    monkeypatch.setattr(msc.mapping_state_cache, "save_state", fake_save_state)

    async def fake_edit(*a, **k):
        return None

    monkeypatch.setattr(ts, "safe_edit_text", fake_edit)

    async def fake_previews(**kwargs):
        call_log.append("previews")
        if previews_raises:
            raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(preview, "send_speaker_audio_previews", fake_previews)

    async def fake_show(**kwargs):
        call_log.append("show")
        return SimpleNamespace()  # truthy message => пауза

    monkeypatch.setattr(ui, "show_mapping_confirmation", fake_show)


@pytest.mark.asyncio
async def test_previews_called_before_show(monkeypatch):
    call_log = []
    _patch_common(monkeypatch, call_log)

    service = _make_service()
    request, tr, pt, pm = _make_args()

    result = await service._handle_speaker_mapping_confirmation(
        request=request,
        transcription_result=tr,
        speaker_mapping={"SPEAKER_1": "Иван Иванов"},
        meeting_type="general",
        temp_file_path="temp/audio.wav",
        processing_metrics=pm,
        progress_tracker=pt,
    )

    assert result is None  # пауза
    assert "previews" in call_log and "show" in call_log
    assert call_log.index("previews") < call_log.index("show")


@pytest.mark.asyncio
async def test_preview_failure_does_not_block_show(monkeypatch):
    call_log = []
    _patch_common(monkeypatch, call_log, previews_raises=True)

    service = _make_service()
    request, tr, pt, pm = _make_args()

    result = await service._handle_speaker_mapping_confirmation(
        request=request,
        transcription_result=tr,
        speaker_mapping={},
        meeting_type="general",
        temp_file_path="temp/audio.wav",
        processing_metrics=pm,
        progress_tracker=pt,
    )

    assert result is None  # пауза всё равно наступает
    assert "show" in call_log  # UI сопоставления показан несмотря на ошибку превью
```

- [ ] **Step 2: Запустить — должен упасть**

Run: `pytest tests/test_mapping_audio_preview_wiring.py -v`
Expected: FAIL — `test_previews_called_before_show` падает, т.к. `"previews"` ещё не в `call_log` (вклинивания нет).

- [ ] **Step 3: Вклинить вызов превью**

В `src/services/processing/processing_service.py`, в методе `_handle_speaker_mapping_confirmation`, найти блок (около стр. 500-514):

```python
            mapped_speakers = set(speaker_mapping.keys())
            unmapped_speakers = [s for s in all_speakers if s not in mapped_speakers]

            speakers_text = transcription_result.speakers_text

            confirmation_message = await show_mapping_confirmation(
```

и вставить вызов превью **между** `speakers_text = ...` и `confirmation_message = await show_mapping_confirmation(`:

```python
            mapped_speakers = set(speaker_mapping.keys())
            unmapped_speakers = [s for s in all_speakers if s not in mapped_speakers]

            speakers_text = transcription_result.speakers_text

            # Аудиопревью: присылаем голосовой фрагмент на каждого спикера ПЕРЕД
            # сообщением с клавиатурой. Обёрнуто в try/except — превью не должно
            # мешать показу UI сопоставления.
            try:
                from src.ux.speaker_audio_preview import send_speaker_audio_previews
                await send_speaker_audio_previews(
                    bot=progress_tracker.bot,
                    chat_id=progress_tracker.chat_id,
                    user_id=request.user_id,
                    speakers=all_speakers,
                    diarization_data=transcription_result.diarization,
                    temp_file_path=temp_file_path,
                    speakers_text=speakers_text,
                )
            except Exception as preview_error:
                logger.warning(
                    f"Не удалось отправить аудиопревью спикеров: {preview_error}"
                )

            confirmation_message = await show_mapping_confirmation(
```

- [ ] **Step 4: Запустить тесты — должны пройти**

Run: `pytest tests/test_mapping_audio_preview_wiring.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/services/processing/processing_service.py tests/test_mapping_audio_preview_wiring.py
git commit -m "feat(processing): send speaker audio previews before mapping UI"
```

---

## Task 7: Финальная проверка и линт

**Files:** нет изменений кода (только проверки)

- [ ] **Step 1: Прогнать весь набор тестов фичи**

Run: `pytest tests/test_audio_fragment_service.py tests/test_safe_send_voice.py tests/test_speaker_audio_preview.py tests/test_mapping_audio_preview_wiring.py -v`
Expected: PASS (все; интеграционный нарезки — PASS при наличии ffmpeg)

- [ ] **Step 2: Прогнать полный набор тестов (регрессий нет)**

Run: `pytest tests/ -q`
Expected: PASS — все существующие тесты проходят, новых падений нет.

- [ ] **Step 3: Линт**

Run: `ruff check src tests`
Expected: без ошибок в новых/изменённых файлах (`audio_fragment_service.py`, `speaker_audio_preview.py`, `telegram_safe.py`, `config.py`, тесты). Исправить замечания (в основном порядок импортов `I001`).

- [ ] **Step 4: Финальный коммит линт-правок (если были)**

```bash
git add -A
git commit -m "style: ruff fixes for speaker audio preview"
```

---

## Self-Review (выполнено при написании плана)

**Покрытие спеки:**
- Авто-отправка voice на каждого спикера → Task 5 + Task 6 ✓
- Окно ~15 с от первого «весомого» сегмента → Task 2 (`select_fragment_window`) ✓
- Нарезка ffmpeg в OGG/Opus, async, не блокирует loop → Task 3 (`cut_voice_fragment`) ✓
- Безопасная rate-limited отправка → Task 4 (`safe_send_voice`) ✓
- Подпись `🔊 SPEAKER_N` + сниппет → Task 5 (`_build_caption`) ✓
- Вклинивание перед `show_mapping_confirmation`, порядок сообщений → Task 6 ✓
- Изоляция ошибок (превью не ломает сопоставление) → Task 5 (внутренний try/except) + Task 6 (внешний try/except) + тест `test_preview_failure_does_not_block_show` ✓
- `temp_file_path` отсутствует → тихий пропуск → Task 5 + тест `test_no_temp_file_sends_nothing` ✓
- Удаление временных клипов → Task 5 (`finally`) + тест `test_temp_clips_are_deleted` ✓
- 4 настройки конфига → Task 1 ✓
- Тесты (юнит окна, оркестратора; интеграция нарезки) → Tasks 2/3/5/6 ✓

**Согласованность типов/имён:** `select_fragment_window(segments, speaker_id, *, max_seconds, min_segment_seconds) -> (start, duration)|None`, `cut_voice_fragment(src_path, start, duration, out_path, *, bitrate) -> bool`, `safe_send_voice(bot, chat_id, voice, caption, ...)`, `send_speaker_audio_previews(bot, chat_id, user_id, speakers, diarization_data, temp_file_path, speakers_text)` — имена и сигнатуры одинаковы во всех задачах и тестах. ✓

**Плейсхолдеры:** не обнаружены — весь код приведён целиком. ✓
