"""Database package with repository pattern."""
from .database import Database, db
from .feedback_repo import FeedbackRepository
from .history_repo import HistoryRepository
from .metrics_repo import MetricsRepository
from .queue_repo import QueueRepository
from .template_repo import TemplateRepository
from .user_repo import UserRepository

# Convenience instances
user_repo = UserRepository(db)
template_repo = TemplateRepository(db)
feedback_repo = FeedbackRepository(db)
history_repo = HistoryRepository(db)
metrics_repo = MetricsRepository(db)
queue_repo = QueueRepository(db)

__all__ = [
    "Database", "db",
    "UserRepository", "TemplateRepository", "FeedbackRepository",
    "HistoryRepository", "MetricsRepository", "QueueRepository",
    "user_repo", "template_repo", "feedback_repo",
    "history_repo", "metrics_repo", "queue_repo",
]
