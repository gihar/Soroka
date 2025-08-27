"""
Health Check система для мониторинга состояния сервисов
"""

import asyncio
import time
from enum import Enum
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field
from loguru import logger


class HealthStatus(Enum):
    """Статус здоровья компонента"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Результат проверки здоровья"""
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    response_time: Optional[float] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ComponentHealth:
    """Здоровье компонента"""
    name: str
    status: HealthStatus
    last_check: float
    last_success: Optional[float]
    consecutive_failures: int
    total_checks: int
    total_failures: int
    average_response_time: float
    details: Dict[str, Any] = field(default_factory=dict)


class HealthCheck:
    """Базовый класс для проверок здоровья"""
    
    def __init__(self, name: str, timeout: float = 10.0):
        self.name = name
        self.timeout = timeout
    
    async def check(self) -> HealthCheckResult:
        """Выполнить проверку здоровья"""
        raise NotImplementedError


class DatabaseHealthCheck(HealthCheck):
    """Проверка здоровья базы данных"""
    
    def __init__(self, name: str = "database", timeout: float = 5.0):
        super().__init__(name, timeout)
    
    async def check(self) -> HealthCheckResult:
        """Проверить подключение к БД"""
        start_time = time.time()
        
        try:
            from database import db
            
            # Простой запрос для проверки соединения
            import aiosqlite
            async with aiosqlite.connect(db.db_path) as connection:
                async with connection.execute("SELECT 1") as cursor:
                    await cursor.fetchone()
            
            response_time = time.time() - start_time
            
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="База данных доступна",
                response_time=response_time,
                details={"database_path": str(db.db_path)}
            )
            
        except Exception as e:
            response_time = time.time() - start_time
            
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Ошибка подключения к БД: {e}",
                response_time=response_time,
                details={"error": str(e)}
            )


class LLMHealthCheck(HealthCheck):
    """Проверка здоровья LLM провайдеров"""
    
    def __init__(self, name: str = "llm_providers", timeout: float = 15.0):
        super().__init__(name, timeout)
    
    async def check(self) -> HealthCheckResult:
        """Проверить доступность LLM провайдеров"""
        start_time = time.time()
        
        try:
            from llm_providers import llm_manager
            
            available_providers = llm_manager.get_available_providers()
            provider_count = len(available_providers)
            
            response_time = time.time() - start_time
            
            if provider_count == 0:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message="Нет доступных LLM провайдеров",
                    response_time=response_time,
                    details={"available_providers": available_providers}
                )
            elif provider_count < 2:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Доступен только {provider_count} LLM провайдер",
                    response_time=response_time,
                    details={"available_providers": available_providers}
                )
            else:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    message=f"Доступно {provider_count} LLM провайдеров",
                    response_time=response_time,
                    details={"available_providers": available_providers}
                )
                
        except Exception as e:
            response_time = time.time() - start_time
            
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Ошибка проверки LLM провайдеров: {e}",
                response_time=response_time,
                details={"error": str(e)}
            )


class DiskSpaceHealthCheck(HealthCheck):
    """Проверка свободного места на диске"""
    
    def __init__(self, name: str = "disk_space", path: str = ".", 
                 warning_threshold: float = 0.8, critical_threshold: float = 0.95,
                 timeout: float = 5.0):
        super().__init__(name, timeout)
        self.path = path
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
    
    async def check(self) -> HealthCheckResult:
        """Проверить свободное место на диске"""
        start_time = time.time()
        
        try:
            # Используем shutil.disk_usage для кроссплатформенной совместимости
            import shutil
            import os
            
            # Преобразуем путь в абсолютный
            abs_path = os.path.abspath(self.path)
            
            # Получаем информацию о диске
            total_space, used_space, free_space = shutil.disk_usage(abs_path)
            usage_ratio = used_space / total_space if total_space > 0 else 0
            
            response_time = time.time() - start_time
            
            details = {
                "path": abs_path,
                "total_space_gb": round(total_space / (1024**3), 2),
                "free_space_gb": round(free_space / (1024**3), 2),
                "used_space_gb": round(used_space / (1024**3), 2),
                "usage_percentage": round(usage_ratio * 100, 1)
            }
            
            if usage_ratio >= self.critical_threshold:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Критически мало места на диске: {details['usage_percentage']}%",
                    response_time=response_time,
                    details=details
                )
            elif usage_ratio >= self.warning_threshold:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Мало места на диске: {details['usage_percentage']}%",
                    response_time=response_time,
                    details=details
                )
            else:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    message=f"Достаточно места на диске: {details['usage_percentage']}% используется",
                    response_time=response_time,
                    details=details
                )
                
        except Exception as e:
            response_time = time.time() - start_time
            
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Ошибка проверки места на диске: {e}",
                response_time=response_time,
                details={"error": str(e)}
            )


