import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import google.generativeai as genai

# --- Настройки логов ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Конфигурация API ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set in environment")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set in environment")

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

ANSWER_TIMEOUT = 60
MAX_LEVEL = 3
MIN_LEVEL = 1

# --- Классы данных ---
@dataclass
class QAItem:
    player_name: str
    level: int
    question: str
    answer: str | None = None
    skipped: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class GameSession:
    chat_id: int
    player1: str | None = None
    player2: str | None = None
    current_player_index: int = 0
    level: int = 1
    history: list[QAItem] = field(default_factory=list)
    skips_left: int = 1
    waiting_for_answer: bool = False
    last_question_id: int | None = None


SESSIONS: dict[int, GameSession] = {}

# --- Вспомогательные функции ---
def get_session(chat_id: int) -> GameSession:
    if chat_id not in SESSIONS:
        SESSIONS[chat_id] = GameSession(chat_id=chat_id)
    return SESSIONS[chat_id]


def current_player_name(session: GameSession) -> str:
    return [session.player1, session.player2][session.current_player_index]


def next_player(session: GameSession) -> None:
    session.current_player_index = 1 - session.current_player_index


def is_short_answer(text: str | None) -> bool:
    if not text:
        return True
    return len(text.strip().split()) <= 3


# --- Генерация вопросов ---
async def generate_question_ru(level: int, session: GameSession, last_answer: str | None):
    history_text = "\n".join(
        f"{i.player_name}: {i.question} → {i.answer or 'нет ответа'}" for i in session.history[-6:]
    )
    prompt = f"""
Ты — ведущий игры для пары. Язык — русский.
Формат:
- ответы «да», «нет», одно слово или медиа
- 3 уровня (1 — лёгкий, 2 — средний, 3 — горячий)
- без бывших и анала

История: {history_text or 'нет'}
Последний ответ: {last_answer or 'нет'}
Сделай новый короткий вопрос для уровня {level}.
"""
    try:
        resp = await asyncio.to_thread(gemini_model.generate_content, prompt)
        text = resp.text.strip()
        if text.startswith("1.") or text.startswith("1)"):
            text = text[2:].strip()
        return text
    except Exception:
        fallback = {
            1: "Какое ласковое слово тебе нравится больше всего?",
            2: "Ты бы хотел чаще говорить о своих желаниях?",
            3: "Что самое смелое ты бы сделал ради партнёра?",
        }
        return fallback[level]


# --- Генерация итогов ---
async def generate_summary_ru(session: GameSession):
    history_text = "\n".join(
        f"{i.player_name}: {i.question} → {i.answer or 'нет ответа'}" for i in session.history
    )
    prompt = f"""
Сделай короткое резюме игры двух людей ({session.player1} и {session.player2})
по их ответам:
{history_text}

1. Дай тёплое заключение (2–3 предложения)
2. Дай 3 коротких совета улучшения отношений
3. Без морали и без упоминания бывших
"""
    try:
        resp = await asyncio.to_thread(gemini_model.generate_content, prompt)
        return resp.text.strip()
    except Exception:
        return "Игра завершена! Вы отлично справились ❤️"


# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session.history.clear()
    session.level = 1
    session.skips_left = 1
    await update.message.reply_text(
        "🔥 Love4Two — игра для пары.\nНапиши имя первого игрока:"
    )
    context.user_data["awaiting_name1"] = True


async def ask_names(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    name = update.message.text.strip()

    if context.user_data.get("awaiting_name1"):
        session.player1 = name
        context.user_data["awaiting_name1"] = False
        context.user_data["awaiting_name2"] = True
        await update.message.reply_text("Теперь имя второго игрока:")
        return

    if context.user_data.get("awaiting_name2"):
        session.player2 = name
        context.user_data["awaiting_name2"] = False
        await update.message.reply_text(
            f"Отлично! {session.player1} и {session.player2}, давайте начнём.\nВведите /question."
        )


async def cmd_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.player1 or not session.player2:
        await update.message.reply_text("Сначала напишите имена через /start.")
        return

    if session.waiting_for_answer:
        await update.message.reply_text("Сначала ответьте на предыдущий вопрос!")
        return

    last_answer = session.history[-1].answer if session.history else None
    q = await generate_question_ru(session.level, session, last_answer)

    player = current_player_name(session)
    qa = QAItem(player_name=player, level=session.level, question=q)
    session.history.append(qa)
    session.waiting_for_answer = True
    session.last_question_id = len(session.history) - 1

    await update.message.reply_text(
        f"🎯 Вопрос для *{player}* (уровень {session.level}):\n\n{q}",
        parse_mode="Markdown",
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if context.user_data.get("awaiting_name1") or context.user_data.get("awaiting_name2"):
        await ask_names(update, context)
        return

    if not session.waiting_for_answer:
        await update.message.reply_text("Напиши /question для следующего вопроса.")
        return

    item = session.history[session.last_question_id]
    text = update.message.text or "<media>"
    if not is_short_answer(text):
        await update.message.reply_text("Ответ должен быть коротким.")
        return

    item.answer = text.strip()
    session.waiting_for_answer = False
    next_player(session)
    await update.message.reply_text("✅ Ответ принят. Введите /question для следующего.")


async def cmd_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    summary = await generate_summary_ru(session)
    await update.message.reply_text(summary)


# --- Запуск ---
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("question", cmd_question))
    app.add_handler(CommandHandler("finish", cmd_finish))
    app.add_handler(MessageHandler(filters.ALL, handle_answer))

    logger.info("Bot starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
