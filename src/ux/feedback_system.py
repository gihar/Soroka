"""
Система обратной связи и оценки качества работы бота
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from loguru import logger

from src.database import feedback_repo
from src.handlers.participants_states import FeedbackInput
from src.utils.telegram_safe import safe_edit_text

# Типы, где цифра бесполезна: серьёзность бага и важность идеи пользователь не
# калибрует, а вот описание — единственный качественный сигнал о продукте,
# которого иначе взять неоткуда (критика v11).
_TEXT_FIRST_TYPES = ("bug_report", "suggestion")

_COMMENT_PROMPTS = {
    "bug_report": (
        "<b>Сообщение об ошибке</b>\n\n"
        "Опишите одним сообщением, что произошло и на каком шаге."
    ),
    "suggestion": (
        "<b>Предложение улучшения</b>\n\n"
        "Опишите одним сообщением, что хотелось бы изменить."
    ),
}

_COMMENT_FOLLOWUP = (
    "Спасибо. Если хотите — опишите одним сообщением, что именно "
    "стоит поправить."
)

_COMMENT_SAVED = "Записал, спасибо — передам разработчику."

_COMMENT_SKIPPED = "Оценка записана, спасибо."


def _comment_prompt(feedback_type: str) -> str:
    return _COMMENT_PROMPTS.get(feedback_type, _COMMENT_FOLLOWUP)


@dataclass
class FeedbackEntry:
    """Запись обратной связи"""
    user_id: int
    timestamp: datetime
    rating: int  # 1-5
    feedback_type: str  # "protocol_quality", "processing_speed", "user_experience", "bug_report"
    comment: Optional[str] = None
    protocol_id: Optional[str] = None
    processing_time: Optional[float] = None
    file_format: Optional[str] = None
    file_size: Optional[int] = None


class FeedbackCollector:
    """Сборщик обратной связи"""
    
    def __init__(self):
        self.feedback_storage: List[FeedbackEntry] = []
        self._initialized = False
    
    async def initialize(self):
        """Загрузить данные из БД при инициализации"""
        if self._initialized:
            return
        
        try:
            # Загружаем последние 1000 записей из БД
            feedbacks = await feedback_repo.get_all_feedback(limit=1000)
            for feedback_dict in feedbacks:
                feedback = FeedbackEntry(
                    user_id=feedback_dict['user_id'],
                    timestamp=datetime.fromisoformat(feedback_dict['created_at']),
                    rating=feedback_dict['rating'],
                    feedback_type=feedback_dict['feedback_type'],
                    comment=feedback_dict.get('comment'),
                    protocol_id=feedback_dict.get('protocol_id'),
                    processing_time=feedback_dict.get('processing_time'),
                    file_format=feedback_dict.get('file_format'),
                    file_size=feedback_dict.get('file_size')
                )
                self.feedback_storage.append(feedback)
            
            logger.info(f"Загружено {len(self.feedback_storage)} записей обратной связи из БД")
            self._initialized = True
        except Exception as e:
            logger.error(f"Ошибка загрузки обратной связи из БД: {e}")
    
    def add_feedback(self, feedback: FeedbackEntry):
        """Добавить обратную связь"""
        self.feedback_storage.append(feedback)
        logger.info(f"Получена обратная связь от пользователя {feedback.user_id}: {feedback.rating}/5")
        
        # Сохраняем в БД асинхронно
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._save_feedback_to_db(feedback))
        except Exception as e:
            logger.error(f"Ошибка сохранения обратной связи в БД: {e}")
    
    async def _save_feedback_to_db(self, feedback: FeedbackEntry):
        """Сохранить обратную связь в БД"""
        try:
            await feedback_repo.save_feedback(
                user_id=feedback.user_id,
                rating=feedback.rating,
                feedback_type=feedback.feedback_type,
                comment=feedback.comment,
                protocol_id=feedback.protocol_id,
                processing_time=feedback.processing_time,
                file_format=feedback.file_format,
                file_size=feedback.file_size
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения обратной связи: {e}")
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Получить статистику обратной связи"""
        try:
            # Получаем статистику из БД
            return await feedback_repo.get_feedback_stats()
        except Exception as e:
            logger.error(f"Ошибка получения статистики из БД: {e}")
            # Fallback: считаем из памяти
            if not self.feedback_storage:
                return {"total": 0, "average_rating": 0, "by_type": {}}
            
            total = len(self.feedback_storage)
            average_rating = sum(f.rating for f in self.feedback_storage) / total
            
            by_type = {}
            for feedback in self.feedback_storage:
                feedback_type = feedback.feedback_type
                if feedback_type not in by_type:
                    by_type[feedback_type] = {"count": 0, "average_rating": 0}
                by_type[feedback_type]["count"] += 1
            
            # Пересчитываем средние рейтинги по типам
            for feedback_type in by_type:
                type_feedbacks = [f for f in self.feedback_storage if f.feedback_type == feedback_type]
                by_type[feedback_type]["average_rating"] = sum(f.rating for f in type_feedbacks) / len(type_feedbacks)
            
            return {
                "total": total,
                "average_rating": round(average_rating, 2),
                "by_type": by_type,
                "recent_comments": [
                    {"rating": f.rating, "comment": f.comment, "type": f.feedback_type}
                    for f in sorted(self.feedback_storage, key=lambda x: x.timestamp, reverse=True)[:5]
                    if f.comment
                ]
            }
    
    def export_feedback(self) -> str:
        """Экспортировать обратную связь в JSON"""
        data = []
        for feedback in self.feedback_storage:
            feedback_dict = asdict(feedback)
            feedback_dict["timestamp"] = feedback.timestamp.isoformat()
            data.append(feedback_dict)
        return json.dumps(data, ensure_ascii=False, indent=2)