class HealthChecker:
    """Основной менеджер проверок здоровья"""
    
    def __init__(self, check_interval: float = 60.0):
        self.check_interval = check_interval
        self.health_checks: Dict[str, HealthCheck] = {}
        self.component_health: Dict[str, ComponentHealth] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def register_check(self, health_check: HealthCheck):
        """Зарегистрировать проверку здоровья"""
        self.health_checks[health_check.name] = health_check
        self.component_health[health_check.name] = ComponentHealth(
            name=health_check.name,
            status=HealthStatus.UNKNOWN,
            last_check=0,
            last_success=None,
            consecutive_failures=0,
            total_checks=0,
            total_failures=0,
            average_response_time=0.0
        )
        logger.info(f"Зарегистрирована проверка здоровья: {health_check.name}")
    
    async def check_component(self, name: str) -> HealthCheckResult:
        """Проверить здоровье конкретного компонента"""
        if name not in self.health_checks:
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                message=f"Неизвестный компонент: {name}"
            )
        
        health_check = self.health_checks[name]
        component = self.component_health[name]
        
        try:
            result = await asyncio.wait_for(
                health_check.check(),
                timeout=health_check.timeout
            )
            
            # Обновляем статистику
            component.total_checks += 1
            component.last_check = time.time()
            
            if result.status == HealthStatus.HEALTHY:
                component.last_success = time.time()
                component.consecutive_failures = 0
            else:
                component.consecutive_failures += 1
                if result.status == HealthStatus.UNHEALTHY:
                    component.total_failures += 1
            
            # Обновляем среднее время ответа
            if result.response_time:
                if component.average_response_time == 0:
                    component.average_response_time = result.response_time
                else:
                    component.average_response_time = (
                        component.average_response_time * 0.8 + result.response_time * 0.2
                    )
            
            component.status = result.status
            component.details = result.details
            
            return result
            
        except asyncio.TimeoutError:
            component.total_checks += 1
            component.total_failures += 1
            component.consecutive_failures += 1
            component.last_check = time.time()
            component.status = HealthStatus.UNHEALTHY
            
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Таймаут проверки {name} ({health_check.timeout}s)",
                response_time=health_check.timeout
            )
        
        except Exception as e:
            component.total_checks += 1
            component.total_failures += 1
            component.consecutive_failures += 1
            component.last_check = time.time()
            component.status = HealthStatus.UNHEALTHY
            
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=f"Ошибка проверки {name}: {e}",
                details={"error": str(e)}
            )
    
    async def check_all(self) -> Dict[str, HealthCheckResult]:
        """Проверить здоровье всех компонентов"""
        results = {}
        
        # Запускаем все проверки параллельно
        tasks = [
            self.check_component(name) 
            for name in self.health_checks.keys()
        ]
        
        if tasks:
            completed_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, name in enumerate(self.health_checks.keys()):
                result = completed_results[i]
                if isinstance(result, Exception):
                    results[name] = HealthCheckResult(
                        status=HealthStatus.UNHEALTHY,
                        message=f"Исключение при проверке: {result}"
                    )
                else:
                    results[name] = result
        
        return results
    
    def get_overall_status(self) -> HealthStatus:
        """Получить общий статус здоровья"""
        if not self.component_health:
            return HealthStatus.UNKNOWN
        
        statuses = [comp.status for comp in self.component_health.values()]
        
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        elif all(status == HealthStatus.HEALTHY for status in statuses):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Получить сводку состояния здоровья"""
        overall_status = self.get_overall_status()
        
        return {
            "overall_status": overall_status.value,
            "components": {
                name: {
                    "status": comp.status.value,
                    "last_check": comp.last_check,
                    "last_success": comp.last_success,
                    "consecutive_failures": comp.consecutive_failures,
                    "total_checks": comp.total_checks,
                    "total_failures": comp.total_failures,
                    "failure_rate": (comp.total_failures / max(1, comp.total_checks)) * 100,
                    "average_response_time": comp.average_response_time,
                    "details": comp.details
                }
                for name, comp in self.component_health.items()
            },
            "timestamp": time.time()
        }
    
    async def start_monitoring(self):
        """Запустить непрерывный мониторинг"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info(f"Запущен мониторинг здоровья (интервал: {self.check_interval}s)")
    
    async def stop_monitoring(self):
        """Остановить мониторинг"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Мониторинг здоровья остановлен")
    
    async def _monitoring_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                results = await self.check_all()
                
                # Логируем критические проблемы
                for name, result in results.items():
                    if result.status == HealthStatus.UNHEALTHY:
                        logger.error(f"Компонент {name} нездоров: {result.message}")
                    elif result.status == HealthStatus.DEGRADED:
                        logger.warning(f"Компонент {name} деградирует: {result.message}")
                
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга здоровья: {e}")
                await asyncio.sleep(5)  # Короткая пауза при ошибке


# Глобальный экземпляр
health_checker = HealthChecker()

# Регистрация стандартных проверок
health_checker.register_check(DatabaseHealthCheck())
health_checker.register_check(LLMHealthCheck())
health_checker.register_check(DiskSpaceHealthCheck())
