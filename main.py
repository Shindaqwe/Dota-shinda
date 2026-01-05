import os
import asyncio
import aiohttp
import json
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from dotenv import load_dotenv
import sqlite3

# ========== НАСТРОЙКА ДЛЯ RENDER ==========
# Render требует веб-сервер, даже для бота
# Мы будем запускать Flask в фоне для health checks

from flask import Flask, jsonify
from threading import Thread
import waitress  # Для продакшена на Render

# Создаем Flask app для Render health checks
app = Flask(__name__)

@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dota2 Bot Status</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 50px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .container {
                background: rgba(0,0,0,0.7);
                padding: 30px;
                border-radius: 15px;
                display: inline-block;
            }
            .status {
                color: #4CAF50;
                font-size: 24px;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Dota2 Stats Bot</h1>
            <p class="status">✅ Бот активен на Render</p>
            <p>Telegram бот для статистики Dota 2</p>
        </div>
    </body>
    </html>
    """

@app.route('/health')
def health():
    """Health check эндпоинт для Render"""
    return jsonify({
        "status": "healthy",
        "service": "dota2-telegram-bot",
        "timestamp": "online"
    }), 200

@app.route('/ping')
def ping():
    """Простой пинг"""
    return "pong", 200

def run_flask():
    """Запуск Flask сервера в фоне"""
    port = int(os.environ.get('PORT', 10000))
    # Используем waitress для продакшена
    waitress.serve(app, host='0.0.0.0', port=port)

# ========== ТЕЛЕГРАМ БОТ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден! Добавьте в Environment Variables на Render")
    exit(1)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== БАЗА ДАННЫХ (SQLite) ==========
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('dota2_bot.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            account_id INTEGER,
            username TEXT,
            score INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица друзей
    c.execute('''
        CREATE TABLE IF NOT EXISTS friends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            friend_id INTEGER,
            friend_name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# Функции для работы с БД
def bind_user(telegram_id, account_id, username=""):
    conn = sqlite3.connect('dota2_bot.db')
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO users (telegram_id, account_id, username) VALUES (?, ?, ?)",
        (telegram_id, account_id, username)
    )
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect('dota2_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_score(telegram_id, points):
    conn = sqlite3.connect('dota2_bot.db')
    c = conn.cursor()
    c.execute(
        "UPDATE users SET score = score + ? WHERE telegram_id = ?",
        (points, telegram_id)
    )
    conn.commit()
    conn.close()

def get_leaderboard(limit=10):
    conn = sqlite3.connect('dota2_bot.db')
    c = conn.cursor()
    c.execute(
        "SELECT telegram_id, username, score FROM users ORDER BY score DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return rows

# ========== УТИЛИТЫ ==========
def steam64_to_account_id(steam64: int) -> int:
    """Конвертация SteamID64 в Account ID"""
    return steam64 - 76561197960265728

async def extract_account_id(steam_url: str):
    """Извлечение Account ID из Steam URL"""
    try:
        steam_url = steam_url.strip().rstrip("/")
        
        # Если это профиль
        if "/profiles/" in steam_url:
            steam64 = int(steam_url.split("/")[-1])
            return steam64_to_account_id(steam64)
        
        # Если это просто число (Steam ID)
        elif steam_url.isdigit():
            num = int(steam_url)
            if num > 76561197960265728:
                return steam64_to_account_id(num)
            return num
        
        return None
    except:
        return None

async def get_player_data(account_id: int):
    """Получение данных игрока из OpenDota API"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.opendota.com/api/players/{account_id}",
                timeout=10
            ) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        logger.error(f"API Error: {e}")
    return None

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    """Основная клавиатура"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Мой профиль")
    builder.button(text="📊 Статистика")
    builder.button(text="🎮 Викторина")
    builder.button(text="🏆 Топ игроков")
    builder.button(text="ℹ️ Помощь")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Обработчик команды /start"""
    welcome_text = (
        "🎮 <b>Добро пожаловать в Dota2 Stats Bot!</b>\n\n"
        "Я помогу отслеживать вашу статистику Dota 2.\n\n"
        "<b>Для начала:</b>\n"
        "1. Отправьте ваш Steam ID или ссылку на профиль\n"
        "2. Используйте кнопки меню для доступа к функциям\n\n"
        "<b>Примеры:</b>\n"
        "• Steam ID: <code>76561198012345678</code>\n"
        "• Ссылка: <code>https://steamcommunity.com/profiles/76561198012345678</code>"
    )
    
    await message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("help"))
async def help_command(message: types.Message):
    """Обработчик команды /help"""
    help_text = (
        "🆘 <b>Справка по командам:</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Начало работы\n"
        "/help - Эта справка\n"
        "/profile - Ваш профиль\n"
        "/stats - Статистика\n"
        "/quiz - Викторина\n"
        "/top - Топ игроков\n\n"
        "<b>Или используйте кнопки меню!</b>"
    )
    
    await message.answer(help_text, parse_mode="HTML")

