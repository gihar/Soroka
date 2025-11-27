"""
Сервис для работы с пользователями
"""

from typing import Optional
from loguru import logger

from src.models.user import User, UserCreate, UserUpdate
from src.exceptions.user import UserNotFoundError, UserCreationError
from database import db


class UserService:
    """Сервис для работы с пользователями"""
    
    def __init__(self):
        self.db = db
    
    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Получить пользователя по Telegram ID"""
        try:
            user_data = await self.db.get_user(telegram_id)
            if user_data:
                return User(**user_data)
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении пользователя {telegram_id}: {e}")
            raise

    async def get_user_default_template_id(self, telegram_id: int) -> Optional[int]:
        """Получить ID шаблона по умолчанию пользователя"""
        try:
            user_data = await self.db.get_user(telegram_id)
            if not user_data:
                logger.debug(f"Пользователь {telegram_id} не найден при запросе default_template_id")
                return None
            
            default_id = user_data.get("default_template_id")
            logger.debug(f"Пользователь {telegram_id} default_template_id={default_id}")
            return default_id
        except Exception as e:
            logger.error(f"Ошибка при получении default_template_id для пользователя {telegram_id}: {e}")
            return None
    
    async def create_user(self, user_data: UserCreate) -> User:
        """Создать нового пользователя"""
        try:
            user_id = await self.db.create_user(
                telegram_id=user_data.telegram_id,
                username=user_data.username,
                first_name=user_data.first_name,
                last_name=user_data.last_name
            )
            
            # Получаем созданного пользователя
            created_user = await self.get_user_by_telegram_id(user_data.telegram_id)
            if not created_user:
                raise UserCreationError(user_data.telegram_id, "Пользователь не найден после создания")
            
            logger.info(f"Создан новый пользователь: {user_data.telegram_id}")
            return created_user
            
        except Exception as e:
            logger.error(f"Ошибка при создании пользователя {user_data.telegram_id}: {e}")
            raise UserCreationError(user_data.telegram_id, str(e))
    
    async def update_user_llm_preference(self, telegram_id: int, llm_provider: Optional[str]) -> User:
        """Обновить предпочтения LLM пользователя"""
        try:
            # Проверяем, что пользователь существует
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                raise UserNotFoundError(telegram_id)
            
            # Обновляем предпочтения
            await self.db.update_user_llm_preference(telegram_id, llm_provider)
            
            # Возвращаем обновленного пользователя
            updated_user = await self.get_user_by_telegram_id(telegram_id)
            if not updated_user:
                raise UserNotFoundError(telegram_id)
            
            logger.info(f"Обновлены предпочтения LLM для пользователя {telegram_id}: {llm_provider}")
            return updated_user
            
        except UserNotFoundError:
            raise

    async def update_user_openai_model_preference(self, telegram_id: int, model_key: Optional[str]) -> User:
        """Обновить предпочтение модели OpenAI пользователя"""
        try:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                raise UserNotFoundError(telegram_id)
            
            await self.db.update_user_openai_model_preference(telegram_id, model_key)
            updated_user = await self.get_user_by_telegram_id(telegram_id)
            if not updated_user:
                raise UserNotFoundError(telegram_id)
            logger.info(f"Обновлена модель OpenAI для пользователя {telegram_id}: {model_key}")
            return updated_user
        except UserNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Ошибка при обновлении модели OpenAI для пользователя {telegram_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка при обновлении предпочтений LLM для пользователя {telegram_id}: {e}")
            raise

    async def update_user_protocol_output_preference(self, telegram_id: int, mode: Optional[str]) -> User:
        """Обновить режим вывода протокола пользователя ('messages' или 'file')"""
        try:
            user = await self.get_user_by_telegram_id(telegram_id)
            if not user:
                raise UserNotFoundError(telegram_id)
            await self.db.update_user_protocol_output_preference(telegram_id, mode)
            updated_user = await self.get_user_by_telegram_id(telegram_id)
            if not updated_user:
                raise UserNotFoundError(telegram_id)
            logger.info(f"Обновлен режим вывода протокола для пользователя {telegram_id}: {mode}")
            return updated_user
        except UserNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Ошибка при обновлении режима вывода протокола для пользователя {telegram_id}: {e}")
            raise
    
    async def get_or_create_user(self, telegram_id: int, username: str = None, 
                                first_name: str = None, last_name: str = None) -> User:
        """Получить пользователя или создать нового, если не существует"""
        user = await self.get_user_by_telegram_id(telegram_id)
        if user:
            return user
        
        # Создаем нового пользователя
        user_data = UserCreate(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        )
        return await self.create_user(user_data)
