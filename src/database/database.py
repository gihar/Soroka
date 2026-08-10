"""
Модуль для работы с базой данных
"""

from contextlib import asynccontextmanager

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
                    speaker_mapping_enabled INTEGER,
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
                    speaker_mapping TEXT,
                    meeting_type TEXT,
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
                    -- rating необязателен: сообщение об ошибке и предложение
                    -- идут текстом без цифры (критика v11). AVG в SQLite
                    -- игнорирует NULL, поэтому статистика не портится.
                    rating INTEGER,
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
            # Миграция: выключатель карточки сопоставления (NULL — как решил
            # администратор; 0/1 — явный выбор пользователя)
            try:
                await db.execute("ALTER TABLE users ADD COLUMN speaker_mapping_enabled INTEGER")
                logger.info("Добавлено поле speaker_mapping_enabled в таблицу users")
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
            
            # SQLite запрещает ADD COLUMN с неконстантным DEFAULT (CURRENT_TIMESTAMP):
            # колонка добавляется без default, затем backfill существующих строк.
            try:
                await db.execute("ALTER TABLE templates ADD COLUMN updated_at TIMESTAMP")
                await db.execute(
                    "UPDATE templates SET updated_at = CURRENT_TIMESTAMP "
                    "WHERE updated_at IS NULL"
                )
                logger.info("Добавлено поле updated_at в таблицу templates")
            except Exception as exc:
                if "duplicate column" not in str(exc).lower():
                    logger.error(f"Миграция updated_at не применилась: {exc}")
            
            # Миграция: поля перегенерации в processing_history (nullable, без
            # DEFAULT — NULL значит «данных нет», backfill не нужен). По ним
            # перегенерация из истории пропускает ЭТАП 1 анализа. Дубликат
            # колонки на уже мигрированной БД — норма, прочие ошибки логируем.
            for _column in ("speaker_mapping", "meeting_type"):
                try:
                    await db.execute(
                        f"ALTER TABLE processing_history ADD COLUMN {_column} TEXT"
                    )
                    logger.info(f"Добавлено поле {_column} в таблицу processing_history")
                except Exception as exc:
                    if "duplicate column" not in str(exc).lower():
                        logger.error(
                            f"Миграция {_column} в processing_history не применилась: {exc}"
                        )

            # Миграция: rating в feedback становится необязательным.
            # NOT NULL снимается только перестройкой таблицы (SQLite не умеет
            # ALTER COLUMN), поэтому шаг идёт под проверкой схемы и выполняется
            # ровно один раз.
            await self._relax_feedback_rating(db)

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
                    extra_body TEXT,
                    extra_headers TEXT,
                    analysis_model TEXT,
                    mapping_model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Миграция: параметры провайдера и модели дешёвых шагов в пресете
            # (ADR-0007). Параметры хранятся JSON-объектом; NULL значит «не
            # задано» — пересинк из конфигурации такой пресет не затирает, а
            # пустая модель дешёвого шага означает основную модель пресета.
            # Дубликат колонки на уже мигрированной БД — норма, прочие ошибки
            # логируем.
            for _column in ("extra_body", "extra_headers", "analysis_model", "mapping_model"):
                try:
                    await db.execute(
                        f"ALTER TABLE model_presets ADD COLUMN {_column} TEXT"
                    )
                    logger.info(f"Добавлено поле {_column} в таблицу model_presets")
                except Exception as exc:
                    if "duplicate column" not in str(exc).lower():
                        logger.error(
                            f"Миграция {_column} в model_presets не применилась: {exc}"
                        )

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
    
    async def _relax_feedback_rating(self, db) -> None:
        """Снять NOT NULL с feedback.rating, сохранив данные.

        Отзыв текстом без оценки («Сообщить об ошибке», «Предложение улучшения»)
        пишет rating=None, и на старой схеме вставка падала бы (критика v11).
        SQLite не умеет ALTER COLUMN, поэтому таблица перестраивается: копия →
        перенос строк → замена. Шаг идемпотентный: на уже мигрированной схеме он
        не выполняется. AVG в SQLite игнорирует NULL — статистика не портится.
        """
        try:
            cursor = await db.execute("PRAGMA table_info(feedback)")
            columns = await cursor.fetchall()
            rating = next((c for c in columns if c[1] == "rating"), None)
            # c[3] — notnull; 0 значит «уже необязательный».
            if rating is None or not rating[3]:
                return

            await db.execute("""
                CREATE TABLE feedback_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    rating INTEGER,
                    feedback_type TEXT NOT NULL,
                    comment TEXT,
                    protocol_id TEXT,
                    processing_time REAL,
                    file_format TEXT,
                    file_size INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                INSERT INTO feedback_migrated
                    (id, user_id, rating, feedback_type, comment, protocol_id,
                     processing_time, file_format, file_size, created_at)
                SELECT id, user_id, rating, feedback_type, comment, protocol_id,
                       processing_time, file_format, file_size, created_at
                FROM feedback
            """)
            await db.execute("DROP TABLE feedback")
            await db.execute("ALTER TABLE feedback_migrated RENAME TO feedback")
            await db.commit()
            logger.info("Поле rating в таблице feedback стало необязательным")
        except Exception as exc:
            logger.error(f"Миграция rating в feedback не применилась: {exc}")
            try:
                await db.execute("DROP TABLE IF EXISTS feedback_migrated")
                await db.commit()
            except Exception:
                pass

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

# Глобальный экземпляр базы данных
db = Database()
