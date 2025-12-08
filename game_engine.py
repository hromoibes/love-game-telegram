from __future__ import annotations
from typing import Dict, Optional
import logging

from models import GameSession, IntimacyLevel

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[int, GameSession] = {}

    def get_or_create(
        self,
        chat_id: int,
        partner1_name: str,
        partner2_name: str,
        intimacy_level: IntimacyLevel,
        max_questions: int,
    ) -> GameSession:
        session = GameSession(
            chat_id=chat_id,
            partner1_name=partner1_name,
            partner2_name=partner2_name,
            intimacy_level=intimacy_level,
            max_questions=max_questions,
        )
        self._sessions[chat_id] = session
        return session

    def get(self, chat_id: int) -> Optional[GameSession]:
        return self._sessions.get(chat_id)

    def update_level(self, chat_id: int, level: IntimacyLevel) -> None:
        session = self.get(chat_id)
        if session:
            logger.info("Изменение уровня откровенности: %s -> %s", session.intimacy_level, level)
            session.intimacy_level = level

    def finish(self, chat_id: int) -> Optional[GameSession]:
        return self._sessions.pop(chat_id, None)


class GameEngine:
    def __init__(self, session_manager: SessionManager) -> None:
        self.session_manager = session_manager

    def record_answer(self, chat_id: int, answer: str) -> None:
        session = self.session_manager.get(chat_id)
        if not session:
            return
        session.add_answer(answer)

    def add_question(self, chat_id: int, question: str, target: str = "оба") -> None:
        session = self.session_manager.get(chat_id)
        if not session:
            return
        session.add_question(question=question, target=target)

    def next_level(self, level: IntimacyLevel, direction: str) -> IntimacyLevel:
        levels = [IntimacyLevel.LIGHT, IntimacyLevel.HOT, IntimacyLevel.BOLD]
        idx = levels.index(level)
        if direction == "up" and idx < len(levels) - 1:
            return levels[idx + 1]
        if direction == "down" and idx > 0:
            return levels[idx - 1]
        return level
