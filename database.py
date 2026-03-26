"""Backward-compatible re-export. Real module lives in src/database/."""
from src.database import Database, db

__all__ = ["Database", "db"]