class FeedbackUI:
    """Пользовательский интерфейс для сбора обратной связи"""

    @staticmethod
    def feedback_intro_text() -> str:
        """Единый текст-приглашение к обратной связи (один слоган во всём боте)."""
        return (
            "<b>Обратная связь</b>\n\n"
            "Помогите сделать бота лучше. Выберите тип обратной связи:"
        )

    @staticmethod
    def create_rating_keyboard(feedback_type: str = "protocol_quality") -> InlineKeyboardMarkup:
        """Создать клавиатуру для оценки"""
        buttons = []
        
        # Рейтинг от 1 до 5
        rating_row = []
        for i in range(1, 6):
            rating_row.append(
                InlineKeyboardButton(
                    text=str(i),
                    callback_data=f"feedback_rating_{feedback_type}_{i}"
                )
            )
        buttons.append(rating_row)

        # Кнопка пропуска
        buttons.append([
            InlineKeyboardButton(
                text="⏭ Пропустить оценку",
                callback_data=f"feedback_skip_{feedback_type}"
            )
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def create_feedback_type_keyboard() -> InlineKeyboardMarkup:
        """Создать клавиатуру выбора типа обратной связи"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="Качество протокола",
                    callback_data="feedback_type_protocol_quality"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Скорость обработки",
                    callback_data="feedback_type_processing_speed"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Удобство использования",
                    callback_data="feedback_type_user_experience"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сообщить об ошибке",
                    callback_data="feedback_type_bug_report"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Предложение улучшения",
                    callback_data="feedback_type_suggestion"
                )
            ]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    @staticmethod
    def create_comment_keyboard() -> InlineKeyboardMarkup:
        """Выход из свободного ввода: писать текст — дело добровольное."""
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="⏭ Пропустить", callback_data="feedback_comment_skip"
            )
        ]])

    def format_feedback_request(feedback_type: str) -> str:
        """Сформировать запрос обратной связи"""
        type_messages = {
            "protocol_quality": (
                "<b>Оценка качества протокола</b>\n\n"
                "Насколько вы довольны качеством созданного протокола?\n"
                "Учитывайте структуру, полноту информации и точность транскрипции."
            ),
            "processing_speed": (
                "<b>Оценка скорости обработки</b>\n\n"
                "Как вы оцениваете скорость обработки вашего файла?\n"
                "Было ли время ожидания приемлемым?"
            ),
            "user_experience": (
                "<b>Оценка удобства использования</b>\n\n"
                "Насколько удобно было использовать бота?\n"
                "Понятен ли интерфейс и логика работы?"
            ),
            "bug_report": (
                "<b>Сообщение об ошибке</b>\n\n"
                "Оцените серьезность проблемы и опишите что произошло.\n"
                "Ваш отзыв поможет нам исправить ошибки."
            ),
            "suggestion": (
                "<b>Предложение улучшения</b>\n\n"
                "Есть идеи как сделать бота лучше?\n"
                "Оцените важность вашего предложения."
            )
        }
        
        return type_messages.get(feedback_type, "Оцените работу бота:")


def setup_feedback_handlers(feedback_collector: FeedbackCollector) -> Router:
    """Настройка обработчиков обратной связи"""
    router = Router()
    
    @router.callback_query(F.data.startswith("feedback_rating_"))
    async def handle_rating(callback: CallbackQuery, state: FSMContext):
        """Обработчик оценки"""
        try:
            # Парсим: feedback_rating_protocol_quality_5
            parts = callback.data.split("_")
            if len(parts) < 4:
                raise ValueError(f"Неверный формат callback_data: {callback.data}")
            
            # Получаем рейтинг (последняя часть)
            rating_str = parts[-1]
            rating = int(rating_str)
            
            # Собираем тип обратной связи из средних частей
            feedback_type = "_".join(parts[2:-1])  # protocol_quality
            
            # Цифра — половина сигнала. Вторую половину спрашиваем текстом;
            # запись в сборщик уходит одна, после ответа или пропуска.
            await state.update_data(
                feedback_type=feedback_type, feedback_rating=rating
            )
            await state.set_state(FeedbackInput.waiting_for_comment)

            await safe_edit_text(
                callback.message,
                _COMMENT_FOLLOWUP,
                reply_markup=FeedbackUI.create_comment_keyboard(),
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка обработки рейтинга: {e}")
            await callback.answer("Не удалось сохранить оценку, попробуйте ещё раз")
    
    @router.callback_query(F.data.startswith("feedback_skip_"))
    async def handle_skip_feedback(callback: CallbackQuery):
        """Обработчик пропуска оценки"""
        await safe_edit_text(
            callback.message,
            "<b>Оценка пропущена</b>\n\n"
            "Вы всегда можете оставить обратную связь командой /feedback",
            parse_mode="HTML",
        )
    
    @router.callback_query(F.data.startswith("feedback_type_"))
    async def handle_feedback_type(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора типа обратной связи"""
        try:
            # Парсим: feedback_type_protocol_quality или feedback_type_bug_report
            parts = callback.data.split("_")
            if len(parts) < 3:
                raise ValueError(f"Неверный формат callback_data: {callback.data}")
            
            # Собираем тип из всех частей после "feedback_type_"
            feedback_type = "_".join(parts[2:])
            
            if feedback_type in _TEXT_FIRST_TYPES:
                await state.update_data(
                    feedback_type=feedback_type, feedback_rating=None
                )
                await state.set_state(FeedbackInput.waiting_for_comment)
                await safe_edit_text(
                    callback.message,
                    _comment_prompt(feedback_type),
                    reply_markup=FeedbackUI.create_comment_keyboard(),
                    parse_mode="HTML"
                )
                return

            message_text = FeedbackUI.format_feedback_request(feedback_type)
            keyboard = FeedbackUI.create_rating_keyboard(feedback_type)

            await safe_edit_text(
                callback.message,
                message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка выбора типа обратной связи: {e}")
            await callback.answer("Не удалось открыть форму, попробуйте ещё раз")
    
    def _entry(user_id: int, data: dict, comment=None) -> FeedbackEntry:
        return FeedbackEntry(
            user_id=user_id,
            timestamp=datetime.now(),
            rating=data.get("feedback_rating"),
            feedback_type=data.get("feedback_type") or "user_experience",
            comment=comment,
        )

    @router.message(StateFilter(FeedbackInput.waiting_for_comment), F.text)
    async def receive_feedback_comment(message: Message, state: FSMContext):
        """Одно сообщение свободным текстом — то, ради чего /feedback и нужен."""
        try:
            data = await state.get_data()
            await state.set_state(None)
            feedback_collector.add_feedback(
                _entry(message.from_user.id, data, comment=message.text)
            )
            await message.answer(_COMMENT_SAVED)
        except Exception as e:
            logger.error(f"Не удалось сохранить отзыв: {e}")
            await message.answer(
                "❌ Не удалось сохранить отзыв.\n"
                "Попробуйте ещё раз командой /feedback."
            )

    @router.callback_query(F.data == "feedback_comment_skip")
    async def skip_feedback_comment(callback: CallbackQuery, state: FSMContext):
        """Писать текст добровольно: оценка сохраняется и без него."""
        try:
            data = await state.get_data()
            await state.set_state(None)
            feedback_collector.add_feedback(_entry(callback.from_user.id, data))
            await safe_edit_text(callback.message, _COMMENT_SKIPPED)
        except Exception as e:
            logger.error(f"Не удалось сохранить оценку: {e}")
            await callback.answer("Не удалось сохранить, попробуйте ещё раз")

    return router


# Глобальный экземпляр сборщика обратной связи
feedback_collector = FeedbackCollector()
