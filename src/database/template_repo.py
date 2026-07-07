"""Template data access."""
import json
from typing import Any, Dict, List, Optional


class TemplateRepository:
    """Repository for template CRUD and system-template maintenance."""

    def __init__(self, database):
        self._db = database

    async def get_templates(self) -> List[Dict[str, Any]]:
        """Get all templates."""
        async with self._db.connect() as db:
            cursor = await db.execute("SELECT * FROM templates ORDER BY is_default DESC, name")
            rows = await cursor.fetchall()
            return [self._deserialize_template(dict(row)) for row in rows]

    async def get_user_templates(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Get templates available to user (own + system defaults)."""
        async with self._db.connect() as db:
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            if not user_row:
                return []

            user_id = user_row['id']

            cursor = await db.execute("""
                SELECT * FROM templates
                WHERE created_by = ? OR is_default = 1
                ORDER BY is_default DESC, name
            """, (user_id,))

            rows = await cursor.fetchall()
            return [self._deserialize_template(dict(row)) for row in rows]

    async def get_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Get template by ID."""
        async with self._db.connect() as db:
            cursor = await db.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            return self._deserialize_template(dict(row))

    async def create_template(self, name: str, content: str, description: str = None,
                              created_by: int = None, is_default: bool = False,
                              category: str = None, tags: List[str] = None,
                              keywords: List[str] = None) -> int:
        """Create a new template."""
        async with self._db.connect() as db:
            tags_json = json.dumps(tags) if tags else None
            keywords_json = json.dumps(keywords) if keywords else None

            cursor = await db.execute("""
                INSERT INTO templates (name, content, description, created_by, is_default, category, tags, keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, content, description, created_by, is_default, category, tags_json, keywords_json))
            await db.commit()
            return cursor.lastrowid

    async def update_template(self, template_id: int, *, name: str, content: str,
                              description: str = None, is_default: bool = False,
                              category: str = None, tags: List[str] = None,
                              keywords: List[str] = None) -> bool:
        """Update an existing template. Schema (updated_at) is guaranteed by init_db."""
        async with self._db.connect() as db:
            tags_json = json.dumps(tags) if tags else None
            keywords_json = json.dumps(keywords) if keywords else None

            cursor = await db.execute("""
                UPDATE templates
                SET name = ?, description = ?, content = ?, is_default = ?, category = ?,
                    tags = ?, keywords = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (name, description, content, is_default, category, tags_json, keywords_json, template_id))
            await db.commit()
            return cursor.rowcount > 0

    async def delete_template(self, telegram_id: int, template_id: int) -> bool:
        """Delete template if owned by user and not a system default."""
        async with self._db.connect() as db:
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            if not user_row:
                return False
            user_id = user_row["id"]

            cursor = await db.execute(
                "SELECT id, is_default, created_by FROM templates WHERE id = ?",
                (template_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            if row["is_default"]:
                return False
            if row["created_by"] not in (user_id, telegram_id):
                return False

            await db.execute(
                "UPDATE users SET default_template_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE default_template_id = ?",
                (template_id,)
            )

            cursor = await db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def system_template_exists(self, name: str) -> bool:
        """Есть ли системный шаблон (created_by IS NULL) с таким именем."""
        async with self._db.connect() as db:
            cursor = await db.execute(
                "SELECT 1 FROM templates WHERE name = ? AND created_by IS NULL LIMIT 1",
                (name,),
            )
            return await cursor.fetchone() is not None

    async def rename_system_template(self, old_name: str, new_name: str) -> int:
        """Переименовать системные шаблоны old_name -> new_name. Возвращает число строк."""
        async with self._db.connect() as db:
            cursor = await db.execute(
                "UPDATE templates SET name = ? WHERE name = ? AND created_by IS NULL",
                (new_name, old_name),
            )
            await db.commit()
            return cursor.rowcount

    async def delete_system_template_by_name(self, name: str) -> int:
        """Удалить системные шаблоны с именем name. Возвращает число удалённых строк."""
        async with self._db.connect() as db:
            cursor = await db.execute(
                "DELETE FROM templates WHERE name = ? AND created_by IS NULL",
                (name,),
            )
            await db.commit()
            return cursor.rowcount

    @staticmethod
    def _deserialize_template(template: Dict[str, Any]) -> Dict[str, Any]:
        """Deserialize JSON fields in template dict."""
        for field in ('tags', 'keywords'):
            if template.get(field):
                try:
                    template[field] = json.loads(template[field])
                except Exception:
                    template[field] = None
        return template