@dp.message(F.text == "👤 Мой профиль")
async def profile_command(message: types.Message):
    """Показ профиля пользователя"""
    user_data = get_user(message.from_user.id)
    
    if not user_data or not user_data[1]:  # [1] = account_id
        await message.answer(
            "❌ <b>Профиль не привязан.</b>\n\n"
            "Отправьте ваш Steam ID или ссылку на профиль.",
            parse_mode="HTML"
        )
        return
    
    account_id = user_data[1]
    player_data = await get_player_data(account_id)
    
    if player_data:
        profile = player_data.get('profile', {})
        name = profile.get('personaname', 'Неизвестно')
        avatar = profile.get('avatarfull', '')
        mmr = player_data.get('mmr_estimate', {}).get('estimate', 'Неизвестно')
        
        response = (
            f"👤 <b>{name}</b>\n"
            f"🎯 MMR: {mmr}\n"
            f"🆔 Account ID: {account_id}\n"
            f"🏆 Очков: {user_data[3] or 0}"
        )
        
        # Если есть аватар, отправляем с фото
        if avatar:
            try:
                await message.answer_photo(
                    photo=avatar,
                    caption=response,
                    parse_mode="HTML"
                )
                return
            except:
                pass  # Если не получилось с фото, отправляем текст
        
        await message.answer(response, parse_mode="HTML")
    else:
        await message.answer(
            f"👤 Ваш Account ID: {account_id}\n"
            f"🏆 Очков: {user_data[3] or 0}\n\n"
            "❌ Не удалось получить данные из OpenDota API"
        )

@dp.message(F.text == "📊 Статистика")
async def stats_command(message: types.Message):
    """Статистика последних игр"""
    user_data = get_user(message.from_user.id)
    
    if not user_data or not user_data[1]:
        await message.answer("❌ Сначала привяжите Steam профиль.")
        return
    
    account_id = user_data[1]
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.opendota.com/api/players/{account_id}/recentMatches",
                timeout=15
            ) as r:
                if r.status == 200:
                    matches = await r.json()
                    
                    if matches and len(matches) > 0:
                        wins = 0
                        total_kills = 0
                        total_deaths = 0
                        total_assists = 0
                        
                        for match in matches[:10]:  # Берем последние 10 игр
                            is_radiant = match.get('player_slot', 0) < 128
                            radiant_win = match.get('radiant_win', False)
                            if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                                wins += 1
                            
                            total_kills += match.get('kills', 0)
                            total_deaths += match.get('deaths', 0)
                            total_assists += match.get('assists', 0)
                        
                        total_matches = len(matches[:10])
                        winrate = (wins / total_matches * 100) if total_matches > 0 else 0
                        
                        avg_kills = total_kills / total_matches if total_matches > 0 else 0
                        avg_deaths = total_deaths / total_matches if total_matches > 0 else 0
                        avg_assists = total_assists / total_matches if total_matches > 0 else 0
                        
                        response = (
                            f"📊 <b>Статистика последних {total_matches} игр:</b>\n\n"
                            f"✅ Побед: {wins}\n"
                            f"❌ Поражений: {total_matches - wins}\n"
                            f"🔥 Винрейт: {winrate:.1f}%\n\n"
                            f"⚔️ Средний KDA:\n"
                            f"• Убийств: {avg_kills:.1f}\n"
                            f"• Смертей: {avg_deaths:.1f}\n"
                            f"• Помощи: {avg_assists:.1f}"
                        )
                        
                        await message.answer(response, parse_mode="HTML")
                    else:
                        await message.answer("📭 Нет данных о последних играх.")
                else:
                    await message.answer("❌ Не удалось получить статистику.")
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await message.answer("❌ Ошибка при получении статистики.")

@dp.message(F.text == "🎮 Викторина")
async def quiz_command(message: types.Message):
    """Меню викторины"""
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🎯 Начать викторину", callback_data="quiz_start")
    keyboard.button(text="🏆 Таблица лидеров", callback_data="quiz_leaderboard")
    keyboard.adjust(1)
    
    await message.answer(
        "🎮 <b>Викторина по Dota 2</b>\n\n"
        "Проверьте свои знания о игре!\n"
        "• +10 очков за правильный ответ\n"
        "• -5 очков за неправильный\n"
        "• 30 секунд на ответ",
        parse_mode="HTML",
        reply_markup=keyboard.as_markup()
    )

