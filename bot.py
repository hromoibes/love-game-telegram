import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set in environment")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set in environment")

ANSWER_TIMEOUT = 60
MAX_LEVEL = 3
MIN_LEVEL = 1


genai.configure(api_key=GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel("gemini-1.5-flash")


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
    skips_left: list[int] = field(default_factory=lambda: [1, 1])
    waiting_for_answer: bool = False
    last_question_id: Optional[int] = None
    reminder_job_name: Optional[str] = None

    def reset(self) -> None:
        self.player1 = None
        self.player2 = None
        self.current_player_index = 0
        self.level = 1
        self.history.clear()
        self.skips_left = [1, 1]
        self.waiting_for_answer = False
        self.last_question_id = None
        self.reminder_job_name = None


SESSIONS: dict[int, GameSession] = {}


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
Сделай новый короткий вопрос для уровня {level} и учитывай предыдущие ответы.
"""
    try:
        resp = await asyncio.to_thread(_gemini_model.generate_content, prompt)
        text = resp.text.strip()
        if text.startswith("1.") or text.startswith("1)"):
            text = text[2:].strip()
        return text
    except Exception as exc:  # pragma: no cover - сетевой код
        logger.warning("Gemini fallback because of %s", exc)
        fallback = {
            1: "Какое ласковое слово тебе нравится больше всего?",
            2: "Ты бы хотел чаще говорить о своих желаниях?",
            3: "Что самое смелое ты бы сделал ради партнёра?",
        }
        return fallback[level]


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
        resp = await asyncio.to_thread(_gemini_model.generate_content, prompt)
        return resp.text.strip()
    except Exception as exc:  # pragma: no cover - сетевой код
        logger.warning("Gemini summary fallback because of %s", exc)
        return "Игра завершена! Вы отлично справились ❤️"


async def send_rules(update: Update):
    rules = (
        "🔥 Love4Two — правила:\n"
        "• Ответы: «да», «нет», одно слово или медиа.\n"
        "• У каждого игрока 1 пропуск — команда /skip.\n"
        "• 3 уровня: 1 — лёгкий флирт, 2 — средний, 3 — очень горячий.\n"
        "• Без вопросов про бывших и анала.\n"
        "• Вопросы по очереди, бот подстраивается под ответы.\n"
        "• На ответ 60 секунд, потом бот напомнит."
    )
    await update.message.reply_text(rules)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session.reset()
    await update.message.reply_text(
        "🔥 Love4Two — игра для пары.\nНапиши имя первого игрока:"
    )
    context.user_data["awaiting_name1"] = True


async def ask_names(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    name = (update.message.text or "").strip()

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


def _schedule_reminder(context: ContextTypes.DEFAULT_TYPE, session: GameSession) -> None:
    if not context.job_queue or session.last_question_id is None:
        return

    job_name = f"reminder-{session.chat_id}-{session.last_question_id}"
    _cancel_reminder(context, session)

    context.job_queue.run_once(
        _reminder_job,
        when=ANSWER_TIMEOUT,
        chat_id=session.chat_id,
        name=job_name,
    )
    session.reminder_job_name = job_name


def _cancel_reminder(context: ContextTypes.DEFAULT_TYPE, session: GameSession) -> None:
    if session.reminder_job_name and context.job_queue:
        for job in context.job_queue.get_jobs_by_name(session.reminder_job_name):
            job.schedule_removal()
    session.reminder_job_name = None


async def _reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if job is None:
        return
    chat_id = job.chat_id
    session = get_session(chat_id)
    if session.waiting_for_answer and session.last_question_id is not None:
        qa = session.history[session.last_question_id]
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⏰ Напоминание! Ответ для {qa.player_name} на вопрос:\n"
                f"{qa.question}\n\nНе затягивайте — просто 'да', 'нет' или одно слово."
            ),
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
    question = await generate_question_ru(session.level, session, last_answer)

    player = current_player_name(session)
    qa = QAItem(player_name=player, level=session.level, question=question)
    session.history.append(qa)
    session.waiting_for_answer = True
    session.last_question_id = len(session.history) - 1

    await update.message.reply_text(
        f"🎯 Вопрос для *{player}* (уровень {session.level}):\n\n{question}",
        parse_mode="Markdown",
    )
    _schedule_reminder(context, session)


async def cmd_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.player1 or not session.player2:
        await update.message.reply_text("Сначала напишите имена через /start.")
        return

    if context.args:
        try:
            new_level = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Укажите уровень числом 1-3.")
            return
        new_level = max(MIN_LEVEL, min(MAX_LEVEL, new_level))
        session.level = new_level
        await update.message.reply_text(f"Текущий уровень: {session.level}.")
    else:
        await update.message.reply_text(
            f"Текущий уровень: {session.level}. Используйте /level 1|2|3 чтобы изменить."
        )


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.waiting_for_answer or session.last_question_id is None:
        await update.message.reply_text("Нет активного вопроса. Введите /question.")
        return

    player_index = session.current_player_index
    if session.skips_left[player_index] <= 0:
        await update.message.reply_text("Пропуск уже израсходован.")
        return

    session.skips_left[player_index] -= 1
    qa = session.history[session.last_question_id]
    qa.skipped = True
    qa.answer = "<пропуск>"
    session.waiting_for_answer = False
    next_player(session)
    _cancel_reminder(context, session)

    await update.message.reply_text("🛟 Пропуск принят. Введите /question для следующего.")


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if context.user_data.get("awaiting_name1") or context.user_data.get("awaiting_name2"):
        await ask_names(update, context)
        return

    if not session.waiting_for_answer or session.last_question_id is None:
        await update.message.reply_text("Напиши /question для следующего вопроса.")
        return

    qa = session.history[session.last_question_id]
    text = update.message.text or "<media>"
    if not is_short_answer(text):
        await update.message.reply_text("Ответ должен быть коротким.")
        return

    qa.answer = text.strip()
    session.waiting_for_answer = False
    _cancel_reminder(context, session)

    normalized = qa.answer.lower()
    if normalized.startswith("да"):
        if session.level < MAX_LEVEL and random.random() < 0.7:
            session.level += 1
    elif normalized.startswith("нет"):
        if session.level > MIN_LEVEL and random.random() < 0.3:
            session.level -= 1

    next_player(session)
    await update.message.reply_text("✅ Ответ принят. Введите /question для следующего.")


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_rules(update)


async def cmd_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    summary = await generate_summary_ru(session)
    await update.message.reply_text(summary)


async def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("rules", cmd_rules))
    application.add_handler(CommandHandler("question", cmd_question))
    application.add_handler(CommandHandler("level", cmd_level))
    application.add_handler(CommandHandler("skip", cmd_skip))
    application.add_handler(CommandHandler("finish", cmd_finish))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_answer))

    logger.info("Bot starting...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
