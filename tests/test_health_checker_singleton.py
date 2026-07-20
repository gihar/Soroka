"""Регресс на дубль-импорт health_checker.

В проекте на sys.path лежат и корень, и src/, поэтому `reliability.health_check`
и `src.reliability.health_check` — два разных модуля, каждый со своим глобальным
`health_checker`. bot.py мониторит экземпляр по «голому» пути; если middleware
читает другой (`src.`-путь), тот никем не отслеживается, его компоненты навсегда
UNKNOWN, и пользователю показывается ложный «ограниченный режим».
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))  # noqa: E402


def test_middleware_shares_the_monitored_health_checker():
    """Middleware читает тот же health_checker, что мониторит bot.py.

    bot.py: `from reliability import health_checker` → start_monitoring().
    Инвариант: экземпляр, который смотрит middleware.get_overall_status(),
    обязан быть тем же объектом — иначе баннер «ограниченный режим» ложный.
    """
    import src.reliability.middleware as middleware
    from reliability import health_checker as monitored  # ровно как в bot.py

    assert middleware.health_checker is monitored
