"""Единая точка разрешения шага работы с моделью (#112, ADR-0007).

Три вызова модели — сопоставление спикеров, ЭТАП 1 анализа, ЭТАП 2 генерации —
решают один и тот же вопрос: каким клиентом, какой моделью, с каким телом и
какими заголовками идти. Ответ живёт здесь и больше нигде: вызывающий называет
шаг и пресет модели, а получает готовый маршрут.

Сегодня маршрут повторяет исторический расклад один в один: пресет обслуживает
только генерацию, дешёвые шаги идут глобальным клиентом с моделями из настроек.
Пресет как полный адрес провайдера (ADR-0007) приезжает следующими срезами —
менять придётся только этот модуль.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

from src.config import settings


class ModelStep(str, Enum):
    """Шаг работы с моделью — единица маршрутизации.

    Значения совпадают с историческими именами шагов: они уходят в лог, в
    контекст разбора ответа и в метрики кеша токенов.
    """

    SPEAKER_MAPPING = "SpeakerMapping"
    ANALYSIS = "Analysis"
    GENERATION = "Generation"


@dataclass(frozen=True)
class StepRoute:
    """Маршрут шага: всё, что нужно вызову, плюс то, чем шаг обслужен."""

    step: ModelStep
    client: Any
    model: str
    preset_key: Optional[str]
    base_url: Optional[str]
    extra_body: Dict[str, Any]
    extra_headers: Dict[str, str]

    def describe(self) -> str:
        """Строка для лога: какой пресет, модель и адрес обслужили шаг."""
        return (
            f"LLM-шаг {self.step.value}: пресет {self.preset_key or 'глобальный'}, "
            f"модель {self.model}, адрес {self.base_url or 'по умолчанию'}"
        )


# Фабрика клиента по обслуживающему пресету (None — глобальный клиент).
ClientFactory = Callable[[Optional[Dict[str, Any]]], Any]

Preset = Optional[Dict[str, Any]]


def _serving_preset(step: ModelStep, preset: Preset) -> Preset:
    """Пресет, обслуживающий шаг.

    Сегодня пресет обслуживает только генерацию, дешёвые шаги идут глобальным
    клиентом. ADR-0007 отдаёт пресету все три шага — здесь и поменяется.
    """
    return preset if step is ModelStep.GENERATION else None


def _model_for(step: ModelStep, serving: Preset) -> str:
    """Имя модели шага; пустое значение откатывается на основную модель."""
    if step is ModelStep.SPEAKER_MAPPING:
        return settings.speaker_mapping_model or settings.openai_model
    if step is ModelStep.ANALYSIS:
        return settings.analysis_stage_model or settings.openai_model
    return (serving or {}).get("model") or settings.openai_model


def _extra_headers() -> Dict[str, str]:
    """Заголовки запроса — пока атрибуция из глобальных настроек, одна на всех."""
    headers: Dict[str, str] = {}
    if settings.http_referer:
        headers["HTTP-Referer"] = settings.http_referer
    if settings.x_title:
        headers["X-Title"] = settings.x_title
    return headers


def resolve_step(step: ModelStep, preset: Preset, client_for: ClientFactory) -> StepRoute:
    """Разрешить «шаг + пресет» в клиента, модель, тело и заголовки вызова."""
    serving = _serving_preset(step, preset)
    return StepRoute(
        step=step,
        client=client_for(serving),
        model=_model_for(step, serving),
        preset_key=(serving or {}).get("key"),
        base_url=(serving or {}).get("base_url") or settings.openai_base_url,
        extra_body={},  # дополнительных полей тела сегодня не задаёт никто
        extra_headers=_extra_headers(),
    )
