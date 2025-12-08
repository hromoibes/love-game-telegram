import logging
from typing import List

from openai import AsyncOpenAI, OpenAIError

from models import GameSession

logger = logging.getLogger(__name__)


SAFETY_RULES = (
    "Всегда избегай насилия, описаний несовершеннолетних и подробного порно. "
    "Говори мягко и игриво, без грубости."
)


class AIClient:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def _complete(self, messages: List[dict]) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.8,
                max_tokens=200,
            )
            return response.choices[0].message.content or ""
        except OpenAIError as exc:
            logger.error("Ошибка при обращении к ИИ: %s", exc)
            raise

    async def generate_question(self, session: GameSession) -> str:
        history_text = "\n".join(
            f"Вопрос: {item.question}\nОтвет: {item.answer or 'пока нет'}" for item in session.history[-5:]
        )
        prompt = (
            "Ты пишешь один вопрос для пары на русском языке. "
            "Будь тёплым, смешным и флиртующим, без пошлости. "
            "Чередуй темы: тело, желания, отношения и игровые задания. "
            "Не повторяй вопросы дословно. "
            f"Текущий уровень: {session.intimacy_level.label} {session.intimacy_level.emoji}. "
            f"Партнёры: {session.partner1_name} и {session.partner2_name}. "
            f"История последнего общение:\n{history_text}\n"
            f"{SAFETY_RULES}"
        )
        messages = [
            {"role": "system", "content": "Ты помогаешь вести игру-переписку для пары."},
            {"role": "user", "content": prompt},
        ]
        return await self._complete(messages)

    async def generate_summary(self, session: GameSession) -> str:
        entries = "\n".join(
            f"- {qa.question}\n  Ответ: {qa.answer or '—'}" for qa in session.history
        )
        prompt = (
            "Сделай короткое резюме сессии для пары. "
            "Опиши настроение, поддержку и открытость без критики. "
            "Добавь 3-5 мягких рекомендаций: темы для разговора, идеи для совместных действий, способы усилить доверие. "
            f"Партнёры: {session.partner1_name} и {session.partner2_name}. "
            f"Уровень откровенности: {session.intimacy_level.label}. "
            f"Всего вопросов: {session.current_question_index}/{session.max_questions}. "
            f"История:\n{entries}\n"
            f"{SAFETY_RULES}"
        )
        messages = [
            {"role": "system", "content": "Ты автор коротких и доброжелательных резюме."},
            {"role": "user", "content": prompt},
        ]
        return await self._complete(messages)