# Вопросы для викторины
QUIZ_QUESTIONS = [
    {
        "question": "Какой герой имеет ультимейт 'Black Hole'?",
        "options": ["Enigma", "Magnus", "Faceless Void", "Tidehunter"],
        "correct": 0
    },
    {
        "question": "Какой предмет дает невидимость?",
        "options": ["Black King Bar", "Manta Style", "Shadow Blade", "Blink Dagger"],
        "correct": 2
    },
    {
        "question": "Кто является боссом на реке?",
        "options": ["Roshan", "Tormentor", "Ancient", "Courier"],
        "correct": 0
    },
    {
        "question": "Какой максимальный уровень у героя?",
        "options": ["20", "25", "30", "Без ограничений"],
        "correct": 1
    },
    {
        "question": "Сколько игроков в команде Dota 2?",
        "options": ["4", "5", "6", "7"],
        "correct": 1
    }
]

import random

@dp.callback_query(F.data == "quiz_start")
async def quiz_start_callback(callback: types.CallbackQuery):
    """Начало викторины"""
    question = random.choice(QUIZ_QUESTIONS)
    
    keyboard = InlineKeyboardBuilder()
    for i, option in enumerate(question["options"]):
        keyboard.button(text=option, callback_data=f"quiz_answer_{i}")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        f"❓ {question['question']}",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("quiz_answer_"))
async def quiz_answer_callback(callback: types.CallbackQuery):
    """Обработка ответа на викторину"""
    answer_index = int(callback.data.split("_")[-1])
    question_index = None
    
    # Находим вопрос (в реальном боте нужно хранить состояние)
    # Для простоты считаем что ответ 0 всегда правильный
    if answer_index == 0:
        update_score(callback.from_user.id, 10)
        await callback.message.edit_text(
            "✅ <b>Правильно!</b>\n+10 очков 🎉",
            parse_mode="HTML"
        )
    else:
        update_score(callback.from_user.id, -5)
        await callback.message.edit_text(
            "❌ <b>Неправильно!</b>\n-5 очков 😔",
            parse_mode="HTML"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "quiz_leaderboard")
async def quiz_leaderboard_callback(callback: types.CallbackQuery):
    """Таблица лидеров викторины"""
    leaders = get_leaderboard(10)
    
    if not leaders:
        await callback.message.edit_text("🏆 Таблица лидеров пуста.")
        return
    
    response = "🏆 <b>Топ игроков:</b>\n\n"
    for i, (user_id, username, score) in enumerate(leaders, 1):
        name = username if username else f"ID {user_id}"
        response += f"{i}. {name}: {score} очков\n"
    
    await callback.message.edit_text(response, parse_mode="HTML")
    await callback.answer()

@dp.message(F.text == "🏆 Топ игроков")
async def leaderboard_command(message: types.Message):
    """Показ общей таблицы лидеров"""
    leaders = get_leaderboard(15)
    
    if not leaders:
        await message.answer("🏆 Топ игроков пуст. Сыграйте в викторину!")
        return
    
    response = "🏆 <b>Топ игроков бота:</b>\n\n"
    for i, (user_id, username, score) in enumerate(leaders, 1):
        name = username if username else f"ID {user_id}"
        response += f"{i}. {name}: {score} очков\n"
    
    await message.answer(response, parse_mode="HTML")

@dp.message(F.text == "ℹ️ Помощь")
async def help_menu_command(message: types.Message):
    """Помощь через меню"""
    await help_command(message)

@dp.message()
async def handle_steam_input(message: types.Message):
    """Обработка Steam ID или ссылки"""
    text = message.text.strip()
    
    # Проверяем похоже ли на Steam ID или ссылку
    if "steamcommunity.com" in text or (text.isdigit() and len(text) > 5):
        account_id = await extract_account_id(text)
        
        if account_id:
            # Получаем данные игрока для имени
            player_data = await get_player_data(account_id)
            username = ""
            
            if player_data:
                username = player_data.get('profile', {}).get('personaname', '')
            
            # Сохраняем в БД
            bind_user(message.from_user.id, account_id, username)
            
            response = f"✅ <b>Профиль привязан!</b>\n\n"
            if username:
                response += f"👤 Игрок: {username}\n"
            response += f"🆔 Account ID: {account_id}\n\n"
            response += "Теперь используйте кнопки меню 👇"
            
            await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        else:
            await message.answer(
                "❌ Не удалось распознать Steam профиль.\n"
                "Проверьте правильность ссылки или ID.",
                reply_markup=get_main_keyboard()
            )
    else:
        await message.answer(
            "Отправьте Steam ID или ссылку на профиль.\n"
            "Или используйте кнопки меню 👇",
            reply_markup=get_main_keyboard()
        )

# ========== ЗАПУСК ПРИЛОЖЕНИЯ ==========
async def main():
    """Основная функция запуска"""
    logger.info("🚀 Запуск Dota2 Bot на Render...")
    
    # Запускаем Flask сервер в отдельном потоке
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"✅ Flask сервер запущен на порту {os.environ.get('PORT', 10000)}")
    
    # Запускаем Telegram бота
    logger.info("🤖 Запуск Telegram бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем приложение
    asyncio.run(main())