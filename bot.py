import logging
import asyncio
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import google.generativeai as genai

# ==========================================
# НАСТРОЙКИ
# ==========================================
# Чтение токенов из переменных окружения (обязательно для Render)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ВСТАВЬ_СЮДА_ТОКЕН_TELEGRAM")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "ВСТАВЬ_СЮДА_API_KEY_GEMINI")

# ==========================================
# ЛОГИКА ИИ
# ==========================================

# Dummy Model для обработки ошибок или отсутствия ключа
class DummyModel:
    """Заглушка, если API ключ Gemini отсутствует или невалиден."""
    def generate_content(self, prompt):
        # Возвращает объект, имитирующий ответ Gemini
        return type('Response', (object,), {'text': "Ошибка ИИ: Проверьте ключ Gemini/интернет. Резервный вопрос: Как ты себя чувствуешь?"})()

# Настройка Gemini
model = None
if GEMINI_API_KEY and GEMINI_API_KEY != "ВСТАВЬ_СЮДА_API_KEY_GEMINI":
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Используем gemini-2.5-flash для более быстрого и дешевого ответа
        model = genai.GenerativeModel('gemini-2.5-flash') 
    except Exception as e:
        logging.error(f"Failed to configure Gemini API: {e}. Using Dummy Model.")
        model = DummyModel()
else:
    logging.warning("GEMINI_API_KEY is missing or using placeholder. AI functionality will be limited. Using Dummy Model.")
    model = DummyModel()

SYSTEM_PROMPT = (
    "Ты — ведущий эротической игры для пары. Твоя задача — генерировать вопросы и задания."
    "Правила:"
    "1. Есть 3 уровня: 1 (легкий флирт), 2 (средний, возбуждение), 3 (очень горячо)."
    "2. СТРОГИЕ ЗАПРЕТЫ: Никаких упоминаний бывших. Никакого анала. Это табу."
    "3. Вопросы должны подразумевать ответ 'Да', 'Нет', одно слово или присылку фото/видео."
    "4. Учитывай контекст: если игроки отвечают 'Да', повышай градус."
    "5. Будь кратким. Не пиши вступлений, сразу вопрос."
)

async def get_ai_question(level, history_summary, player_name):
    """Генерирует вопрос через ИИ."""
    prompt = (
        f"{SYSTEM_PROMPT}\n"
        f"Текущий уровень: {level}.\n"
        f"Сейчас ход игрока по имени: {player_name}.\n"
        f"Краткая история игры: {history_summary}\n"
        f"Придумай 1 задание или вопрос для {player_name}."
    )
    try:
        # Устанавливаем таймаут на всякий случай
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, prompt), 
            timeout=15.0
        )
        return response.text.strip()
    except (asyncio.TimeoutError, Exception) as e:
        logging.error(f"AI Error during question generation: {e}")
        return "Расскажи часть тела партнера, которая тебе нравится больше всего. (Ошибка ИИ, резервный вопрос)"

async def get_ai_summary(history_full):
    """Генерирует резюме игры."""
    prompt = (
        f"{SYSTEM_PROMPT}\n"
        "Игра окончена. Проанализируй ответы пары и составь психологический и сексуальный портрет их совместимости на основе этой игры."
        "Дай советы, что им попробовать в постели. Будь позитивным и игривым."
        f"История игры:\n{history_full}"
    )
    try:
        # Устанавливаем таймаут
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, prompt), 
            timeout=30.0
        )
        return response.text.strip()
    except (asyncio.TimeoutError, Exception) as e:
        logging.error(f"AI Error during summary generation: {e}")
        return "Вы отлично провели время! (Ошибка генерации резюме)"

# ==========================================
# ЛОГИКА БОТА
# ==========================================

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Состояния
REGISTER, GAME_LOOP, WAITING_FOR_ANSWER = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 **Привет! Я ИИ-бот для пар @love4two.**\n\n"
        "Правила:\n"
        "- Таймер 60 сек.\n"
        "- 3 уровня пикантности.\n"
        "- ИИ подстраивается под вас.\n"
        "- В конце я выдам резюме вашей пары.\n\n"
        "Введите имя **первого игрока**:",
        parse_mode="Markdown"
    )
    context.user_data['players'] = []
    context.user_data['history'] = [] # Для полного лога
    context.user_data['history_summary'] = "" # Для контекста вопросов
    return REGISTER

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data['players'].append({'name': name, 'skips': 1, 'id': update.effective_user.id})
    
    if len(context.user_data['players']) == 1:
        await update.message.reply_text("Супер. Введите имя **второго игрока**:")
        return REGISTER
    else:
        p1 = context.user_data['players'][0]['name']
        p2 = context.user_data['players'][1]['name']
        await update.message.reply_text(
            f"Игроки {p1} и {p2} в игре!\n"
            "Начинаем с Уровня 1.\n"
            "Нажмите /question, чтобы ИИ сгенерировал первый вопрос."
        )
        context.user_data['level'] = 1
        context.user_data['turn'] = 0
        return GAME_LOOP

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    players = context.user_data.get('players')
    if not players:
        await update.message.reply_text("Нажмите /start")
        return ConversationHandler.END

    # Проверка, что спрашивает игрок, чей сейчас ход (для безопасности)
    turn = context.user_data['turn']
    current_player = players[turn]
    
    # Можно добавить проверку: if update.effective_user.id != current_player['id'] and len(players) == 2:
    #     await update.message.reply_text(f"Сейчас ход игрока {current_player['name']}!")
    #     return GAME_LOOP 

    level = context.user_data['level']
    history_summary = context.user_data.get('history_summary', '')

    # Индикация загрузки (так как ИИ думает пару секунд)
    msg = await update.message.reply_text("🧠 *ИИ придумывает вопрос...*", parse_mode="Markdown")

    # Генерация вопроса
    question = await get_ai_question(level, history_summary, current_player['name'])
    
    # Удаляем сообщение о загрузке и пишем вопрос
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    
    await update.message.reply_text(
        f"🎲 **Ход: {current_player['name']}** (Уровень {level})\n\n"
        f"{question}\n\n"
        f"⏳ 60 секунд! (Ответ: текст, фото, видео или /skip)",
        parse_mode="Markdown"
    )
    
    # Сохраняем вопрос в контекст
    context.user_data['current_question'] = question

    # Таймер
    chat_id = update.effective_message.chat_id
    context.job_queue.run_once(alarm, 60, chat_id=chat_id, name=str(chat_id), data={'player': current_player['name']})
    
    return WAITING_FOR_ANSWER

