"""
Модуль для работы с базой данных
"""

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import aiosqlite
from loguru import logger


class Database:
    """Класс для работы с базой данных"""

    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path

    @asynccontextmanager
    async def connect(self):
        """Единственное место политики соединения: row_factory, будущие PRAGMA."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn

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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            # Миграция: добавляем поле saved_participants если его нет
            try:
                await db.execute("ALTER TABLE users ADD COLUMN saved_participants TEXT")
                logger.info("Добавлено поле saved_participants в таблицу users")
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
            
            try:
                await db.execute("ALTER TABLE templates ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                logger.info("Добавлено поле updated_at в таблицу templates")
            except Exception:
                pass
            
            # Миграция: синхронизируем владельцев шаблонов (legacy created_by = telegram_id)
            await self._sync_template_owner_ids(db)
            
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
            
            # Таблица пресетов моделей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS model_presets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    api_key TEXT,
                    admin_only BOOLEAN DEFAULT 0,
                    is_enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Таблица глобальных настроек приложения (key-value)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by INTEGER
                )
            """)

            # Seed active_model_key from first enabled preset (idempotent).
            # INSERT OR IGNORE makes concurrent startups safe.
            cursor = await db.execute(
                "SELECT key FROM model_presets WHERE is_enabled = 1 "
                "ORDER BY created_at, id LIMIT 1"
            )
            preset_row = await cursor.fetchone()
            if preset_row is not None:
                cursor = await db.execute(
                    "INSERT OR IGNORE INTO app_settings (key, value, updated_by) "
                    "VALUES ('active_model_key', ?, NULL)",
                    (preset_row[0],),
                )
                if cursor.rowcount > 0:
                    logger.info(
                        f"Seeded active_model_key = '{preset_row[0]}' "
                        "from first enabled preset"
                    )

            # Миграция: консолидация шаблонов (27 -> 7)
            await self._consolidate_templates(db)

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
    
    async def update_user_protocol_output_preference(self, telegram_id: int, mode: Optional[str]):
        """Обновить режим вывода протокола пользователя ('messages' или 'file')"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET protocol_output_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (mode, telegram_id)
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

    async def system_template_exists(self, name: str) -> bool:
        """Есть ли системный шаблон (created_by IS NULL) с таким именем."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM templates WHERE name = ? AND created_by IS NULL LIMIT 1",
                (name,),
            )
            return await cursor.fetchone() is not None

    async def rename_system_template(self, old_name: str, new_name: str) -> int:
        """Переименовать системные шаблоны old_name -> new_name. Возвращает число строк."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE templates SET name = ? WHERE name = ? AND created_by IS NULL",
                (new_name, old_name),
            )
            await db.commit()
            return cursor.rowcount

    async def delete_system_template_by_name(self, name: str) -> int:
        """Удалить системные шаблоны с именем name. Возвращает число удалённых строк."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM templates WHERE name = ? AND created_by IS NULL",
                (name,),
            )
            await db.commit()
            return cursor.rowcount

    async def ensure_templates_updated_at_column(self) -> None:
        """Проверить наличие столбца updated_at и добавить его при необходимости"""
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_templates_updated_at_column(db)

    async def _sync_template_owner_ids(self, db) -> None:
        """Преобразовать старые значения created_by (telegram_id) в актуальные user_id"""
        try:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, created_by 
                FROM templates 
                WHERE created_by IS NOT NULL
            """)
            templates = await cursor.fetchall()
            if not templates:
                return
            
            updated = 0
            for template in templates:
                creator_id = template["created_by"]
                template_id = template["id"]
                
                if creator_id is None:
                    continue
                
                # Если created_by уже указывает на существующего пользователя, ничего не делаем
                cursor = await db.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1", (creator_id,))
                if await cursor.fetchone():
                    continue
                
                # Legacy: created_by хранит telegram_id
                cursor = await db.execute(
                    "SELECT id FROM users WHERE telegram_id = ? LIMIT 1",
                    (creator_id,)
                )
                user_row = await cursor.fetchone()
                if not user_row:
                    continue
                
                await db.execute(
                    "UPDATE templates SET created_by = ? WHERE id = ?",
                    (user_row["id"], template_id)
                )
                updated += 1
            
            if updated:
                logger.info(f"Синхронизированы владельцы у {updated} шаблонов")
        except Exception as e:
            logger.warning(f"Не удалось синхронизировать владельцев шаблонов: {e}")

    async def _consolidate_templates(self, db):
        """One-time migration: reduce templates from 27 to 7, remove categories."""
        # Check if migration already ran
        cursor = await db.execute(
            "SELECT COUNT(*) FROM templates WHERE category IS NOT NULL AND category != ''"
        )
        row = await cursor.fetchone()
        if row[0] == 0:
            return  # Already migrated

        logger.info("Running template consolidation migration (27 -> 7)...")

        # Merge OD template duplicates: redirect history from 31 to 22
        await db.execute("UPDATE processing_history SET template_id = 22 WHERE template_id = 31")

        # Reset user defaults pointing to templates being deleted
        deleted_ids = (7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 19, 20, 21, 24, 25, 26, 27, 28, 29, 31)
        placeholders = ",".join("?" * len(deleted_ids))
        await db.execute(
            f"UPDATE users SET default_template_id = NULL WHERE default_template_id IN ({placeholders})",
            deleted_ids
        )

        # Delete templates
        await db.execute(f"DELETE FROM templates WHERE id IN ({placeholders})", deleted_ids)

        # Clear category on remaining templates
        await db.execute("UPDATE templates SET category = NULL")

        await db.commit()
        logger.info("Template consolidation migration complete")

    async def _ensure_templates_updated_at_column(self, db) -> None:
        cursor = await db.execute("PRAGMA table_info(templates)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "updated_at" in columns:
            return
        try:
            await db.execute("ALTER TABLE templates ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            await db.commit()
            logger.info("Добавлено поле updated_at в таблицу templates (ensure)")
        except Exception as e:
            logger.warning(f"Не удалось добавить поле updated_at в таблицу templates: {e}")

    async def update_template(self, template_id: int, *, name: str, content: str,
                              description: str = None, is_default: bool = False,
                              category: str = None, tags: List[str] = None,
                              keywords: List[str] = None) -> bool:
        """Полностью обновить существующий шаблон"""
        import json
        await self.ensure_templates_updated_at_column()
        async with aiosqlite.connect(self.db_path) as db:
            tags_json = json.dumps(tags) if tags else None
            keywords_json = json.dumps(keywords) if keywords else None
            
            sql_with_updated_at = """
                UPDATE templates
                SET name = ?, description = ?, content = ?, is_default = ?, category = ?, 
                    tags = ?, keywords = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """
            params = (name, description, content, is_default, category, tags_json, keywords_json, template_id)
            try:
                cursor = await db.execute(sql_with_updated_at, params)
            except aiosqlite.OperationalError as exc:
                if "updated_at" not in str(exc).lower():
                    raise
                logger.warning("Колонка updated_at недоступна, обновляем шаблон без нее: %s", exc)
                cursor = await db.execute("""
                    UPDATE templates
                    SET name = ?, description = ?, content = ?, is_default = ?, category = ?, 
                        tags = ?, keywords = ?
                    WHERE id = ?
                """, (name, description, content, is_default, category, tags_json, keywords_json, template_id))
            await db.commit()
            return cursor.rowcount > 0

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
                template_cursor = await db.execute("""
                    SELECT id, created_by, is_default
                    FROM templates 
                    WHERE id = ?
                """, (template_id,))
                template_row = await template_cursor.fetchone()
                
                if not template_row:
                    return False
                
                template_owner = template_row["created_by"]
                is_system_template = bool(template_row["is_default"])
                
                # Проверяем права доступа к шаблону
                owner_matches_user = template_owner == user_id
                owner_matches_telegram = template_owner == telegram_id
                owner_unknown = template_owner is None
                
                if not (is_system_template or owner_matches_user or owner_unknown or owner_matches_telegram):
                    return False
                
                # Если шаблон создан пользователем в старых версиях (created_by = telegram_id),
                # синхронизируем created_by с актуальным user_id владельца
                if owner_matches_telegram:
                    await db.execute(
                        "UPDATE templates SET created_by = ? WHERE id = ?",
                        (user_id, template_id)
                    )
            
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


# Глобальный экземпляр базы данных
db = Database()
