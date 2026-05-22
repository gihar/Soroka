"""Callback handlers aggregated from domain-specific modules."""

from aiogram import Router

from .processing_callbacks import setup_processing_callbacks
from .settings_callbacks import setup_settings_callbacks
from .speaker_mapping_callbacks import setup_speaker_mapping_callbacks
from .template_callbacks import setup_template_callbacks
from .template_mgmt_callbacks import setup_template_mgmt_callbacks


def setup_callback_handlers(user_service, template_service, llm_service, processing_service) -> Router:
    """Aggregate all callback routers into one."""
    router = Router()
    router.include_router(setup_template_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_template_mgmt_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_settings_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_processing_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_speaker_mapping_callbacks(user_service, template_service, llm_service, processing_service))
    return router