async def alarm(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(job.chat_id, text=f"⏰ ВРЕМЯ ВЫШЛО! {job.data['player']}, ты наказан(а)! Целуй партнера куда он скажет. Жми /question дальше.")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Убираем таймер
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_message.chat_id))
    for job in jobs:
        job.schedule_removal()

    # Проверка, что отвечает игрок, чей сейчас ход
    players = context.user_data.get('players', [])
    if not players:
        await update.message.reply_text("Игра не начата. Нажмите /start")
        return ConversationHandler.END
        
    turn = context.user_data['turn']
    current_player_id = players[turn]['id']
    
    # Если отвечает не тот игрок
    if update.effective_user.id != current_player_id and len(players) == 2:
        await update.message.reply_text(f"Подожди! Сейчас отвечает {players[turn]['name']}.")
        return WAITING_FOR_ANSWER # Ждем ответа от нужного игрока

    user_text = update.message.text if update.message.text else "[МЕДИА ФАЙЛ]"
    
    # Обработка /skip
    if user_text == '/skip':
        if players[turn]['skips'] > 0:
            players[turn]['skips'] -= 1
            await update.message.reply_text(f"Пропуск принят. Осталось пропусков: {players[turn]['skips']}. Жми /question.")
        else:
            await update.message.reply_text("Пропуски кончились! Отвечай или выполняй наказание. Жми /question.")
        
        # Переход хода
        context.user_data['turn'] = 1 - context.user_data['turn']
        return GAME_LOOP

    # Логика уровней
    if user_text.lower() in ['да', 'yes', 'хочу', 'конечно']:
        # Повышаем уровень после "да"
        if context.user_data['level'] < 3:
             context.user_data['level'] += 1
             await update.message.reply_text("🔥 Ого! Ответ 'Да' повышает градус! Следующий вопрос будет горячее.")

    # Сохраняем историю для ИИ
    player_name = players[turn]['name']
    question = context.user_data.get('current_question', 'Вопрос')
    
    entry = f"Вопрос к {player_name}: {question}. Ответ: {user_text}."
    context.user_data['history'].append(entry)
    # Держим краткую историю (последние 3 хода) для генерации вопросов
    context.user_data['history_summary'] += f" {entry}"
    if len(context.user_data['history_summary']) > 500:
        context.user_data['history_summary'] = context.user_data['history_summary'][-500:]

    await update.message.reply_text("Принято! 😏 Жми /question для следующего хода.\nИли /stop чтобы закончить и получить резюме.")
    
    # Переход хода
    context.user_data['turn'] = 1 - context.user_data['turn']
    return GAME_LOOP

async def stop_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация финального отчета."""
    # Удаляем все активные таймеры перед завершением
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_message.chat_id))
    for job in jobs:
        job.schedule_removal()
        
    history = "\n".join(context.user_data.get('history', []))
    if not history:
        await update.message.reply_text("Вы толком не играли :( Начните заново /start")
        return ConversationHandler.END
        
    msg = await update.message.reply_text("🏁 Игра окончена! ИИ анализирует вашу химию... (подождите пару секунд)", parse_mode="Markdown")
    
    summary = await get_ai_summary(history)
    
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    await update.message.reply_text(f"📋 **РЕЗЮМЕ ПАРЫ**:\n\n{summary}", parse_mode="Markdown")
    
    return ConversationHandler.END

# Настройка приложения
def main():
    # Проверяем токен
    if (TELEGRAM_TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН_TELEGRAM" and not os.environ.get("TELEGRAM_TOKEN")):
        print("ОШИБКА: Вы не вставили токен бота в файл или не установили его в переменные окружения! Бот не запустится.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REGISTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, register)],
            GAME_LOOP: [
                CommandHandler("question", ask_question),
                CommandHandler("stop", stop_game) 
            ],
            WAITING_FOR_ANSWER: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE, handle_answer),
                CommandHandler("skip", handle_answer) 
            ],
        },
        fallbacks=[CommandHandler("stop", stop_game)],
    )

    application.add_handler(conv_handler)
    
    # Запуск бота
    print("Бот запущен. Ожидание обновлений...")
    application.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    # Логирование для отладки
    logging.getLogger('google').setLevel(logging.WARNING)
    main()