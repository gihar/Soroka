"""Признак квотной стены — один набор маркеров на оба пути.

Признак «квота подписки исчерпана» опознаётся дважды: на границе клиента модели
(``src.llm.protocol_generator`` — там к тексту добавляется HTTP-код и рождается
типизированная ошибка) и ниже по течению, где от исключения остался один текст
(``src.services.error_presentation`` — оттуда его берут и пользовательский шаг, и
разбор повода для алерта админам).

Две копии таблицы уже разошлись: «out of quota» и «quota_exhausted» знал только
генератор. Нетипизированный сбой с таким текстом уезжал в кредитную ветку, и
администратор получал «Пополните баланс провайдера» на квотной стене — совет,
который там не работает (CONTEXT.md: «Квота подписки»). Здесь закрепляется, что
таблица одна и обслуживает оба пути.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.services.error_presentation import QUOTA_EXHAUSTION_MARKERS

_SRC = Path(__file__).resolve().parent.parent / "src"


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


@pytest.fixture(autouse=True)
def no_failover(monkeypatch):
    """Автовозврат здесь не проверяется — его база не нужна (см. test_admin_quota_alert)."""
    from src.services import preset_failover

    monkeypatch.setattr(preset_failover, "return_to_fallback", AsyncMock(return_value=None))


def _worker():
    """Воркер очереди без запуска: нужен только его разбор причины сбоя."""
    from src.services.task_queue_manager import TaskQueueManager

    return TaskQueueManager.__new__(TaskQueueManager)


async def test_out_of_quota_reaches_the_admin_as_a_quota_wall(sent):
    """Нетипизированный сбой «out of quota» — квотный алерт, а не кредитный.

    Совет «пополните баланс» на исчерпанной квоте не работает: пополнять
    нечего, лечит только следующий период или другой пресет.
    """
    await _worker()._notify_admins_provider_exhausted(
        RuntimeError("Error code: 429 - The request is out of quota")
    )

    body = str(sent.await_args_list[0].args[2])
    assert "квот" in body.lower()
    assert "баланс" not in body.lower()


@pytest.mark.parametrize("marker", QUOTA_EXHAUSTION_MARKERS)
def test_every_marker_is_seen_by_both_paths(marker):
    """Один набор обслуживает оба пути: классификацию и опознание по тексту.

    Слева — граница клиента модели: маркер плюс квотный HTTP-код рождают
    типизированную ошибку. Справа — то, что читает уже только текст. Маркер,
    известный одному и неизвестный другому, и есть расхождение таблиц.
    """
    from src.llm.protocol_generator import _is_quota_exhausted_error
    from src.services.error_presentation import is_quota_exhausted

    raw = f"Error code: 429 - {marker}"

    assert _is_quota_exhausted_error(RuntimeError(raw))
    assert is_quota_exhausted(raw)


def _marker_tables(path: Path) -> list[str]:
    """Перечисления строк в файле, среди которых есть квотный маркер.

    Ищем именно таблицу признаков — набор литералов, а не отдельное слово:
    ``admin_alerts.REASON_QUOTA_EXHAUSTED`` совпадает с маркером написанием, но
    это ключ окна троттлинга, другая сущность.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tables = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            continue
        literals = {
            item.value for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        if literals & set(QUOTA_EXHAUSTION_MARKERS):
            tables.append(f"L{node.lineno}")
    return tables


def test_the_marker_table_is_written_down_once():
    """Таблица маркеров одна на весь src/ — вторая копия и есть будущее расхождение."""
    homes = {
        str(path.relative_to(_SRC.parent)): _marker_tables(path)
        for path in sorted(_SRC.rglob("*.py"))
        if _marker_tables(path)
    }

    assert list(homes) == ["src/services/error_presentation.py"], (
        f"квотные маркеры перечислены не в одном месте: {homes}"
    )


def test_plain_throttling_is_not_a_quota_wall():
    """Голое 429 — rate limit: лечится повтором, квотной стеной не считается."""
    from src.llm.protocol_generator import _is_quota_exhausted_error

    assert not _is_quota_exhausted_error(RuntimeError("Error code: 429 - rate limited"))
