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
                    preferred_openai_model_key TEXT,
                    default_template_id INTEGER,
                    protocol_output_mode TEXT DEFAULT 'messages',
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
                    category TEXT,
                    tags TEXT,
                    keywords TEXT,
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
            
            # Таблица обратной связи
            await db.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL,
                    feedback_type TEXT NOT NULL,
                    comment TEXT,
                    protocol_id TEXT,
                    processing_time REAL,
                    file_format TEXT,
                    file_size INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица метрик производительности
            await db.execute("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица метрик обработки файлов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS processing_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    download_duration REAL DEFAULT 0.0,
                    validation_duration REAL DEFAULT 0.0,
                    conversion_duration REAL DEFAULT 0.0,
                    transcription_duration REAL DEFAULT 0.0,
                    diarization_duration REAL DEFAULT 0.0,
                    llm_duration REAL DEFAULT 0.0,
                    formatting_duration REAL DEFAULT 0.0,
                    file_size_bytes INTEGER DEFAULT 0,
                    file_format TEXT,
                    audio_duration_seconds REAL DEFAULT 0.0,
                    transcription_length INTEGER DEFAULT 0,
                    speakers_count INTEGER DEFAULT 0,
                    error_occurred BOOLEAN DEFAULT 0,
                    error_stage TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Миграция: добавляем поле default_template_id если его нет
            try:
                await db.execute("ALTER TABLE users ADD COLUMN default_template_id INTEGER")
                logger.info("Добавлено поле default_template_id в таблицу users")
            except Exception:
                # Поле уже существует, пропускаем
                pass
            # Миграция: добавляем поле preferred_openai_model_key если его нет
            try:
                await db.execute("ALTER TABLE users ADD COLUMN preferred_openai_model_key TEXT")
                logger.info("Добавлено поле preferred_openai_model_key в таблицу users")
            except Exception:
                # Поле уже существует, пропускаем
                pass
            # Миграция: добавляем поле protocol_output_mode если его нет
            try:
                await db.execute("ALTER TABLE users ADD COLUMN protocol_output_mode TEXT DEFAULT 'messages'")
                logger.info("Добавлено поле protocol_output_mode в таблицу users (по умолчанию 'messages')")
            except Exception:
                # Поле уже существует, пропускаем
                pass
            
            # Миграция: добавляем поля для категоризации шаблонов
            try:
                await db.execute("ALTER TABLE templates ADD COLUMN category TEXT")
                logger.info("Добавлено поле category в таблицу templates")
            except Exception:
                pass
            
            try:
                await db.execute("ALTER TABLE templates ADD COLUMN tags TEXT")
                logger.info("Добавлено поле tags в таблицу templates")
            except Exception:
                pass
            
            try:
                await db.execute("ALTER TABLE templates ADD COLUMN keywords TEXT")
                logger.info("Добавлено поле keywords в таблицу templates")
            except Exception:
                pass
            
            # Таблица очереди задач
            await db.execute("""
                CREATE TABLE IF NOT EXISTS queue_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    file_id TEXT,
                    file_path TEXT,
                    file_name TEXT NOT NULL,
                    template_id INTEGER NOT NULL,
                    llm_provider TEXT NOT NULL,
                    language TEXT DEFAULT 'ru',
                    is_external_file BOOLEAN DEFAULT 0,
                    status TEXT NOT NULL,
                    priority INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    error_message TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id)
                )
            """)
            
            # Таблица неотправленных сообщений (при Flood control)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    parse_mode TEXT,
                    reply_markup TEXT,
                    file_path TEXT,
                    caption TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    retry_count INTEGER DEFAULT 0,
                    last_retry_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id)
                )
            """)
            
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

    async def update_user_protocol_output_preference(self, telegram_id: int, mode: Optional[str]):
        """Обновить режим вывода протокола пользователя ('messages' или 'file')"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET protocol_output_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (mode, telegram_id)
            )
            await db.commit()

    async def update_user_openai_model_preference(self, telegram_id: int, model_key: Optional[str]):
        """Обновить предпочтения модели OpenAI пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET preferred_openai_model_key = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (model_key, telegram_id)
            )
            await db.commit()
    
    async def get_templates(self) -> List[Dict[str, Any]]:
        """Получить все шаблоны"""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM templates ORDER BY is_default DESC, name")
            rows = await cursor.fetchall()
            templates = []
            for row in rows:
                template = dict(row)
                # Десериализуем JSON поля
                if template.get('tags'):
                    try:
                        template['tags'] = json.loads(template['tags'])
                    except:
                        template['tags'] = None
                if template.get('keywords'):
                    try:
                        template['keywords'] = json.loads(template['keywords'])
                    except:
                        template['keywords'] = None
                templates.append(template)
            return templates
    
    async def get_user_templates(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Получить шаблоны пользователя"""
        import json
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
            templates = []
            for row in rows:
                template = dict(row)
                # Десериализуем JSON поля
                if template.get('tags'):
                    try:
                        template['tags'] = json.loads(template['tags'])
                    except:
                        template['tags'] = None
                if template.get('keywords'):
                    try:
                        template['keywords'] = json.loads(template['keywords'])
                    except:
                        template['keywords'] = None
                templates.append(template)
            return templates
    
    async def get_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Получить шаблон по ID"""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            template = dict(row)
            # Десериализуем JSON поля
            if template.get('tags'):
                try:
                    template['tags'] = json.loads(template['tags'])
                except:
                    template['tags'] = None
            if template.get('keywords'):
                try:
                    template['keywords'] = json.loads(template['keywords'])
                except:
                    template['keywords'] = None
            return template
    
    async def create_template(self, name: str, content: str, description: str = None, 
                            created_by: int = None, is_default: bool = False,
                            category: str = None, tags: List[str] = None, 
                            keywords: List[str] = None) -> int:
        """Создать новый шаблон"""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            # Сериализуем списки в JSON
            tags_json = json.dumps(tags) if tags else None
            keywords_json = json.dumps(keywords) if keywords else None
            
            cursor = await db.execute("""
                INSERT INTO templates (name, content, description, created_by, is_default, category, tags, keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, content, description, created_by, is_default, category, tags_json, keywords_json))
            await db.commit()
            return cursor.lastrowid

    async def delete_template(self, telegram_id: int, template_id: int) -> bool:
        """Удалить шаблон, если он принадлежит пользователю и не является базовым"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Получаем ID пользователя
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            if not user_row:
                return False
            user_id = user_row["id"]

            # Проверяем, что шаблон существует, не базовый и принадлежит пользователю
            cursor = await db.execute(
                "SELECT id, is_default, created_by FROM templates WHERE id = ?",
                (template_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            if row["is_default"]:
                return False
            # Разрешим удаление, если шаблон привязан к текущему пользователю
            # с учетом старых записей, где created_by мог содержать telegram_id
            if row["created_by"] not in (user_id, telegram_id):
                return False

            # Сбрасываем default_template_id у пользователей, где он ссылается на удаляемый шаблон
            await db.execute(
                "UPDATE users SET default_template_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE default_template_id = ?",
                (template_id,)
            )

            # Удаляем шаблон
            cursor = await db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
            await db.commit()
            return cursor.rowcount > 0
    
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
                SELECT t.id, t.name, COUNT(*) as count
                FROM processing_history ph
                JOIN templates t ON ph.template_id = t.id
                WHERE ph.user_id = ?
                GROUP BY t.id, t.name
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
            # template_id = 0 - специальное значение для "Умного выбора", пропускаем проверку
            if template_id != 0:
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

    async def reset_user_default_template(self, telegram_id: int) -> bool:
        """Сбросить шаблон по умолчанию для пользователя (установить NULL)"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                UPDATE users SET default_template_id = NULL, updated_at = CURRENT_TIMESTAMP 
                WHERE telegram_id = ?
            """, (telegram_id,))
            await db.commit()
            return cursor.rowcount > 0
    
    # Методы для работы с обратной связью
    async def save_feedback(self, user_id: int, rating: int, feedback_type: str,
                          comment: Optional[str] = None, protocol_id: Optional[str] = None,
                          processing_time: Optional[float] = None, file_format: Optional[str] = None,
                          file_size: Optional[int] = None):
        """Сохранить обратную связь"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO feedback 
                (user_id, rating, feedback_type, comment, protocol_id, processing_time, file_format, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, rating, feedback_type, comment, protocol_id, processing_time, file_format, file_size))
            await db.commit()
    
    async def get_all_feedback(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Получить всю обратную связь"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM feedback ORDER BY created_at DESC"
            if limit:
                query += f" LIMIT {limit}"
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_feedback_stats(self) -> Dict[str, Any]:
        """Получить статистику обратной связи"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Общая статистика
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total,
                    AVG(rating) as average_rating
                FROM feedback
            """)
            stats = await cursor.fetchone()
            
            # По типам
            cursor = await db.execute("""
                SELECT 
                    feedback_type,
                    COUNT(*) as count,
                    AVG(rating) as average_rating
                FROM feedback
                GROUP BY feedback_type
            """)
            by_type = await cursor.fetchall()
            
            return {
                "total": stats['total'] if stats else 0,
                "average_rating": round(stats['average_rating'], 2) if stats and stats['average_rating'] else 0,
                "by_type": {row['feedback_type']: {"count": row['count'], "average_rating": round(row['average_rating'], 2)} 
                           for row in by_type}
            }
    
    # Методы для работы с метриками производительности
    async def save_performance_metric(self, name: str, value: float, unit: str, 
                                     tags: Optional[Dict[str, str]] = None):
        """Сохранить метрику производительности"""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            tags_json = json.dumps(tags) if tags else None
            await db.execute("""
                INSERT INTO performance_metrics (name, value, unit, tags)
                VALUES (?, ?, ?, ?)
            """, (name, value, unit, tags_json))
            await db.commit()
    
    async def save_processing_metric(self, metric_data: Dict[str, Any]) -> int:
        """Сохранить метрику обработки файла"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO processing_metrics (
                    file_name, user_id, start_time, end_time,
                    download_duration, validation_duration, conversion_duration,
                    transcription_duration, diarization_duration, llm_duration, formatting_duration,
                    file_size_bytes, file_format, audio_duration_seconds,
                    transcription_length, speakers_count,
                    error_occurred, error_stage, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric_data.get('file_name'),
                metric_data.get('user_id'),
                metric_data.get('start_time'),
                metric_data.get('end_time'),
                metric_data.get('download_duration', 0.0),
                metric_data.get('validation_duration', 0.0),
                metric_data.get('conversion_duration', 0.0),
                metric_data.get('transcription_duration', 0.0),
                metric_data.get('diarization_duration', 0.0),
                metric_data.get('llm_duration', 0.0),
                metric_data.get('formatting_duration', 0.0),
                metric_data.get('file_size_bytes', 0),
                metric_data.get('file_format'),
                metric_data.get('audio_duration_seconds', 0.0),
                metric_data.get('transcription_length', 0),
                metric_data.get('speakers_count', 0),
                metric_data.get('error_occurred', False),
                metric_data.get('error_stage'),
                metric_data.get('error_message')
            ))
            await db.commit()
            return cursor.lastrowid
    
    async def get_processing_metrics(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Получить метрики обработки за последние N часов"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM processing_metrics
                WHERE created_at >= DATETIME('now', ?) 
                ORDER BY created_at DESC
            """, (f'-{hours} hours',))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # Методы для работы с очередью задач
    async def save_queue_task(self, task_data: Dict[str, Any]) -> bool:
        """Сохранить задачу в очередь"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO queue_tasks (
                        task_id, user_id, chat_id, message_id,
                        file_id, file_path, file_name, template_id,
                        llm_provider, language, is_external_file,
                        status, priority, created_at, started_at, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_data['task_id'],
                    task_data['user_id'],
                    task_data['chat_id'],
                    task_data.get('message_id'),
                    task_data.get('file_id'),
                    task_data.get('file_path'),
                    task_data['file_name'],
                    task_data['template_id'],
                    task_data['llm_provider'],
                    task_data.get('language', 'ru'),
                    task_data.get('is_external_file', False),
                    task_data['status'],
                    task_data.get('priority', 1),
                    task_data['created_at'],
                    task_data.get('started_at'),
                    task_data.get('error_message')
                ))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении задачи в БД: {e}")
            return False
    
    async def update_queue_task_status(self, task_id: str, status: str, 
                                      started_at: Optional[str] = None,
                                      error_message: Optional[str] = None) -> bool:
        """Обновить статус задачи в очереди"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                if started_at:
                    await db.execute("""
                        UPDATE queue_tasks 
                        SET status = ?, started_at = ?, error_message = ?
                        WHERE task_id = ?
                    """, (status, started_at, error_message, task_id))
                else:
                    await db.execute("""
                        UPDATE queue_tasks 
                        SET status = ?, error_message = ?
                        WHERE task_id = ?
                    """, (status, error_message, task_id))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении статуса задачи: {e}")
            return False
    
    async def update_queue_task_message_id(self, task_id: str, message_id: int) -> bool:
        """Обновить message_id задачи"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE queue_tasks 
                    SET message_id = ?
                    WHERE task_id = ?
                """, (message_id, task_id))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении message_id задачи: {e}")
            return False
    
    async def get_queue_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Получить задачу по ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM queue_tasks WHERE task_id = ?
            """, (task_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    async def get_pending_queue_tasks(self) -> List[Dict[str, Any]]:
        """Получить все задачи в статусе queued, отсортированные по приоритету и времени создания"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM queue_tasks 
                WHERE status = 'queued'
                ORDER BY priority DESC, created_at ASC
            """)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def delete_queue_task(self, task_id: str) -> bool:
        """Удалить задачу из очереди"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    DELETE FROM queue_tasks WHERE task_id = ?
                """, (task_id,))
                await db.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при удалении задачи: {e}")
            return False
    
    async def cleanup_completed_queue_tasks(self, hours: int = 24) -> int:
        """Очистить завершенные задачи старше N часов"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    DELETE FROM queue_tasks 
                    WHERE status IN ('completed', 'cancelled', 'failed')
                    AND created_at < DATETIME('now', ?)
                """, (f'-{hours} hours',))
                await db.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Ошибка при очистке завершенных задач: {e}")
            return 0
    
    async def update_user_saved_participants(self, telegram_id: int, participants_json: str) -> bool:
        """Обновить сохраненный список участников для пользователя"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Сначала проверяем, есть ли колонка saved_participants
                cursor = await db.execute("PRAGMA table_info(users)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                # Если колонки нет - добавляем её
                if 'saved_participants' not in column_names:
                    logger.info("Добавление колонки saved_participants в таблицу users")
                    await db.execute("ALTER TABLE users ADD COLUMN saved_participants TEXT")
                    await db.commit()
                
                # Обновляем список участников
                await db.execute("""
                    UPDATE users 
                    SET saved_participants = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE telegram_id = ?
                """, (participants_json, telegram_id))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении списка участников: {e}")
            return False
    
    async def get_user_saved_participants(self, telegram_id: int) -> Optional[str]:
        """Получить сохраненный список участников пользователя"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Проверяем наличие колонки
                cursor = await db.execute("PRAGMA table_info(users)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if 'saved_participants' not in column_names:
                    return None
                
                cursor = await db.execute("""
                    SELECT saved_participants FROM users WHERE telegram_id = ?
                """, (telegram_id,))
                row = await cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Ошибка при получении списка участников: {e}")
            return None
    
    async def save_pending_message(self, user_id: int, chat_id: int, message_type: str, 
                                 content: str, parse_mode: str = None, reply_markup: str = None,
                                 file_path: str = None, caption: str = None) -> int:
        """Сохранить неотправленное сообщение в БД"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    INSERT INTO pending_messages 
                    (user_id, chat_id, message_type, content, parse_mode, reply_markup, file_path, caption)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, chat_id, message_type, content, parse_mode, reply_markup, file_path, caption))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Ошибка сохранения неотправленного сообщения: {e}")
            return None
    
    async def get_pending_messages(self, user_id: int = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Получить неотправленные сообщения"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                if user_id:
                    cursor = await db.execute("""
                        SELECT * FROM pending_messages 
                        WHERE user_id = ? 
                        ORDER BY created_at ASC 
                        LIMIT ?
                    """, (user_id, limit))
                else:
                    cursor = await db.execute("""
                        SELECT * FROM pending_messages 
                        ORDER BY created_at ASC 
                        LIMIT ?
                    """, (limit,))
                
                rows = await cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения неотправленных сообщений: {e}")
            return []
    
    async def update_pending_message_retry(self, message_id: int, retry_count: int):
        """Обновить счетчик попыток отправки"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE pending_messages 
                    SET retry_count = ?, last_retry_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (retry_count, message_id))
                await db.commit()
        except Exception as e:
            logger.error(f"Ошибка обновления счетчика попыток: {e}")
    
    async def delete_pending_message(self, message_id: int):
        """Удалить неотправленное сообщение после успешной отправки"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM pending_messages WHERE id = ?", (message_id,))
                await db.commit()
        except Exception as e:
            logger.error(f"Ошибка удаления неотправленного сообщения: {e}")


# Глобальный экземпляр базы данных
db = Database()
