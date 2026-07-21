"""Регресс на дубль-импорт global_rate_limiter.

Как и с health_checker: reliability.rate_limiter и src.reliability.rate_limiter —
два разных модуля, каждый со своим global_rate_limiter. Middleware энфорсит
лимиты на своём экземпляре, а api/monitoring читает статистику с другого —
readout мониторинга расходится с реальным энфорсментом.
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))  # noqa: E402


def test_middleware_and_monitoring_share_rate_limiter():
    """Middleware энфорсит на том же global_rate_limiter, что читает monitoring.

    api/monitoring и reliability/__init__ импортируют по «голому» пути;
    инвариант: middleware.global_rate_limiter — тот же объект, иначе
    статистика лимитов в мониторинге не отражает реальный энфорсмент.
    """
    import src.reliability.middleware as middleware
    from reliability.rate_limiter import global_rate_limiter as canonical

    assert middleware.global_rate_limiter is canonical
