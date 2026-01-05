import os
import asyncio
import aiohttp
import json
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import sqlite3
from collections import Counter
import random

# ========== НАСТРОЙКА ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
STEAM_API_KEY = os.getenv("STEAM_API_KEY")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден!")
    exit(1)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    
    # Пользователи
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            steam_id TEXT,
            account_id INTEGER,
            username TEXT,
            score INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Друзья
    c.execute('''
        CREATE TABLE IF NOT EXISTS friends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            friend_account_id INTEGER,
            friend_name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id)
        )
    ''')
    
    # Состояния викторины
    c.execute('''
        CREATE TABLE IF NOT EXISTS quiz_state (
            user_id INTEGER PRIMARY KEY,
            current_question INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# ========== STATES ==========
class ProfileStates(StatesGroup):
    waiting_steam_url = State()
    waiting_friend = State()

# ========== STEAM UTILITIES ==========
def steam64_to_account_id(steam64: int) -> int:
    return steam64 - 76561197960265728

async def extract_account_id(steam_input: str):
    """Извлечение Account ID из любых форматов"""
    try:
        steam_input = steam_input.strip().rstrip("/")
        
        # Убираем параметры
        if "?" in steam_input:
            steam_input = steam_input.split("?")[0]
        
        # Если это уже account_id (маленькое число)
        if steam_input.isdigit():
            num = int(steam_input)
            if num < 10000000000:
                return num
        
        # 1. SteamID64 профиль (/profiles/)
        if "/profiles/" in steam_input:
            steam64 = int(steam_input.split("/profiles/")[-1].split("/")[0])
            return steam64_to_account_id(steam64)
        
        # 2. Vanity URL (/id/username)
        elif "/id/" in steam_input:
            if not STEAM_API_KEY:
                return None
            
            vanity = steam_input.split("/id/")[-1].split("/")[0]
            async with aiohttp.ClientSession() as session:
                url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
                params = {'key': STEAM_API_KEY, 'vanityurl': vanity}
                
                async with session.get(url, params=params, timeout=10) as r:
                    data = await r.json()
                    if data.get('response', {}).get('success') == 1:
                        steam64 = int(data['response']['steamid'])
                        return steam64_to_account_id(steam64)
            return None
        
        # 3. Просто SteamID64
        elif steam_input.isdigit():
            steam64 = int(steam_input)
            if steam64 > 76561197960265728:
                return steam64_to_account_id(steam64)
        
        # 4. Только vanity (без /id/)
        elif not steam_input.startswith("http"):
            if STEAM_API_KEY:
                async with aiohttp.ClientSession() as session:
                    url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
                    params = {'key': STEAM_API_KEY, 'vanityurl': steam_input}
                    
                    async with session.get(url, params=params, timeout=10) as r:
                        data = await r.json()
                        if data.get('response', {}).get('success') == 1:
                            steam64 = int(data['response']['steamid'])
                            return steam64_to_account_id(steam64)
        
        return None
        
    except Exception as e:
        logger.error(f"Ошибка Steam: {e}")
        return None

async def get_player_data(account_id: int):
    """Данные игрока"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.opendota.com/api/players/{account_id}",
                timeout=10
            ) as r:
                if r.status == 200:
                    return await r.json()
    except:
        return None

async def get_matches(account_id: int, limit=100):
    """Матчи игрока"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.opendota.com/api/players/{account_id}/matches",
                params={'limit': limit},
                timeout=15
            ) as r:
                if r.status == 200:
                    return await r.json()
    except:
        return []

async def get_heroes_data():
    """Данные героев"""
    try:
        with open('hero_names.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

async def get_winloss(account_id: int):
    """Статистика побед/поражений"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.opendota.com/api/players/{account_id}/wl",
                timeout=10
            ) as r:
                if r.status == 200:
                    return await r.json()
    except:
        return None

# ========== MMR TO RANK ==========
def get_rank_from_mmr(mmr):
    """Конвертация MMR в ранг"""
    ranks = {
        (0, 154): ("Uncalibrated", "❓"),
        (155, 309): ("Herald", "🛡️"),
        (310, 614): ("Guardian", "🛡️"),
        (615, 919): ("Crusader", "⚔️"),
        (920, 1224): ("Archon", "⚔️"),
        (1225, 1529): ("Legend", "⭐"),
        (1530, 1964): ("Ancient", "🏆"),
        (1965, 2454): ("Divine", "👑"),
        (2455, 10000): ("Immortal", "💎")
    }
    
    for (min_mmr, max_mmr), (rank_name, icon) in ranks.items():
        if min_mmr <= mmr <= max_mmr:
            return f"{icon} {rank_name}"
    return "Uncalibrated"

# ========== DATABASE FUNCTIONS ==========
def save_user(telegram_id, steam_id, account_id, username=""):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO users (telegram_id, steam_id, account_id, username) VALUES (?, ?, ?, ?)",
        (telegram_id, steam_id, account_id, username)
    )
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = c.fetchone()
    conn.close()
    return row

def add_friend(telegram_id, friend_account_id, friend_name):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO friends (user_id, friend_account_id, friend_name) VALUES (?, ?, ?)",
        (telegram_id, friend_account_id, friend_name)
    )
    conn.commit()
    conn.close()

def get_friends(telegram_id):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute(
        "SELECT friend_account_id, friend_name FROM friends WHERE user_id = ?",
        (telegram_id,)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def update_score(telegram_id, points):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute(
        "UPDATE users SET score = score + ? WHERE telegram_id = ?",
        (points, telegram_id)
    )
    conn.commit()
    conn.close()

def get_leaderboard(limit=10):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute(
        "SELECT telegram_id, username, score FROM users ORDER BY score DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return rows

# ========== KEYBOARDS ==========
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Профиль")
    builder.button(text="📊 Статистика")
    builder.button(text="🎮 Викторина")
    builder.button(text="👥 Друзья")
    builder.button(text="🤝 Сравнить")
    builder.button(text="🏆 Топ")
    builder.button(text="⚔️ Мета")
    builder.button(text="🛠 Сборки")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# ========== COMMAND HANDLERS ==========
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "🎮 <b>Dota2 Stats Bot</b>\n\n"
        "Отправьте ссылку на Steam профиль:\n"
        "• https://steamcommunity.com/id/ваш_ник\n"
        "• https://steamcommunity.com/profiles/76561198...\n"
        "• Или просто SteamID\n\n"
        "Используйте кнопки меню 👇",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text.contains("steamcommunity.com") | F.text.contains("/id/") | (F.text & F.text.regexp(r'^\d+$')))
async def handle_steam_input(message: types.Message):
    text = message.text.strip()
    await message.answer_chat_action("typing")
    
    account_id = await extract_account_id(text)
    
    if account_id:
        player_data = await get_player_data(account_id)
        
        if player_data:
            profile = player_data.get('profile', {})
            name = profile.get('personaname', 'Игрок')
            
            save_user(message.from_user.id, text, account_id, name)
            
            await message.answer(
                f"✅ <b>Профиль привязан!</b>\n"
                f"👤 {name}\n"
                f"🆔 Account ID: {account_id}",
                reply_markup=get_main_keyboard()
            )
        else:
            save_user(message.from_user.id, text, account_id, "")
            await message.answer(
                f"✅ Account ID привязан: {account_id}\n"
                f"<i>Данные профиля временно недоступны</i>",
                reply_markup=get_main_keyboard()
            )
    else:
        await message.answer(
            "❌ Не удалось распознать Steam профиль.\n"
            "Убедитесь что ссылка правильная или попробуйте другой формат.",
            reply_markup=get_main_keyboard()
        )

@dp.message(F.text == "👤 Профиль")
async def profile_cmd(message: types.Message):
    user = get_user(message.from_user.id)
    
    if not user or not user[2]:  # account_id
        await message.answer("❌ Профиль не привязан. Отправьте Steam ссылку.")
        return
    
    account_id = user[2]
    await message.answer_chat_action("typing")
    
    # Получаем данные
    player_data = await get_player_data(account_id)
    matches = await get_matches(account_id, 5)  # Последние 5 игр
    winloss = await get_winloss(account_id)
    
    if not player_data:
        await message.answer("❌ Не удалось получить данные профиля.")
        return
    
    profile = player_data.get('profile', {})
    name = profile.get('personaname', 'Неизвестно')
    avatar = profile.get('avatarfull', '')
    
    # MMR и ранг
    mmr_estimate = player_data.get('mmr_estimate', {}).get('estimate', 0)
    rank_tier = player_data.get('rank_tier', 0)
    
    if mmr_estimate:
        mmr_text = f"{mmr_estimate}"
        rank = get_rank_from_mmr(mmr_estimate)
    elif rank_tier:
        mmr_text = f"~{rank_tier * 150 + 100}"
        rank = get_rank_from_mmr(rank_tier * 150 + 100)
    else:
        mmr_text = "Неизвестно"
        rank = "Uncalibrated"
    
    # Общая статистика
    total_wins = winloss.get('win', 0) if winloss else 0
    total_losses = winloss.get('lose', 0) if winloss else 0
    total_matches = total_wins + total_losses
    total_winrate = (total_wins / total_matches * 100) if total_matches > 0 else 0
    
    # Статистика последних 20 игр
    recent_matches = await get_matches(account_id, 20)
    recent_wins = 0
    if recent_matches:
        for match in recent_matches:
            is_radiant = match.get('player_slot', 0) < 128
            radiant_win = match.get('radiant_win', False)
            if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                recent_wins += 1
    
    recent_winrate = (recent_wins / len(recent_matches) * 100) if recent_matches else 0
    
    # Формируем ответ
    response = f"""
👤 <b>{name}</b>
🎯 <b>MMR:</b> {mmr_text} ({rank})
📊 <b>Общая статистика:</b>
   • Игр: {total_matches}
   • Побед: {total_wins} ({total_winrate:.1f}%)
   • Поражений: {total_losses}

📈 <b>Последние 20 игр:</b>
   • Побед: {recent_wins} ({recent_winrate:.1f}%)

<b>Последние 5 игр:</b>
"""
    
    # Добавляем последние 5 игр
    if matches:
        heroes = await get_heroes_data()
        for i, match in enumerate(matches[:5], 1):
            hero_id = str(match.get('hero_id', 0))
            hero_name = heroes.get(hero_id, f"Герой {hero_id}")
            
            is_radiant = match.get('player_slot', 0) < 128
            radiant_win = match.get('radiant_win', False)
            win = (is_radiant and radiant_win) or (not is_radiant and not radiant_win)
            
            outcome = "✅" if win else "❌"
            k, d, a = match.get('kills', 0), match.get('deaths', 0), match.get('assists', 0)
            
            duration = match.get('duration', 0)
            time_str = f"{duration // 60}:{duration % 60:02d}"
            
            response += f"{i}. {outcome} <b>{hero_name}</b>\n   KDA: {k}/{d}/{a} | ⏱ {time_str}\n"
    else:
        response += "Нет данных о последних играх"
    
    # Кнопки для профиля
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Обновить", callback_data="refresh_profile")
    keyboard.button(text="📊 Подробная статистика", callback_data="detailed_stats")
    keyboard.button(text="🏆 Лучшие герои", callback_data="best_heroes")
    keyboard.adjust(1)
    
    # Отправляем с аватаром если есть
    try:
        if avatar:
            await message.answer_photo(
                photo=avatar,
                caption=response,
                reply_markup=keyboard.as_markup(),
                parse_mode="HTML"
            )
        else:
            await message.answer(response, reply_markup=keyboard.as_markup(), parse_mode="HTML")
    except:
        await message.answer(response, reply_markup=keyboard.as_markup(), parse_mode="HTML")

# ========== QUIZ SYSTEM ==========
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
        "question": "Сколько игроков в команде Dota 2?",
        "options": ["4", "5", "6", "7"],
        "correct": 1
    },
    {
        "question": "Какой максимальный уровень у героя?",
        "options": ["20", "25", "30", "Без ограничений"],
        "correct": 1
    }
]

def get_quiz_state(user_id):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute("SELECT * FROM quiz_state WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        # Создаем новое состояние
        conn = sqlite3.connect('dota2.db')
        c = conn.cursor()
        c.execute(
            "INSERT INTO quiz_state (user_id, current_question, score) VALUES (?, ?, ?)",
            (user_id, 0, 0)
        )
        conn.commit()
        conn.close()
        return (user_id, 0, 0, datetime.now().isoformat())
    
    return row

def update_quiz_state(user_id, question_num, score):
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    c.execute(
        "UPDATE quiz_state SET current_question = ?, score = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
        (question_num, score, user_id)
    )
    conn.commit()
    conn.close()

@dp.message(F.text == "🎮 Викторина")
async def quiz_menu(message: types.Message):
    state = get_quiz_state(message.from_user.id)
    current_question = state[1]
    score = state[2]
    
    keyboard = InlineKeyboardBuilder()
    
    if current_question >= len(QUIZ_QUESTIONS):
        keyboard.button(text="🔄 Начать заново", callback_data="quiz_restart")
        keyboard.button(text="🏆 Топ игроков", callback_data="quiz_leaderboard")
        
        await message.answer(
            f"🎮 <b>Викторина завершена!</b>\n\n"
            f"🏆 Ваш счет: {score}/{len(QUIZ_QUESTIONS)}\n"
            f"📊 Правильных ответов: {(score/len(QUIZ_QUESTIONS)*100):.1f}%\n\n"
            f"Начать заново или посмотреть топ?",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
    else:
        keyboard.button(text="🎯 Продолжить", callback_data="quiz_continue")
        keyboard.button(text="🔄 Начать заново", callback_data="quiz_restart")
        keyboard.button(text="🏆 Топ игроков", callback_data="quiz_leaderboard")
        keyboard.adjust(1)
        
        await message.answer(
            f"🎮 <b>Викторина по Dota 2</b>\n\n"
            f"📊 Прогресс: {current_question}/{len(QUIZ_QUESTIONS)}\n"
            f"🏆 Текущий счет: {score}\n\n"
            f"Продолжить или начать заново?",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "quiz_continue")
async def quiz_continue(callback: types.CallbackQuery):
    state = get_quiz_state(callback.from_user.id)
    question_num = state[1]
    
    if question_num >= len(QUIZ_QUESTIONS):
        await callback.answer("Викторина завершена!")
        return
    
    question = QUIZ_QUESTIONS[question_num]
    
    keyboard = InlineKeyboardBuilder()
    for i, option in enumerate(question["options"]):
        keyboard.button(text=option, callback_data=f"quiz_answer_{i}")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        f"❓ Вопрос {question_num + 1}/{len(QUIZ_QUESTIONS)}\n\n"
        f"{question['question']}",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("quiz_answer_"))
async def quiz_answer(callback: types.CallbackQuery):
    answer_idx = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    state = get_quiz_state(user_id)
    question_num = state[1]
    
    if question_num >= len(QUIZ_QUESTIONS):
        await callback.answer("Викторина завершена!")
        return
    
    question = QUIZ_QUESTIONS[question_num]
    score = state[2]
    
    if answer_idx == question["correct"]:
        score += 10
        response = "✅ <b>Правильно!</b> +10 очков 🎉"
    else:
        response = "❌ <b>Неправильно!</b>"
    
    # Обновляем состояние
    update_quiz_state(user_id, question_num + 1, score)
    update_score(user_id, 10 if answer_idx == question["correct"] else 0)
    
    # Показываем результат и сразу следующий вопрос
    if question_num + 1 < len(QUIZ_QUESTIONS):
        next_question = QUIZ_QUESTIONS[question_num + 1]
        
        keyboard = InlineKeyboardBuilder()
        for i, option in enumerate(next_question["options"]):
            keyboard.button(text=option, callback_data=f"quiz_answer_{i}")
        keyboard.adjust(2)
        
        await callback.message.edit_text(
            f"{response}\n\n"
            f"❓ Вопрос {question_num + 2}/{len(QUIZ_QUESTIONS)}\n\n"
            f"{next_question['question']}",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
    else:
        # Викторина завершена
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔄 Начать заново", callback_data="quiz_restart")
        keyboard.button(text="🏆 Топ игроков", callback_data="quiz_leaderboard")
        keyboard.adjust(1)
        
        await callback.message.edit_text(
            f"{response}\n\n"
            f"🎮 <b>Викторина завершена!</b>\n\n"
            f"🏆 Итоговый счет: {score}/{len(QUIZ_QUESTIONS)*10}\n"
            f"📊 Правильных ответов: {(score/(len(QUIZ_QUESTIONS)*10)*100):.1f}%",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "quiz_restart")
async def quiz_restart(callback: types.CallbackQuery):
    update_quiz_state(callback.from_user.id, 0, 0)
    
    # Показываем первый вопрос
    question = QUIZ_QUESTIONS[0]
    
    keyboard = InlineKeyboardBuilder()
    for i, option in enumerate(question["options"]):
        keyboard.button(text=option, callback_data=f"quiz_answer_{i}")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        f"❓ Вопрос 1/{len(QUIZ_QUESTIONS)}\n\n"
        f"{question['question']}",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "quiz_leaderboard")
async def quiz_leaderboard(callback: types.CallbackQuery):
    leaders = get_leaderboard(10)
    
    response = "🏆 <b>Топ игроков викторины:</b>\n\n"
    for i, (user_id, username, score) in enumerate(leaders, 1):
        name = username if username else f"ID {user_id}"
        response += f"{i}. {name}: {score} очков\n"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🎯 Вернуться к викторине", callback_data="quiz_back")
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "quiz_back")
async def quiz_back(callback: types.CallbackQuery):
    await quiz_menu(callback.message)
    await callback.answer()

# ========== FRIENDS SYSTEM ==========
@dp.message(F.text == "👥 Друзья")
async def friends_menu(message: types.Message):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ Добавить друга", callback_data="add_friend")
    keyboard.button(text="📋 Список друзей", callback_data="list_friends")
    keyboard.adjust(1)
    
    await message.answer(
        "👥 <b>Управление друзьями</b>\n\n"
        "Добавляйте друзей для сравнения статистики!",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "add_friend")
async def add_friend_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🔗 Отправьте Steam ссылку друга:\n"
        "• https://steamcommunity.com/id/ник\n"
        "• https://steamcommunity.com/profiles/...\n"
        "• Или просто SteamID"
    )
    await state.set_state(ProfileStates.waiting_friend)
    await callback.answer()

@dp.message(ProfileStates.waiting_friend)
async def add_friend_process(message: types.Message, state: FSMContext):
    text = message.text.strip()
    account_id = await extract_account_id(text)
    
    if account_id:
        player_data = await get_player_data(account_id)
        if player_data:
            name = player_data.get('profile', {}).get('personaname', 'Друг')
            add_friend(message.from_user.id, account_id, name)
            
            await message.answer(f"✅ Друг {name} добавлен!")
        else:
            await message.answer(f"✅ Account ID друга добавлен: {account_id}")
    else:
        await message.answer("❌ Не удалось распознать профиль друга.")
    
    await state.clear()

@dp.callback_query(F.data == "list_friends")
async def list_friends(callback: types.CallbackQuery):
    friends = get_friends(callback.from_user.id)
    
    if not friends:
        await callback.message.answer("📭 У вас пока нет друзей.")
        return
    
    response = "👥 <b>Ваши друзья:</b>\n\n"
    keyboard = InlineKeyboardBuilder()
    
    for friend_id, friend_name in friends:
        response += f"• {friend_name} (ID: {friend_id})\n"
        keyboard.button(text=f"🤝 Сравнить с {friend_name}", callback_data=f"compare_{friend_id}")
    
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

# ========== COMPARE SYSTEM ==========
@dp.message(F.text == "🤝 Сравнить")
async def compare_menu(message: types.Message):
    friends = get_friends(message.from_user.id)
    
    if not friends:
        await message.answer(
            "🤝 <b>Сравнение статистики</b>\n\n"
            "У вас пока нет друзей. Добавьте друга через меню '👥 Друзья'",
            parse_mode="HTML"
        )
        return
    
    keyboard = InlineKeyboardBuilder()
    for friend_id, friend_name in friends:
        keyboard.button(text=f"🤝 {friend_name}", callback_data=f"compare_{friend_id}")
    keyboard.button(text="➕ Добавить еще друга", callback_data="add_friend")
    keyboard.adjust(1)
    
    await message.answer(
        "🤝 <b>Выберите друга для сравнения:</b>",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("compare_"))
async def compare_friend(callback: types.CallbackQuery):
    friend_id = int(callback.data.split("_")[1])
    
    # Получаем данные текущего пользователя
    user = get_user(callback.from_user.id)
    if not user or not user[2]:
        await callback.answer("❌ Сначала привяжите свой профиль!")
        return
    
    user_account = user[2]
    friend_account = friend_id
    
    await callback.answer("⏳ Сравниваю статистику...")
    
    # Получаем данные обоих игроков
    user_data = await get_player_data(user_account)
    friend_data = await get_player_data(friend_account)
    
    user_winloss = await get_winloss(user_account)
    friend_winloss = await get_winloss(friend_account)
    
    if not user_data or not friend_data:
        await callback.message.answer("❌ Не удалось получить данные для сравнения.")
        return
    
    # MMR
    user_mmr = user_data.get('mmr_estimate', {}).get('estimate', 0)
    friend_mmr = friend_data.get('mmr_estimate', {}).get('estimate', 0)
    
    user_rank = get_rank_from_mmr(user_mmr)
    friend_rank = get_rank_from_mmr(friend_mmr)
    
    # Winrate
    user_wins = user_winloss.get('win', 0) if user_winloss else 0
    user_losses = user_winloss.get('lose', 0) if user_winloss else 0
    user_total = user_wins + user_losses
    user_winrate = (user_wins / user_total * 100) if user_total > 0 else 0
    
    friend_wins = friend_winloss.get('win', 0) if friend_winloss else 0
    friend_losses = friend_winloss.get('lose', 0) if friend_winloss else 0
    friend_total = friend_wins + friend_losses
    friend_winrate = (friend_wins / friend_total * 100) if friend_total > 0 else 0
    
    # Определяем победителя
    mmr_winner = "Вы" if user_mmr > friend_mmr else "Друг" if friend_mmr > user_mmr else "Ничья"
    wr_winner = "Вы" if user_winrate > friend_winrate else "Друг" if friend_winrate > user_winrate else "Ничья"
    
    response = f"""
🤝 <b>Сравнение статистики</b>

👤 <b>Вы:</b>
• MMR: {user_mmr} ({user_rank})
• Winrate: {user_winrate:.1f}% ({user_wins}W-{user_losses}L)

👤 <b>Друг:</b>
• MMR: {friend_mmr} ({friend_rank})
• Winrate: {friend_winrate:.1f}% ({friend_wins}W-{friend_losses}L)

🏆 <b>Итог:</b>
• По MMR побеждает: {mmr_winner}
• По винрейту побеждает: {wr_winner}
"""
    
    await callback.message.answer(response, parse_mode="HTML")

# ========== META HEROES ==========
@dp.message(F.text == "⚔️ Мета")
async def meta_cmd(message: types.Message):
    await message.answer_chat_action("typing")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Получаем мету для Divine/Immortal
            async with session.get(
                "https://api.opendota.com/api/heroStats",
                timeout=10
            ) as r:
                if r.status == 200:
                    hero
