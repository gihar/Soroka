"""Регресс на дубль-импорт global_rate_limiter (после ADR-0004).

Как и с health_checker: канон — единственный корень `src.`, статически его
держит страж импортов (test_import_canon). Этот тест охраняет рантайм-тождество:
middleware энфорсит лимиты на `global_rate_limiter`, а api/monitoring читает по
нему статистику. Разойдись пути на два объекта-модуля — readout мониторинга
разъедется с реальным энфорсментом (баг #82). Направление зафиксировано на
`src.`; ADR-0004 перевернул канон с «голого» пути.
"""


def test_middleware_and_monitoring_share_rate_limiter():
    """Middleware энфорсит на том же global_rate_limiter, что читает monitoring.

    middleware и api/monitoring импортируют по каноничному `src.`-пути;
    инвариант: middleware.global_rate_limiter — тот же объект, что
    src.reliability.rate_limiter.global_rate_limiter, иначе статистика лимитов
    в мониторинге не отражает реальный энфорсмент.
    """
    import src.reliability.middleware as middleware
    from src.reliability.rate_limiter import global_rate_limiter as canonical

    assert middleware.global_rate_limiter is canonical
