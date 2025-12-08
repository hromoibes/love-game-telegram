import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReplyKeyboardMarkup,
                           KeyboardButton)

from ai_client import AIClient
from config import settings
from game_engine import GameEngine, SessionManager
from models import GameSession, IntimacyLevel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=settings.telegram_token, parse_mode=ParseMode.HTML)
dp = Dispatcher()
session_manager = SessionManager()
ai_client = AIClient(api_key=settings.ai_api_key)
game_engine = GameEngine(session_manager=session_manager)


class SetupForm(StatesGroup):
    waiting_names = State()
    waiting_level = State()
    waiting_length = State()
    playing = State()


def level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Лайт", callback_data="level:light")],
            [InlineKeyboardButton(text="🔥 Горячо", callback_data="level:hot")],
            [InlineKeyboardButton(text="💣 Очень смело", callback_data="level:bold")],
        ]
    )


def length_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="10 вопросов", callback_data="len:10")],
            [InlineKeyboardButton(text="15 вопросов", callback_data="len:15")],
            [InlineKeyboardButton(text="20 вопросов", callback_data="len:20")],
        ]
    )


def answer_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔥 Обожаю"), KeyboardButton(text="😳 Смущает, но ок")],
            [KeyboardButton(text="❌ Пропустить вопрос")],
            [KeyboardButton(text="➡️ Давай мягче"), KeyboardButton(text="⚡ Давай смелее")],
            [KeyboardButton(text="🏁 Завершить игру")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def parse_names(text: str) -> tuple[str, str]:
    parts = [p.strip() for p in text.replace(" и ", ",").split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return text.strip(), "Партнёр"


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    session_manager.finish(message.chat.id)
    await state.clear()
    await message.answer(
        "Привет! Это игра для пары. Немного флирта, без грубостей и всё конфиденциально.\n"
        "Напиши имена партнёров через запятую: например, <b>Аня, Сергей</b>.",
    )
    await state.set_state(SetupForm.waiting_names)


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Игра задаёт вопросы по очереди партнёрам.\n"
        "Уровни: 💬 мягкий флирт, 🔥 горячо, 💣 очень смело.\n"
        "Команды: /start — начать заново, /stop — завершить сессии с резюме."
    )


@dp.message(Command("stop"))
async def cmd_stop(message: Message, state: FSMContext) -> None:
    await finish_game(chat_id=message.chat.id, message=message)
    await state.clear()


@dp.message(SetupForm.waiting_names)
async def get_names(message: Message, state: FSMContext) -> None:
    partner1, partner2 = parse_names(message.text)
    await state.update_data(partner1=partner1, partner2=partner2)
    await message.answer(
        f"Супер! Партнёры: {partner1} и {partner2}. Выберите уровень откровенности:",
        reply_markup=level_keyboard(),
    )
    await state.set_state(SetupForm.waiting_level)


@dp.callback_query(F.data.startswith("level:"), SetupForm.waiting_level)
async def choose_level(callback: CallbackQuery, state: FSMContext) -> None:
    level_value = callback.data.split(":", maxsplit=1)[1]
    await state.update_data(level=IntimacyLevel(level_value))
    await callback.message.edit_text("Отлично! Теперь выберите длину сессии:")
    await callback.message.answer("Сколько вопросов сыграем?", reply_markup=length_keyboard())
    await state.set_state(SetupForm.waiting_length)
    await callback.answer()


@dp.callback_query(F.data.startswith("len:"), SetupForm.waiting_length)
async def choose_length(callback: CallbackQuery, state: FSMContext) -> None:
    length_value = int(callback.data.split(":", maxsplit=1)[1])
    data = await state.get_data()
    partner1 = data["partner1"]
    partner2 = data["partner2"]
    level = data["level"]

    session = session_manager.get_or_create(
        chat_id=callback.message.chat.id,
        partner1_name=partner1,
        partner2_name=partner2,
        intimacy_level=level,
        max_questions=length_value,
    )
    await state.set_state(SetupForm.playing)
    await callback.message.answer(
        f"Поехали! Уровень: {session.intimacy_level.label} {session.intimacy_level.emoji}. "
        f"Всего вопросов: {session.max_questions}.",
        reply_markup=answer_keyboard(),
    )
    await callback.answer()
    await ask_next_question(callback.message.chat.id, callback.message)


@dp.message(SetupForm.playing)
async def handle_answer(message: Message, state: FSMContext) -> None:
    text = message.text
    if text == "❌ Пропустить вопрос":
        await ask_next_question(message.chat.id, message, skipped=True)
        return
    if text == "➡️ Давай мягче":
        session = session_manager.get(message.chat.id)
        if session:
            new_level = game_engine.next_level(session.intimacy_level, direction="down")
            session_manager.update_level(message.chat.id, new_level)
            await message.answer(f"Уровень снижен до: {new_level.label} {new_level.emoji}")
        return
    if text == "⚡ Давай смелее":
        session = session_manager.get(message.chat.id)
        if session:
            new_level = game_engine.next_level(session.intimacy_level, direction="up")
            session_manager.update_level(message.chat.id, new_level)
            await message.answer(f"Уровень повышен до: {new_level.label} {new_level.emoji}")
        return
    if text == "🏁 Завершить игру":
        await finish_game(chat_id=message.chat.id, message=message)
        await state.clear()
        return

    game_engine.record_answer(message.chat.id, text)
    await ask_next_question(message.chat.id, message)


async def ask_next_question(chat_id: int, message: Message, skipped: bool = False) -> None:
    session = session_manager.get(chat_id)
    if not session:
        await message.answer("Сессия не найдена. Нажмите /start, чтобы начать заново.")
        return

    if session.is_finished:
        await finish_game(chat_id=chat_id, message=message)
        return

    if skipped:
        game_engine.record_answer(chat_id, "Пропущено")

    try:
        question = await ai_client.generate_question(session)
    except Exception:
        question = fallback_question(session)

    game_engine.add_question(chat_id, question)
    await message.answer(question, reply_markup=answer_keyboard())


async def finish_game(chat_id: int, message: Message) -> None:
    session = session_manager.finish(chat_id)
    if not session:
        await message.answer("Нет активной игры. Нажмите /start, чтобы начать.")
        return
    try:
        summary = await ai_client.generate_summary(session)
    except Exception:
        summary = basic_summary(session)
    await message.answer(
        "🏁 Игра завершена! Вот мини-резюме:\n" + summary,
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True),
    )


def fallback_question(session: GameSession) -> str:
    presets = [
        "Расскажите, какой комплимент нравится каждому из вас больше всего?",
        "Назовите место, где вы бы хотели устроить свидание вдвоём.",
        "Что помогает вам быстрее расслабиться вместе?",
        "Вспомните момент, когда вы чувствовали сильное доверие друг к другу.",
    ]
    idx = session.current_question_index % len(presets)
    return presets[idx]


def basic_summary(session: GameSession) -> str:
    answered = [qa for qa in session.history if qa.answer]
    return (
        f"Вы прошли {len(answered)} вопросов из {session.max_questions}. "
        "Судя по ответам, вам нравится исследовать друг друга и поддерживать доверие."
    )
