"""Живой зонд строгих схем против реального провайдера (issue #116, ADR-0007).

Назначение — единственный риск, который принципиально не ловится моками:
поддержка строгих схем оказалась свойством конкретной модели, а не провайдера,
и отказ бывает бесшумным. Модель отвечает успехом и валидным JSON, но со своими
ключами вместо затребованных — по коду ответа это неотличимо от успеха.

Запуск вручную при смене модели (в обычном прогоне пропускается — ключа в
окружении нет):

    LIVE_LLM_API_KEY='sk-…' \\
    LIVE_LLM_BASE_URL='https://token-plan.<region>.maas.aliyuncs.com/compatible-mode/v1' \\
    LIVE_LLM_MODEL='qwen3.7-plus' \\
    LIVE_LLM_EXTRA_BODY='{"enable_thinking": false}' \\
        venv/bin/python -m pytest -m live_schema_probe tests/test_schema_probe_live.py

Пресет задаётся только переменными окружения: ключ провайдера в репозитории
не хранится. ``LIVE_LLM_EXTRA_BODY`` — необязательные поля тела запроса
(у Qwen без ``enable_thinking: false`` ответ не укладывается в таймаут).
"""

import json
import os

import pytest

API_KEY = os.environ.get("LIVE_LLM_API_KEY")
BASE_URL = os.environ.get("LIVE_LLM_BASE_URL")
MODEL = os.environ.get("LIVE_LLM_MODEL")
EXTRA_BODY = os.environ.get("LIVE_LLM_EXTRA_BODY")

pytestmark = [
    pytest.mark.live_schema_probe,
    pytest.mark.skipif(
        not API_KEY,
        reason=(
            "Живой зонд пропущен: задайте LIVE_LLM_API_KEY, LIVE_LLM_BASE_URL, "
            "LIVE_LLM_MODEL и запустите "
            "pytest -m live_schema_probe tests/test_schema_probe_live.py"
        ),
    ),
]


def _live_preset() -> dict:
    """Пресет из окружения — полный адрес провайдера (ADR-0007).

    Ключ задан (иначе тест пропущен), но остальное могло остаться незаданным:
    молча уйти на другой адрес хуже, чем сказать, чего не хватает.
    """
    missing = [
        name for name, value in (
            ("LIVE_LLM_BASE_URL", BASE_URL),
            ("LIVE_LLM_MODEL", MODEL),
        ) if not value
    ]
    if missing:
        pytest.fail(f"Живому зонду не хватает переменных окружения: {', '.join(missing)}")

    extra_body = {}
    if EXTRA_BODY:
        try:
            extra_body = json.loads(EXTRA_BODY)
        except json.JSONDecodeError as e:
            pytest.fail(f"LIVE_LLM_EXTRA_BODY не разбирается как JSON: {e}")
        if not isinstance(extra_body, dict):
            pytest.fail("LIVE_LLM_EXTRA_BODY должен быть JSON-объектом")

    return {
        "key": "live_probe",
        "name": f"Живой зонд: {MODEL}",
        "model": MODEL,
        "base_url": BASE_URL,
        "api_key": API_KEY,
        "extra_body": extra_body,
    }


async def test_live_model_honors_the_strict_schema():
    """Отдавать пользователям можно только модель, применяющую строгую схему."""
    from src.llm import protocol_generator

    verdict = await protocol_generator.probe_schema_support(preset=_live_preset())

    assert verdict.model == MODEL
    assert verdict.base_url == BASE_URL
    assert verdict.schema_honored, (
        f"Модель {verdict.model} по адресу {verdict.base_url} приняла схему и выбросила: "
        f"затребованы ключи {sorted(verdict.requested_keys)}, "
        f"вернулись {sorted(verdict.returned_keys)}. "
        "Такой отказ бесшумен — протокол потеряет разделы молча."
    )
