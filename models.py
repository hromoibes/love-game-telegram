from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class IntimacyLevel(str, Enum):
    LIGHT = "light"
    HOT = "hot"
    BOLD = "bold"

    @property
    def emoji(self) -> str:
        return {
            IntimacyLevel.LIGHT: "💬",
            IntimacyLevel.HOT: "🔥",
            IntimacyLevel.BOLD: "💣",
        }[self]

    @property
    def label(self) -> str:
        return {
            IntimacyLevel.LIGHT: "Лайт",
            IntimacyLevel.HOT: "Горячо",
            IntimacyLevel.BOLD: "Очень смело",
        }[self]


class QAItem(BaseModel):
    question: str
    answer: Optional[str] = None
    target: str = Field(default="оба", description="кому адресован вопрос")


class GameSession(BaseModel):
    chat_id: int
    partner1_name: str
    partner2_name: str
    intimacy_level: IntimacyLevel
    max_questions: int
    current_question_index: int = 0
    history: List[QAItem] = Field(default_factory=list)

    @property
    def is_finished(self) -> bool:
        return self.current_question_index >= self.max_questions

    def add_question(self, question: str, target: str = "оба") -> None:
        self.history.append(QAItem(question=question, target=target))
        self.current_question_index += 1

    def add_answer(self, answer: str) -> None:
        if not self.history:
            return
        self.history[-1].answer = answer
