"""
Модуль для работы с базой данных
"""

import aiosqlite
from typing import List, Dict, Optional, Any
from loguru import logger
from config import settings


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
    
    async def init_db(self):
        """Инициализация базы данных"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    preferred_llm TEXT DEFAULT 'openai',
                    default_template_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (default_template_id) REFERENCES templates (id)
                )
            """)
            
            # Таблица шаблонов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    content TEXT NOT NULL,
                    is_default BOOLEAN DEFAULT 0,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users (id)
                )
            """)
            
            # Таблица истории обработки
            await db.execute("""
                CREATE TABLE IF NOT EXISTS processing_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    file_name TEXT,
                    template_id INTEGER,
                    llm_provider TEXT,
                    transcription_text TEXT,
                    result_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (template_id) REFERENCES templates (id)
                )
            """)
            
            # Миграция: добавляем поле default_template_id если его нет
            try:
                await db.execute("ALTER TABLE users ADD COLUMN default_template_id INTEGER")
                logger.info("Добавлено поле default_template_id в таблицу users")
            except Exception:
                # Поле уже существует, пропускаем
                pass
            
            await db.commit()
            logger.info("База данных инициализирована")
    
    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Получить пользователя по Telegram ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?", 
                (telegram_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def create_user(self, telegram_id: int, username: str = None, 
                         first_name: str = None, last_name: str = None) -> int:
        """Создать нового пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, username, first_name, last_name))
            await db.commit()
            return cursor.lastrowid
    
    async def update_user_llm_preference(self, telegram_id: int, llm_provider: Optional[str]):
        """Обновить предпочтения LLM пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET preferred_llm = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (llm_provider, telegram_id)
            )
            await db.commit()
    
    async def get_templates(self) -> List[Dict[str, Any]]:
        """Получить все шаблоны"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM templates ORDER BY is_default DESC, name")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_user_templates(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Получить шаблоны пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Получаем ID пользователя
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            
            if not user_row:
                return []
            
            user_id = user_row['id']
            
            # Получаем шаблоны пользователя (созданные им + стандартные)
            cursor = await db.execute("""
                SELECT * FROM templates 
                WHERE created_by = ? OR is_default = 1
                ORDER BY is_default DESC, name
            """, (user_id,))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Получить шаблон по ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def create_template(self, name: str, content: str, description: str = None, 
                            created_by: int = None, is_default: bool = False) -> int:
        """Создать новый шаблон"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO templates (name, content, description, created_by, is_default)
                VALUES (?, ?, ?, ?, ?)
            """, (name, content, description, created_by, is_default))
            await db.commit()
            return cursor.lastrowid
    
    async def save_processing_result(self, user_id: int, file_name: str, template_id: int,
                                   llm_provider: str, transcription_text: str, result_text: str):
        """Сохранить результат обработки"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO processing_history 
                (user_id, file_name, template_id, llm_provider, transcription_text, result_text)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, file_name, template_id, llm_provider, transcription_text, result_text))
            await db.commit()
    
    async def get_user_stats(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Получить статистику пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Получаем ID пользователя
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            
            if not user_row:
                return None
            
            user_id = user_row['id']
            
            # Статистика по файлам
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total_files,
                    COUNT(DISTINCT DATE(created_at)) as active_days,
                    MIN(created_at) as first_file_date,
                    MAX(created_at) as last_file_date
                FROM processing_history 
                WHERE user_id = ?
            """, (user_id,))
            
            stats_row = await cursor.fetchone()
            
            # Статистика по LLM провайдерам
            cursor = await db.execute("""
                SELECT llm_provider, COUNT(*) as count
                FROM processing_history 
                WHERE user_id = ? AND llm_provider IS NOT NULL
                GROUP BY llm_provider
                ORDER BY count DESC
            """, (user_id,))
            
            llm_stats = await cursor.fetchall()
            
            # Статистика по шаблонам
            cursor = await db.execute("""
                SELECT t.name, COUNT(*) as count
                FROM processing_history ph
                JOIN templates t ON ph.template_id = t.id
                WHERE ph.user_id = ?
                GROUP BY t.name
                ORDER BY count DESC
                LIMIT 5
            """, (user_id,))
            
            template_stats = await cursor.fetchall()
            
            # Активность по дням (последние 30 дней)
            cursor = await db.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as count
                FROM processing_history 
                WHERE user_id = ? AND created_at >= DATE('now', '-30 days')
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                LIMIT 30
            """, (user_id,))
            
            daily_activity = await cursor.fetchall()
            
            return {
                "total_files": stats_row['total_files'] if stats_row else 0,
                "active_days": stats_row['active_days'] if stats_row else 0,
                "first_file_date": stats_row['first_file_date'] if stats_row else None,
                "last_file_date": stats_row['last_file_date'] if stats_row else None,
                "llm_providers": [dict(row) for row in llm_stats],
                "favorite_templates": [dict(row) for row in template_stats],
                "daily_activity": [dict(row) for row in daily_activity]
            }
    
    async def set_user_default_template(self, telegram_id: int, template_id: int) -> bool:
        """Установить шаблон по умолчанию для пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Получаем ID пользователя
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            
            if not user_row:
                return False
            
            user_id = user_row['id']
            
            # Проверяем, что шаблон существует и доступен пользователю
            cursor = await db.execute("""
                SELECT id FROM templates 
                WHERE id = ? AND (created_by = ? OR is_default = 1)
            """, (template_id, user_id))
            
            if not await cursor.fetchone():
                return False
            
            # Обновляем предпочтения пользователя
            await db.execute("""
                UPDATE users SET default_template_id = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE telegram_id = ?
            """, (template_id, telegram_id))
            
            await db.commit()
            return True


# Глобальный экземпляр базы данных
db = Database()
