"""
API endpoints для мониторинга
"""

import json
from typing import Dict, Any, Optional
from loguru import logger
from reliability.health_check import health_checker
from reliability.middleware import monitoring_middleware
from reliability.rate_limiter import global_rate_limiter


class MonitoringAPI:
    """API для мониторинга состояния бота"""
    
    def __init__(self, bot_instance=None):
        self.bot_instance = bot_instance
    
    def get_health_status(self) -> Dict[str, Any]:
        """Получить статус здоровья системы"""
        try:
            return health_checker.get_health_summary()
        except Exception as e:
            logger.error(f"Ошибка при получении статуса здоровья: {e}")
            return {"error": str(e), "status": "error"}
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Получить метрики производительности"""
        try:
            return monitoring_middleware.get_stats()
        except Exception as e:
            logger.error(f"Ошибка при получении метрик: {e}")
            return {"error": str(e)}
    
    def get_rate_limit_stats(self) -> Dict[str, Any]:
        """Получить статистику rate limiting"""
        try:
            return global_rate_limiter.get_all_stats()
        except Exception as e:
            logger.error(f"Ошибка при получении статистики rate limiting: {e}")
            return {"error": str(e)}
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Получить полную системную статистику"""
        return {
            "health": self.get_health_status(),
            "performance": self.get_performance_metrics(),
            "rate_limits": self.get_rate_limit_stats(),
            "bot_specific": self._get_bot_specific_stats()
        }
    
    def _get_bot_specific_stats(self) -> Dict[str, Any]:
        """Получить статистику конкретного бота"""
        if self.bot_instance and hasattr(self.bot_instance, 'get_reliability_stats'):
            try:
                return self.bot_instance.get_reliability_stats()
            except Exception as e:
                logger.error(f"Ошибка при получении статистики бота: {e}")
                return {"error": str(e)}
        
        return {"message": "Bot instance not available"}
    
    def format_status_report(self) -> str:
        """Форматировать отчет о состоянии для пользователя"""
        try:
            stats = self.get_system_stats()
            
            # Форматируем в текстовый отчет
            report_lines = [
                "📊 **Отчет о состоянии системы**",
                ""
            ]
            
            # Общее здоровье
            health = stats.get("health", {})
            overall_status = health.get("overall_status", "unknown")
            status_emoji = {
                "healthy": "✅",
                "degraded": "⚠️",
                "unhealthy": "❌", 
                "unknown": "❓"
            }.get(overall_status, "❓")
            
            report_lines.extend([
                f"**Общий статус:** {status_emoji} {overall_status.upper()}",
                ""
            ])
            
            # Производительность
            perf = stats.get("performance", {})
            if perf and "error" not in perf:
                report_lines.extend([
                    "**📈 Производительность:**",
                    f"• Всего запросов: {perf.get('total_requests', 0)}",
                    f"• Ошибок: {perf.get('total_errors', 0)} ({perf.get('error_rate', 0):.1f}%)",
                    f"• Среднее время обработки: {perf.get('average_processing_time', 0):.3f}с",
                    f"• Активных пользователей: {perf.get('active_users', 0)}",
                    ""
                ])
            
            # Компоненты
            components = health.get("components", {})
            if components:
                healthy_count = sum(1 for comp in components.values() if comp.get("status") == "healthy")
                total_count = len(components)
                
                report_lines.extend([
                    f"**🔧 Компоненты:** {healthy_count}/{total_count} здоровы",
                    ""
                ])
                
                # Показываем проблемные компоненты
                problematic = [
                    (name, comp) for name, comp in components.items()
                    if comp.get("status") in ["unhealthy", "degraded"]
                ]
                
                if problematic:
                    report_lines.append("**⚠️ Проблемные компоненты:**")
                    for name, comp in problematic:
                        status = comp.get("status", "unknown")
                        emoji = "❌" if status == "unhealthy" else "⚠️"
                        report_lines.append(f"• {emoji} {name}: {status}")
                    report_lines.append("")
            
            # Rate limiting
            rate_limits = stats.get("rate_limits", {})
            if rate_limits and "error" not in rate_limits:
                total_blocked = sum(
                    limiter.get("blocked_requests", 0) 
                    for limiter in rate_limits.values() 
                    if isinstance(limiter, dict)
                )
                
                if total_blocked > 0:
                    report_lines.extend([
                        f"**🛡️ Rate Limiting:** {total_blocked} запросов заблокировано",
                        ""
                    ])
            
            report_lines.append(f"*Обновлено: {health.get('timestamp', 0):.0f}*")
            
            return "\n".join(report_lines)
            
        except Exception as e:
            logger.error(f"Ошибка при форматировании отчета: {e}")
            return f"❌ Ошибка при формировании отчета: {e}"
    
    def export_stats_json(self) -> str:
        """Экспортировать статистику в JSON"""
        try:
            stats = self.get_system_stats()
            return json.dumps(stats, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка при экспорте JSON: {e}")
            return json.dumps({"error": str(e)})


# Глобальный экземпляр
monitoring_api = MonitoringAPI()
