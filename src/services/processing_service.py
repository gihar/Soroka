"""Backward-compatible re-export. Real module lives in src/services/processing/."""
from src.services.processing.processing_service import ProcessingService, ServiceFactory

__all__ = ["ProcessingService", "ServiceFactory"]
