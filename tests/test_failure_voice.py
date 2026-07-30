"""Голос сбоя: следующий шаг обязан соответствовать причине (#прод-30.07).

Инцидент 2026-07-30 показал три дефекта разом.

1. Классификация не срабатывала: проверка `"память" in text` не ловит «памяти»
   — русская флексия. Реальный прод-текст «Высокое использование памяти: 91.1%»
   проваливался мимо ветки памяти в общую «Ошибка при транскрипции».
2. Трекер игнорировал класс сбоя и всем писал «Отправьте запись ещё раз —
   обычно повторная попытка помогает», хотя при забитой памяти повтор
   гарантированно не помогал: 27 отказов подряд.
3. Битый файл выдавался за отсутствующий ffmpeg.

Канон «что + шаг»: шаг зависит от того, на чьей стороне проблема и лечится ли
она повтором.
"""
import pytest

from src.services import error_presentation as ep

PROD_MEMORY_ERROR = (
    "Ошибка транскрипции: Не удалось проверить файл: Ошибка транскрипции: "
    "Файл не может быть обработан: Высокое использование памяти: 91.1% >= 90.0%"
)


class TestMemoryPressureIsRecognised:
    """Дефект 1: флексии «памяти/памятью» должны ловиться наравне с «память»."""

    @pytest.mark.parametrize(
        "text",
        [
            PROD_MEMORY_ERROR,
            "Высокое использование памяти: 91.1% >= 90.0%",
            "Недостаточно памяти для обработки",
            "Не хватило памяти",
            "Проблема с памятью сервера",
            "High memory usage",
            "Система перегружена",
        ],
    )
    def test_memory_pressure_detected(self, text):
        assert ep.is_memory_pressure(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Файл слишком большой: 500MB > 100MB",
            "Ошибка сети",
            "Неподдерживаемый формат файла",
            "",
        ],
    )
    def test_unrelated_errors_are_not_memory(self, text):
        assert not ep.is_memory_pressure(text)


class TestStepMatchesCause:
    """Дефект 2: «отправьте ещё раз» — только там, где повтор осмыслен."""

    def test_memory_pressure_does_not_promise_retry_helps(self):
        step = ep.processing_failure_step(PROD_MEMORY_ERROR)

        assert "обычно повторная попытка помогает" not in step
        assert "перегруж" in step.lower() or "нагруз" in step.lower()

    def test_memory_pressure_points_at_our_side(self):
        step = ep.processing_failure_step(PROD_MEMORY_ERROR)

        assert "нашей стороне" in step or "не нужно" in step

    def test_oversized_file_asks_to_shrink_not_resend(self):
        step = ep.processing_failure_step("Файл слишком большой: 500MB > 100MB")

        assert "обычно повторная попытка помогает" not in step
        assert "сожм" in step.lower() or "раздел" in step.lower()

    def test_corrupt_file_asks_for_another_file(self):
        step = ep.processing_failure_step(
            "Bad Request: failed to process audio: corrupt or unsupported data"
        )

        assert "обычно повторная попытка помогает" not in step
        assert "запис" in step.lower() or "формат" in step.lower()

    def test_transient_api_error_suggests_waiting(self):
        step = ep.processing_failure_step("Service unavailable, connection reset")

        assert "минут" in step

    def test_insufficient_credits_is_our_problem(self):
        step = ep.processing_failure_step("Error code: 402 insufficient credits")

        assert "нашей стороне" in step
        assert "менять не нужно" in step

    def test_unknown_error_keeps_retry_advice(self):
        """Неизвестный сбой — повтор всё ещё разумный первый шаг."""
        step = ep.processing_failure_step("нечто неопознанное")

        assert "ещё раз" in step


class TestTrackerMessage:
    """Сообщение трекера собирается из этапа и шага по причине."""

    def test_message_names_the_stage(self):
        text = ep.processing_failure_message("Транскрипция", PROD_MEMORY_ERROR)

        assert "«Транскрипция»" in text
        assert text.startswith("❌")

    def test_message_carries_cause_specific_step(self):
        text = ep.processing_failure_message("Транскрипция", PROD_MEMORY_ERROR)

        assert "обычно повторная попытка помогает" not in text
        assert ep.processing_failure_step(PROD_MEMORY_ERROR) in text

    def test_stage_name_is_escaped(self):
        """Имя этапа уходит в HTML — угловые скобки экранируются."""
        text = ep.processing_failure_message("<b>Этап</b>", "нечто")

        assert "<b>" not in text
        assert "&lt;b&gt;" in text

    def test_raw_error_never_leaks_to_user(self):
        """Сырой вывод провайдера — только в лог (анти-референс PRODUCT.md)."""
        raw = "OpenRouter payload {'user_id': 42, 'max_tokens': 8000} Error code: 402"
        text = ep.processing_failure_message("Составление", raw)

        assert "user_id" not in text
        assert "max_tokens" not in text
        assert "OpenRouter" not in text


class TestMediaDecodeClassification:
    """Дефект 3: битый файл и отсутствующий ffmpeg — разные вещи."""

    @pytest.mark.parametrize(
        "text",
        [
            "failed to process audio: corrupt or unsupported data",
            "Failed to load audio: Invalid data found when processing input",
            "moov atom not found",
        ],
    )
    def test_broken_media_detected(self, text):
        assert ep.is_unsupported_media(text)

    def test_missing_binary_is_not_broken_media(self):
        assert not ep.is_unsupported_media("ffmpeg не найден в системе")
