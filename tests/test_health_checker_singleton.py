"""Регресс на дубль-импорт health_checker (после ADR-0004).

Канон — единственный корень `src.`; страж импортов (test_import_canon) держит
его статически. Этот тест охраняет рантайм-тождество: bot.py мониторит
экземпляр `health_checker`, а middleware читает его статус. Если пути разойдутся
(второй объект-модуль), middleware смотрит немониторимый экземпляр — его
компоненты навсегда UNKNOWN, и пользователю показывается ложный «ограниченный
режим» (баг #81). Направление зафиксировано на `src.` — раньше канон был
«голый» путь, ADR-0004 его перевернул.
"""


def test_middleware_shares_the_monitored_health_checker():
    """Middleware читает тот же health_checker, что мониторит bot.py.

    bot.py: `from src.reliability import health_checker` → start_monitoring().
    Инвариант: экземпляр, который смотрит middleware.get_overall_status(),
    обязан быть тем же объектом — иначе баннер «ограниченный режим» ложный.
    """
    import src.reliability.middleware as middleware
    from src.reliability import health_checker as monitored  # ровно как в bot.py

    assert middleware.health_checker is monitored
