"""Неоплаченный доступ к модели — третий класс отказа провайдера.

Классов исчерпания было два: кредиты (402, лечит пополнение) и квота подписки
(429/400, лечит следующий период или другой пресет). Прод 08–15.09.2026 показал
третий: Qwen отвечает 403 ``AccessDenied.Unpurchased`` — доступ к модели не
куплен. Это не лимит внутри оплаченного периода: следующий период сам не
наступит, и квотный совет «подождите до следующего периода» здесь — ловушка,
которая и стоила одиннадцати дней простоя.

Отсюда отдельный класс: поведение бота то же, что при квоте (алерт, автовозврат,
«это на нашей стороне» пользователю), но совет администратору другой — продлить
подписку или сменить пресет насовсем, а не ждать.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.services.error_presentation import ACCESS_NOT_PURCHASED_MARKERS

_SRC = Path(__file__).resolve().parent.parent / "src"

RAW_403 = (
    "Error code: 403 - {'error': {'message': 'Access to model denied. Please make "
    "sure you are eligible for using the model.', 'id': 'aa9d76b0-d163-49b3-8709', "
    "'type': 'AccessDenied.Unpurchased', 'code': 'AccessDenied.Unpurchased'}}"
)


def _unpurchased_exc():
    from src.exceptions.processing import LLMAccessNotPurchasedError

    return LLMAccessNotPurchasedError(RAW_403, provider="openai", model="qwen3.8-max")


@pytest.fixture
def sent(monkeypatch):
    """Перехват доставки алертов: тексты без похода в Telegram."""
    import src.utils.telegram_safe as telegram_safe
    from src.config import settings
    from src.services import admin_alerts

    delivered = AsyncMock()
    monkeypatch.setattr(telegram_safe, "safe_send_message", delivered)
    monkeypatch.setattr(admin_alerts, "_get_alert_bot", lambda: object())
    monkeypatch.setattr(settings, "admins", [111])
    return delivered


# ------------------------------------------------------------ классификация


def test_the_wall_is_recognised_at_the_model_client_boundary():
    """Граница клиента модели поднимает типизированную ошибку, а не голый ответ."""
    from src.llm.protocol_generator import is_access_not_purchased_error

    assert is_access_not_purchased_error(RuntimeError(RAW_403))


def test_the_wall_is_recognised_downstream_where_only_text_is_left():
    """Ниже по течению от исключения остаётся один текст — признак тот же."""
    from src.services.error_presentation import is_access_not_purchased

    assert is_access_not_purchased(RAW_403)


def test_the_typed_error_is_recognised_by_its_own_message():
    """Типизированная ошибка опознаётся своим же текстом: путь замкнут."""
    from src.services.error_presentation import is_access_not_purchased

    assert is_access_not_purchased(str(_unpurchased_exc()))


def test_unpurchased_access_is_not_a_quota_wall():
    """Классы не сливаются: у квоты есть следующий период, здесь его нет."""
    from src.services.error_presentation import is_access_not_purchased, is_quota_exhausted

    assert not is_quota_exhausted(RAW_403)
    assert not is_access_not_purchased(
        "Error code: 429 - Free allocated quota exceeded"
    )


def test_unpurchased_access_is_not_out_of_credits():
    """402 лечит пополнение, 403 — нет: кредитная ветка чужая."""
    from src.services.error_presentation import is_access_not_purchased, is_insufficient_credits

    assert not is_insufficient_credits(RAW_403)
    assert not is_access_not_purchased("Error code: 402 - requires more credits")


def test_a_bare_403_without_the_marker_is_not_unpurchased_access():
    """403 честно многозначен: отозванный ключ — пожар другой природы.

    Ловим парой «код + слово», как квоту: голый код без маркера слил бы
    неоплаченный доступ с украденным секретом, а лечатся они по-разному.
    """
    from src.llm.protocol_generator import is_access_not_purchased_error

    assert not is_access_not_purchased_error(
        RuntimeError("Error code: 403 - {'error': {'message': 'Invalid API key'}}")
    )


def test_the_marker_without_the_code_is_not_enough():
    """Слово без кода отказа — не вердикт: так текст письма стал бы диагнозом."""
    from src.llm.protocol_generator import is_access_not_purchased_error

    assert not is_access_not_purchased_error(
        RuntimeError("Error code: 500 - access to model denied")
    )


# ------------------------------------------------------ единственная таблица


@pytest.mark.parametrize("marker", ACCESS_NOT_PURCHASED_MARKERS)
def test_every_marker_is_seen_by_both_paths(marker):
    """Один набор обслуживает оба пути — иначе таблицы разойдутся, как квотные."""
    from src.llm.protocol_generator import is_access_not_purchased_error
    from src.services.error_presentation import is_access_not_purchased

    raw = f"Error code: 403 - {marker}"

    assert is_access_not_purchased_error(RuntimeError(raw))
    assert is_access_not_purchased(raw)


def _marker_tables(path: Path) -> list[str]:
    """Перечисления строк в файле, среди которых есть маркер неоплаченного доступа."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tables = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            continue
        literals = {
            item.value for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        if literals & set(ACCESS_NOT_PURCHASED_MARKERS):
            tables.append(f"L{node.lineno}")
    return tables


def test_the_marker_table_is_written_down_once():
    """Таблица одна на весь src/ — вторая копия и есть будущее расхождение."""
    homes = {
        str(path.relative_to(_SRC.parent)): _marker_tables(path)
        for path in sorted(_SRC.rglob("*.py"))
        if _marker_tables(path)
    }

    assert list(homes) == ["src/services/error_presentation.py"], (
        f"маркеры неоплаченного доступа перечислены не в одном месте: {homes}"
    )


# ------------------------------------------------------------ текст админу


async def test_the_admin_is_not_told_to_wait_for_the_next_period(sent):
    """Ждать нечего: подписки нет. Квотный совет здесь — ловушка на 11 дней."""
    from src.services import admin_alerts

    await admin_alerts.notify_access_not_purchased(_unpurchased_exc())

    body = str(sent.await_args_list[0].args[2])
    assert "следующем периоде" not in body.lower()
    assert "баланс" not in body.lower()
    assert "подписк" in body.lower()
    assert "qwen3.8-max" in body  # админу видно, какой адрес упёрся в стену


async def test_it_has_its_own_throttling_window(sent):
    """Повод свой — квотный инцидент не должен глушить этот, и наоборот."""
    from src.services import admin_alerts

    await admin_alerts.notify_access_not_purchased(_unpurchased_exc())
    await admin_alerts.notify_quota_exhausted(
        RuntimeError("Error code: 429 - out of quota")
    )

    texts = [str(call.args[2]) for call in sent.await_args_list]
    assert any("подписк" in text.lower() and "квот" not in text.lower() for text in texts)
    assert any("квот" in text.lower() for text in texts)


# ------------------------------------------------------- текст пользователю


def test_the_user_is_not_promised_that_a_retry_helps():
    """Повтор на стене не помогает никогда — обещать его значит звать в круг."""
    from src.services.error_presentation import resume_failure_message

    text = resume_failure_message(RAW_403)

    assert "повторная попытка помогает" not in text
    assert "файл менять не нужно" in text


def test_the_tracker_step_matches_the_cause():
    """Шаг в трекере подбирается по причине — у стены он не про файл."""
    from src.services.error_presentation import processing_failure_step

    step = processing_failure_step(RAW_403)

    assert "на нашей стороне" in step
    assert "сожмите" not in step


# ------------------------------------------------------------------- зонд


def test_the_probe_does_not_blame_a_working_key():
    """/check_model слал админа менять исправный секрет: 403 читался как отказ ключа."""
    from src.handlers.admin_model_handlers import _is_key_refused_error

    assert not _is_key_refused_error(RuntimeError(RAW_403))


def test_the_probe_still_reports_a_genuinely_refused_key():
    """Сузив 403, не теряем 401: отозванный ключ по-прежнему назван своим именем."""
    from src.handlers.admin_model_handlers import _is_key_refused_error

    assert _is_key_refused_error(RuntimeError("Error code: 401 - Unauthorized"))


def test_the_probe_names_unpurchased_access_as_such():
    """Зонд — первый инструмент админа: соврав, он уводит разбирательство не туда."""
    from src.ux.admin_views import model_check_failed

    verdict = model_check_failed(
        "Qwen3.8-max подписка", "qwen3.8-max", "https://token-plan/v1",
        RAW_403, key_refused=False, access_not_purchased=True,
    )

    assert "не оплачен" in verdict.lower()
    assert "/add_model" not in verdict  # менять рабочий ключ незачем
