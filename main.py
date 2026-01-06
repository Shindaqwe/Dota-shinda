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
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
import sqlite3
from collections import Counter
import random
# В начало main.py после других импортов добавьте:
from advanced_stats import AdvancedStats
from daily_quests_manager import DailyQuestsManager
from tournament_manager import TournamentManager
from game_mini_apps import MiniGamesManager
from achievements_system import AchievementsSystem
# Добавьте эти импорты если их нет:
from aiogram import Router
from aiogram.types import CallbackQuery



# Инициализация менеджеров
adv_stats = AdvancedStats()
quests_manager = DailyQuestsManager()
tournament_manager = TournamentManager()
games_manager = MiniGamesManager()
achievements_system = AchievementsSystem()
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

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('dota2.db')
    c = conn.cursor()
    
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
    searching_hero = State()

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
                logger.warning("⚠️ STEAM_API_KEY не задан")
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

# ========== ОПРЕДЕЛЕНИЕ РОЛИ ==========
def determine_main_role(matches):
    """Определяет основную роль игрока по последним матчам"""
    if not matches:
        return "Универсал"
    
    role_counter = Counter()
    
    for match in matches[:20]:
        lane_role = match.get('lane_role', 0)
        
        if lane_role == 1:
            role_counter["Керри"] += 1
        elif lane_role == 2:
            role_counter["Мидер"] += 1
        elif lane_role == 3:
            role_counter["Оффлейнер"] += 1
        elif lane_role in [4, 5]:
            role_counter["Саппорт"] += 1
    
    if role_counter:
        main_role, count = role_counter.most_common(1)[0]
        total_games = sum(role_counter.values())
        
        if count / total_games >= 0.4:
            return main_role
    
    return "Универсал"

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
    builder.button(text="⚔️ Мета")
    builder.button(text="🛠 Сборки")
    builder.button(text="📈 Анализ")
    builder.button(text="🎯 Квесты")
    builder.button(text="🏆 Турниры")
    builder.button(text="🎮 Игры")
    builder.button(text="🏅 Достижения")
    builder.button(text="❤️ Поддержка")
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

@dp.message(F.text.contains("steamcommunity.com") | F.text.regexp(r'^\d+$') | F.text.contains("/id/"))
async def handle_steam_input(message: types.Message):
    text = message.text.strip()
    logger.info(f"Получена Steam ссылка: {text}")
    
    await message.answer_chat_action("typing")
    
    account_id = await extract_account_id(text)
    logger.info(f"Извлечен Account ID: {account_id}")
    
    if account_id:
        player_data = await get_player_data(account_id)
        
        if player_data:
            profile = player_data.get('profile', {})
            name = profile.get('personaname', 'Игрок')
            
            save_user(message.from_user.id, text, account_id, name)
            
            await message.answer(
                f"✅ <b>Профиль привязан!</b>\n\n"
                f"👤 <b>{name}</b>\n"
                f"🆔 Account ID: <code>{account_id}</code>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        else:
            save_user(message.from_user.id, text, account_id, "")
            await message.answer(
                f"✅ Account ID привязан: <code>{account_id}</code>\n\n"
                f"<i>Не удалось получить данные профиля. Возможно профиль скрыт.</i>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
    else:
        await message.answer(
            "❌ <b>Не удалось распознать Steam профиль.</b>\n\n"
            "Возможные причины:\n"
            "1. Неверный формат ссылки\n"
            "2. STEAM_API_KEY не настроен\n"
            "3. Профиль скрыт\n\n"
            "<b>Добавьте STEAM_API_KEY в Render Environment Variables</b>",
            parse_mode="HTML"
        )

@dp.message(F.text == "👤 Профиль")
async def profile_cmd(message: types.Message):
    user = get_user(message.from_user.id)
    
    if not user or not user[2]:
        await message.answer("❌ Профиль не привязан. Отправьте Steam ссылку.")
        return
    
    account_id = user[2]
    await message.answer_chat_action("typing")
    
    # Получаем данные
    player_data = await get_player_data(account_id)
    matches = await get_matches(account_id, 20)
    
    if not player_data:
        await message.answer("❌ Не удалось получить данные профиля.")
        return
    
    profile = player_data.get('profile', {})
    name = profile.get('personaname', 'Неизвестно')
    avatar = profile.get('avatarfull', '')
    
    # MMR
    mmr_estimate = player_data.get('mmr_estimate', {}).get('estimate', 0)
    rank_tier = player_data.get('rank_tier', 0)
    
    if mmr_estimate:
        mmr_text = f"~{mmr_estimate}"
    elif rank_tier:
        mmr_text = f"~{rank_tier * 150 + 100}"
    else:
        mmr_text = "Неизвестно"
    
    # Статистика последних 20 игр
    recent_wins = 0
    if matches:
        for match in matches:
            is_radiant = match.get('player_slot', 0) < 128
            radiant_win = match.get('radiant_win', False)
            if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                recent_wins += 1
    
    recent_winrate = (recent_wins / len(matches) * 100) if matches else 0
    
    # Определяем роль
    main_role = determine_main_role(matches)
    
    # Формируем ответ в стиле старого интерфейса
    response = f"""
👤 <b>{name}</b> 
🎯 MMR: {mmr_text}

📊 <b>Статистика за последние {len(matches) if matches else 0} игр:</b>
🔥 Винрейт: {recent_winrate:.1f}% ({recent_wins}W - {len(matches)-recent_wins if matches else 0}L)
🎭 Роль: {main_role}

<b>Последние 5 игр детально:</b>
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
            
            outcome = "Победа ✅" if win else "Поражение ❌"
            k, d, a = match.get('kills', 0), match.get('deaths', 0), match.get('assists', 0)
            
            duration = match.get('duration', 0)
            time_str = f"{duration // 60}:{duration % 60:02d}"
            
            response += f"\n{outcome} | {hero_name}"
            response += f"\n📊 KDA: {k}/{d}/{a} | 🕒 {time_str}"
            if i < 5:
                response += "\n----------------------------"
    else:
        response += "\nНет данных о последних играх"
    
    # Кнопки для профиля
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Обновить", callback_data="refresh_profile")
    keyboard.button(text="📊 Подробная статистика", callback_data="detailed_stats")
    keyboard.button(text="🏆 Лучшие герои", callback_data="best_heroes")
    keyboard.adjust(1)
    
    # Отправляем сообщение
    try:
        if avatar:
            await message.answer_photo(
                photo=avatar,
                caption=response,
                reply_markup=keyboard.as_markup(),
                parse_mode="HTML"
            )
        else:
            await message.answer(
                response,
                reply_markup=keyboard.as_markup(),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Ошибка отправки профиля: {e}")
        await message.answer(
            response,
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )

@dp.message(F.text == "📊 Статистика")
async def stats_cmd(message: types.Message):
    user = get_user(message.from_user.id)
    
    if not user or not user[2]:
        await message.answer("❌ Сначала привяжите профиль.")
        return
    
    account_id = user[2]
    await message.answer_chat_action("typing")
    
    # Получаем общую статистику
    winloss = await get_winloss(account_id)
    matches = await get_matches(account_id, 50)
    
    if not winloss:
        await message.answer("❌ Не удалось получить статистику.")
        return
    
    total_wins = winloss.get('win', 0)
    total_losses = winloss.get('lose', 0)
    total_matches = total_wins + total_losses
    total_winrate = (total_wins / total_matches * 100) if total_matches > 0 else 0
    
    # Статистика последних игр
    recent_stats = {'kills': 0, 'deaths': 0, 'assists': 0, 'wins': 0}
    if matches:
        for match in matches:
            recent_stats['kills'] += match.get('kills', 0)
            recent_stats['deaths'] += match.get('deaths', 0)
            recent_stats['assists'] += match.get('assists', 0)
            
            is_radiant = match.get('player_slot', 0) < 128
            radiant_win = match.get('radiant_win', False)
            if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                recent_stats['wins'] += 1
    
    avg_kills = recent_stats['kills'] / len(matches) if matches else 0
    avg_deaths = recent_stats['deaths'] / len(matches) if matches else 0
    avg_assists = recent_stats['assists'] / len(matches) if matches else 0
    recent_winrate = (recent_stats['wins'] / len(matches) * 100) if matches else 0
    
    kda = (avg_kills + avg_assists) / avg_deaths if avg_deaths > 0 else avg_kills + avg_assists
    
    response = f"""
📊 <b>Статистика игрока</b>

🎯 <b>Общая статистика:</b>
• Всего игр: {total_matches}
• Побед: {total_wins} ({total_winrate:.1f}%)
• Поражений: {total_losses}

📈 <b>Последние {len(matches) if matches else 0} игр:</b>
• Winrate: {recent_winrate:.1f}%
• Средний KDA: {avg_kills:.1f}/{avg_deaths:.1f}/{avg_assists:.1f}
• KDA Ratio: {kda:.2f}

⚔️ <b>Детализация:</b>
• Убийств/игра: {avg_kills:.1f}
• Смертей/игра: {avg_deaths:.1f}
• Помощей/игра: {avg_assists:.1f}
"""
    
    await message.answer(response, parse_mode="HTML")

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
    keyboard.button(text="🤝 Сравнить с другом", callback_data="compare_menu")
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
    
    for friend_id, friend_name in friends:
        response += f"• {friend_name} (ID: {friend_id})\n"
    
    await callback.message.edit_text(
        response,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "compare_menu")
async def compare_menu_callback(callback: types.CallbackQuery):
    friends = get_friends(callback.from_user.id)
    
    if not friends:
        await callback.message.answer("📭 У вас пока нет друзей для сравнения.")
        return
    
    keyboard = InlineKeyboardBuilder()
    for friend_id, friend_name in friends:
        keyboard.button(text=f"🤝 {friend_name}", callback_data=f"compare_{friend_id}")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        "🤝 <b>Выберите друга для сравнения:</b>",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("compare_"))
async def compare_friend(callback: types.CallbackQuery):
    friend_id = int(callback.data.split("_")[1])
    
    user = get_user(callback.from_user.id)
    if not user or not user[2]:
        await callback.answer("❌ Сначала привяжите свой профиль!")
        return
    
    user_account = user[2]
    friend_account = friend_id
    
    await callback.answer("⏳ Сравниваю статистику...")
    
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
• MMR: {user_mmr}
• Winrate: {user_winrate:.1f}% ({user_wins}W-{user_losses}L)

👤 <b>Друг:</b>
• MMR: {friend_mmr}
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
            async with session.get(
                "https://api.opendota.com/api/heroStats",
                timeout=15
            ) as r:
                if r.status == 200:
                    heroes_data = await r.json()
                    
                    meta_heroes = []
                    
                    for hero in heroes_data:
                        divine_pick = hero.get('8_pick', 0)
                        divine_win = hero.get('8_win', 0)
                        
                        if divine_pick > 50:
                            winrate = (divine_win / divine_pick * 100) if divine_pick > 0 else 0
                            if winrate > 52.0:
                                meta_heroes.append({
                                    'name': hero.get('localized_name', 'Unknown'),
                                    'winrate': winrate,
                                    'pick_rate': divine_pick,
                                    'hero_id': hero.get('id', 0)
                                })
                    
                    meta_heroes.sort(key=lambda x: x['winrate'], reverse=True)
                    
                    if meta_heroes:
                        response = "⚔️ <b>Текущая мета (Divine/Immortal):</b>\n\n"
                        
                        for i, hero in enumerate(meta_heroes[:15], 1):
                            response += f"{i}. <b>{hero['name']}</b>\n"
                            response += f"   📊 Winrate: <code>{hero['winrate']:.1f}%</code>\n"
                            response += f"   🎯 Пиков: {hero['pick_rate']}\n\n"
                        
                        response += "<i>Данные обновляются с OpenDota API</i>"
                    else:
                        response = "📭 Не удалось получить данные меты. Попробуйте позже."
                    
                    await message.answer(response, parse_mode="HTML")
                else:
                    await message.answer("❌ Ошибка API. Попробуйте позже.")
                    
    except Exception as e:
        logger.error(f"Meta error: {e}")
        await message.answer("❌ Ошибка при получении меты.")

# ========== HERO BUILDS ==========
@dp.message(F.text == "🛠 Сборки")
async def builds_menu(message: types.Message):
    keyboard = InlineKeyboardBuilder()
    
    hero_roles = [
        ("⚔️ Керри", "carry"),
        ("🎯 Мидер", "mid"),
        ("🛡️ Оффлейнер", "offlane"),
        ("💫 Саппорт", "support"),
        ("🔮 Хард саппорт", "hard_support"),
        ("🔍 Поиск героя", "search")
    ]
    
    for role_name, role_id in hero_roles:
        keyboard.button(text=role_name, callback_data=f"builds_{role_id}")
    
    keyboard.adjust(2)
    
    await message.answer(
        "🛠 <b>Сборки предметов и способностей</b>\n\n"
        "Выберите категорию или найдите героя:",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "builds_search")
async def search_hero(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🔍 <b>Поиск героя</b>\n\n"
        "Введите имя героя (например: Pudge, Invoker, Crystal Maiden):",
        parse_mode="HTML"
    )
    await state.set_state(ProfileStates.searching_hero)
    await callback.answer()

@dp.message(ProfileStates.searching_hero)
async def process_hero_search(message: types.Message, state: FSMContext):
    search_term = message.text.strip().lower()
    
    with open('hero_names.json', 'r', encoding='utf-8') as f:
        heroes = json.load(f)
    
    found_heroes = []
    for hero_id, hero_name in heroes.items():
        if search_term in hero_name.lower():
            found_heroes.append((int(hero_id), hero_name))
    
    if found_heroes:
        keyboard = InlineKeyboardBuilder()
        for hero_id, hero_name in found_heroes[:10]:
            keyboard.button(text=hero_name, callback_data=f"hero_build_{hero_id}")
        keyboard.button(text="⬅️ Назад", callback_data="builds_back")
        keyboard.adjust(1)
        
        await message.answer(
            f"🔍 <b>Найдено героев:</b> {len(found_heroes)}\n\n"
            f"Выберите героя:",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "❌ Герой не найден. Попробуйте другое имя или используйте категории.",
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()

@dp.callback_query(F.data.startswith("builds_"))
async def builds_by_role(callback: types.CallbackQuery):
    role_id = callback.data.split("_")[1]
    
    if role_id == "search":
        await search_hero(callback, FSMContext)
        return
    
    # Загружаем данные из hero_builds.json
    try:
        with open('hero_builds.json', 'r', encoding='utf-8') as f:
            heroes_builds = json.load(f)
    except FileNotFoundError:
        await callback.message.answer("❌ Файл сборок не найден.")
        return
    
    role_names = {
        "carry": "Керри",
        "mid": "Мидер",
        "offlane": "Оффлейнер",
        "support": "Саппорт",
        "hard_support": "Хард саппорт"
    }
    
    role_name = role_names.get(role_id, role_id)
    
    # Ищем героев с этой ролью
    heroes = []
    for hero_id, hero_data in heroes_builds.items():
        if role_name in hero_data.get('primary_roles', []) or role_name in hero_data.get('secondary_roles', []):
            heroes.append((int(hero_id), hero_data.get('name', f"Герой {hero_id}")))
    
    if not heroes:
        await callback.answer("❌ Нет героев для этой роли")
        return
    
    keyboard = InlineKeyboardBuilder()
    for hero_id, hero_name in heroes:
        keyboard.button(text=hero_name, callback_data=f"hero_build_{hero_id}")
    
    keyboard.button(text="⬅️ Назад", callback_data="builds_back")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        f"🛠 <b>Герои ({role_name}):</b>\n\n"
        f"Выберите героя для просмотра сборки:",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

    @dp.callback_query(F.data.startswith("hero_build_"))
async def hero_build_display(callback: types.CallbackQuery):
    hero_id = callback.data.split("_")[2]
    
    # Загружаем данные из hero_builds.json
    try:
        with open('hero_builds.json', 'r', encoding='utf-8') as f:
            heroes_builds = json.load(f)
    except FileNotFoundError:
        await callback.message.answer("❌ Файл сборок не найден.")
        return
    
    hero_data = heroes_builds.get(hero_id)
    
    if not hero_data:
        await callback.message.answer(f"❌ Сборки для героя с ID {hero_id} не найдены.")
        return
    
    hero_name = hero_data.get('name', f"Герой {hero_id}")
    
    # Получаем первую роль из списка
    roles = hero_data.get('primary_roles', [])
    if not roles:
        roles = hero_data.get('secondary_roles', [])
    
    if not roles:
        await callback.message.answer(f"❌ Для героя {hero_name} не указаны роли.")
        return
    
    role = roles[0]
    builds = hero_data.get('builds', {})
    
    if role not in builds:
        # Пытаемся найти любую сборку
        if builds:
            role = list(builds.keys())[0]
        else:
            await callback.message.answer(f"❌ Для героя {hero_name} нет сборок.")
            return
    
    build = builds[role]
    
    response = f"""
🛠 <b>{hero_name} ({role})</b>

🎒 <b>Предметы:</b>
"""
    
    for item in build.get("items", []):
        response += f"• {item}\n"
    
    response += f"""
⚡ <b>Способности:</b>
{build.get('skills', 'Не указано')}

📈 <b>Прокачка:</b>
{build.get('skill_build', 'Не указано')}

🌟 <b>Таланты:</b>
{build.get('talents', 'Не указано')}

🎮 <b>Стиль игры:</b>
{build.get('playstyle', 'Не указано')}

<i>Сборка основана на текущей мете</i>
"""
    
    # Кнопки для других ролей если есть
    keyboard = InlineKeyboardBuilder()
    other_roles = [r for r in builds.keys() if r != role]
    for other_role in other_roles:
        keyboard.button(text=f"🎯 {other_role}", callback_data=f"hero_role_{hero_id}_{other_role}")
    
    keyboard.button(text="⬅️ Назад", callback_data="builds_back")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer() 


@dp.callback_query(F.data.startswith("hero_role_"))
async def hero_role_switch(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    hero_id = parts[2]
    role = parts[3]
    
    # Загружаем данные из hero_builds.json
    try:
        with open('hero_builds.json', 'r', encoding='utf-8') as f:
            heroes_builds = json.load(f)
    except FileNotFoundError:
        await callback.message.answer("❌ Файл сборок не найден.")
        return
    
    hero_data = heroes_builds.get(hero_id)
    if not hero_data:
        await callback.message.answer("❌ Герой не найден.")
        return
    
    hero_name = hero_data.get('name', f"Герой {hero_id}")
    builds = hero_data.get('builds', {})
    
    if role not in builds:
        await callback.message.answer(f"❌ Для героя {hero_name} нет сборки для роли {role}.")
        return
    
    build = builds[role]
    
    response = f"""
🛠 <b>{hero_name} ({role})</b>

🎒 <b>Предметы:</b>
"""
    
    for item in build.get("items", []):
        response += f"• {item}\n"
    
    response += f"""
⚡ <b>Способности:</b>
{build.get('skills', 'Не указано')}

📈 <b>Прокачка:</b>
{build.get('skill_build', 'Не указано')}

🌟 <b>Таланты:</b>
{build.get('talents', 'Не указано')}

🎮 <b>Стиль игры:</b>
{build.get('playstyle', 'Не указано')}

<i>Сборка основана на текущей мете</i>
"""
    
    keyboard = InlineKeyboardBuilder()
    other_roles = [r for r in builds.keys() if r != role]
    for other_role in other_roles:
        keyboard.button(text=f"🎯 {other_role}", callback_data=f"hero_role_{hero_id}_{other_role}")
    
    keyboard.button(text="⬅️ Назад", callback_data=f"hero_build_{hero_id}")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()
    
@dp.callback_query(F.data == "builds_back")
async def builds_back(callback: types.CallbackQuery):
    await builds_menu(callback.message)
    await callback.answer()

# ========== SUPPORT ==========
@dp.message(F.text == "❤️ Поддержка")
async def support_cmd(message: types.Message):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="💸 Донат", url="https://www.donationalerts.com/r/shindaqwe")
    keyboard.button(text="🛠 Тех поддержка", url="https://t.me/DotaShindaHelper_bot")
    keyboard.adjust(1)
    
    await message.answer(
        "❤️ <b>Поддержка проекта</b>\n\n"
        "Если вам нравится бот, вы можете поддержать его развитие!\n\n"
        "💸 <b>Донат</b> - финансовая поддержка\n"
        "🛠 <b>Тех поддержка</b> - помощь с ботом",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

# ========== BACK BUTTONS ==========
@dp.callback_query(F.data == "profile_back")
async def profile_back(callback: types.CallbackQuery):
    await profile_cmd(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "refresh_profile")
async def refresh_profile(callback: types.CallbackQuery):
    await callback.answer("🔄 Обновляю...")
    await profile_cmd(callback.message)

@dp.callback_query(F.data == "detailed_stats")
async def detailed_stats(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user[2]:
        await callback.answer("❌ Сначала привяжите профиль!")
        return
    
    account_id = user[2]
    await callback.answer("⏳ Получаю подробную статистику...")
    
    winloss = await get_winloss(account_id)
    matches = await get_matches(account_id, 50)
    
    if not winloss:
        await callback.message.answer("❌ Не удалось получить данные.")
        return
    
    total_wins = winloss.get('win', 0)
    total_losses = winloss.get('lose', 0)
    total_matches = total_wins + total_losses
    
    if matches:
        recent_stats = {'kills': 0, 'deaths': 0, 'assists': 0, 'wins': 0}
        
        for match in matches:
            recent_stats['kills'] += match.get('kills', 0)
            recent_stats['deaths'] += match.get('deaths', 0)
            recent_stats['assists'] += match.get('assists', 0)
            
            is_radiant = match.get('player_slot', 0) < 128
            radiant_win = match.get('radiant_win', False)
            if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                recent_stats['wins'] += 1
        
        avg_kills = recent_stats['kills'] / len(matches)
        avg_deaths = recent_stats['deaths'] / len(matches)
        avg_assists = recent_stats['assists'] / len(matches)
        recent_winrate = (recent_stats['wins'] / len(matches) * 100)
        
        kda = (avg_kills + avg_assists) / avg_deaths if avg_deaths > 0 else avg_kills + avg_assists
    else:
        avg_kills = avg_deaths = avg_assists = kda = 0
        recent_winrate = 0
    
    response = f"""
📊 <b>Подробная статистика</b>

📈 <b>Общая:</b>
• Игр: {total_matches}
• Побед: {total_wins}
• Поражений: {total_losses}

🎯 <b>Последние {len(matches) if matches else 0} игр:</b>
• Winrate: {recent_winrate:.1f}%
• Средний KDA: {avg_kills:.1f}/{avg_deaths:.1f}/{avg_assists:.1f} ({kda:.2f} ratio)

⚔️ <b>Статистика за игру:</b>
• Убийств/игра: {avg_kills:.1f}
• Смертей/игра: {avg_deaths:.1f}
• Помощей/игра: {avg_assists:.1f}
"""
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⬅️ Назад", callback_data="profile_back")
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "best_heroes")
async def best_heroes(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user[2]:
        await callback.answer("❌ Сначала привяжите профиль!")
        return
    
    account_id = user[2]
    await callback.answer("⏳ Анализирую героев...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.opendota.com/api/players/{account_id}/heroes",
                timeout=10
            ) as r:
                if r.status == 200:
                    heroes_data = await r.json()
                    
                    valid_heroes = []
                    for hero in heroes_data:
                        games = hero.get('games', 0)
                        wins = hero.get('win', 0)
                        
                        if games >= 3:
                            winrate = (wins / games * 100) if games > 0 else 0
                            valid_heroes.append({
                                'hero_id': hero.get('hero_id', 0),
                                'games': games,
                                'wins': wins,
                                'winrate': winrate
                            })
                    
                    valid_heroes.sort(key=lambda x: x['winrate'], reverse=True)
                    
                    heroes = await get_heroes_data()
                    
                    response = "🏆 <b>Ваши лучшие герои:</b>\n\n"
                    
                    for i, hero in enumerate(valid_heroes[:10], 1):
                        hero_name = heroes.get(str(hero['hero_id']), f"Герой {hero['hero_id']}")
                        response += f"{i}. <b>{hero_name}</b>\n"
                        response += f"   📊 {hero['winrate']:.1f}% ({hero['wins']}W-{hero['games']-hero['wins']}L)\n"
                        response += f"   🎮 Игр: {hero['games']}\n\n"
                    
                    if not valid_heroes:
                        response = "📭 Недостаточно данных по героям. Сыграйте больше игр!"
                    
                    keyboard = InlineKeyboardBuilder()
                    keyboard.button(text="⬅️ Назад в профиль", callback_data="profile_back")
                    
                    await callback.message.edit_text(
                        response,
                        reply_markup=keyboard.as_markup(),
                        parse_mode="HTML"
                    )
                else:
                    await callback.message.answer("❌ Не удалось получить данные по героям.")
    
    except Exception as e:
        logger.error(f"Best heroes error: {e}")
        await callback.message.answer("❌ Ошибка при анализе героев.")

# ========== FLASK SERVER FOR RENDER ==========
from flask import Flask, jsonify
from threading import Thread
import waitress

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Dota2 Bot is running"

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/ping')
def ping():
    return "pong", 200

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    waitress.serve(app, host='0.0.0.0', port=port, threads=1)

# ========== START BOT ==========
async def main():
    logger.info("🚀 Starting Dota2 Bot...")
    
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"✅ Flask server started on port {os.environ.get('PORT', 10000)}")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

@dp.message(F.text == "📈 Анализ")
async def analysis_menu(message: types.Message):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📅 Недельная статистика", callback_data="weekly_stats")
    keyboard.button(text="🔍 Слабые стороны", callback_data="weakness_analysis")
    keyboard.button(text="🔮 Прогноз матча", callback_data="match_prediction")
    keyboard.button(text="🎯 Контрпики", callback_data="counterpicks")
    keyboard.adjust(1)
    
    await message.answer(
        "📈 <b>Анализ и улучшения</b>\n\n"
        "Выберите тип анализа:",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

# Недельная статистика
@dp.callback_query(F.data == "weekly_stats")
async def weekly_stats_handler(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user[2]:
        await callback.answer("❌ Сначала привяжите профиль!")
        return
    
    await callback.answer("⏳ Анализирую недельную статистику...")
    
    stats = await adv_stats.get_weekly_stats(user[2])
    
    if not stats:
        await callback.message.answer("❌ Не удалось получить данные за неделю.")
        return
    
    # Форматируем ответ
    response = f"""
📅 <b>Ваша неделя в Dota 2</b>

🎮 <b>Общая статистика:</b>
• Игр: {stats['total_games']}
• Побед: {stats['wins']}
• Поражений: {stats['losses']}
• Винрейт: {stats['wins']/stats['total_games']*100:.1f}%

⚔️ <b>Лучшие герои:</b>
"""
    
    # Находим лучшего героя
    best_hero = None
    best_winrate = 0
    
    with open('hero_names.json', 'r', encoding='utf-8') as f:
        hero_names = json.load(f)
    
    for hero_id, hero_data in stats['heroes'].items():
        if hero_data['games'] >= 3:
            winrate = hero_data['wins'] / hero_data['games'] * 100
            if winrate > best_winrate:
                best_winrate = winrate
                hero_name = hero_names.get(hero_id, f"Герой {hero_id}")
                best_hero = f"{hero_name} ({winrate:.1f}%)"
    
    if best_hero:
        response += f"• {best_hero}\n"
    
    # Самый частый противник (упрощенно)
    response += f"\n📊 <b>Средний KDA:</b> {stats['kills']/stats['total_games']:.1f}/{stats['deaths']/stats['total_games']:.1f}/{stats['assists']/stats['total_games']:.1f}"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⬅️ Назад", callback_data="analysis_back")
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(F.text == "🎯 Квесты")
async def daily_quests_menu(message: types.Message):
    user_id = message.from_user.id
    quests = quests_manager.get_user_quests(user_id)
    
    if not quests:
        # Генерируем новые квесты
        quests_manager.generate_daily_quests(user_id)
        quests = quests_manager.get_user_quests(user_id)
    
    response = "🎯 <b>Ежедневные задания</b>\n\n"
    
    for i, quest in enumerate(quests, 1):
        completed = quest['progress'] >= quest['target']
        status = "✅" if completed else "🔄"
        
        response += f"{i}. {status} <b>{quest['title']}</b>\n"
        response += f"   {quest['description']}\n"
        response += f"   Прогресс: {quest['progress']}/{quest['target']}\n"
        response += f"   Награда: {quest['reward']} очков\n\n"
    
    response += "<i>Задания обновляются каждый день в 00:00</i>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 Обновить", callback_data="refresh_quests")
    keyboard.button(text="🏆 Мои награды", callback_data="my_rewards")
    keyboard.adjust(1)
    
    await message.answer(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

@dp.message(F.text == "🏆 Турниры")
async def tournaments_menu(message: types.Message):
    tournaments = tournament_manager.get_active_tournaments()
    
    if not tournaments:
        response = "🏆 <b>Текущие турниры</b>\n\n"
        response += "На данный момент нет активных турниров.\n"
        response += "Создайте свой или подождите начала новых!"
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="➕ Создать турнир", callback_data="create_tournament")
        keyboard.adjust(1)
    else:
        response = "🏆 <b>Активные турниры</b>\n\n"
        
        for tournament in tournaments[:5]:
            response += f"🎮 <b>{tournament['name']}</b>\n"
            response += f"   👥 {tournament['current_participants']}/{tournament['max_participants']}\n"
            response += f"   🏆 {tournament['prize']}\n"
            response += f"   📅 Старт: {tournament['start_date']}\n"
            response += f"   📊 Статус: {tournament['status']}\n\n"
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="➕ Создать турнир", callback_data="create_tournament")
        keyboard.button(text="📋 Мои турниры", callback_data="my_tournaments")
        keyboard.button(text="🏆 Таблица лидеров", callback_data="tournament_leaderboard")
        keyboard.adjust(1)
    
    await message.answer(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
# Добавьте эти функции:

@dp.message(F.text == "🎮 Игры")
async def games_menu(message: types.Message):
    await games_manager.show_menu(message)

@dp.message(F.text == "🏅 Достижения")
async def achievements_menu(message: types.Message):
    user_achievements = achievements_system.get_user_achievements(message.from_user.id)
    # Отображение достижений

@dp.callback_query(F.data == "mini_game_tic_tac_toe")
async def mini_game_tic_tac_toe_handler(callback: types.CallbackQuery):
    # Пока что просто сообщение
    await callback.message.answer("🎮 Крестики-нолики будут добавлены в следующем обновлении!")
    await callback.answer()

@dp.callback_query(F.data == "mini_game_random_hero")
async def mini_game_random_hero_handler(callback: types.CallbackQuery):
    # Случайный герой
    with open('hero_names.json', 'r', encoding='utf-8') as f:
        heroes = json.load(f)
    
    hero_id, hero_name = random.choice(list(heroes.items()))
    await callback.message.answer(f"🎲 Ваш случайный герой: <b>{hero_name}</b> (ID: {hero_id})", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery):
    await callback.message.answer("Возвращаемся в главное меню.", reply_markup=get_main_keyboard())
    await callback.answer()

@dp.message(F.text == "🏅 Достижения")
async def achievements_menu(message: types.Message):
    user_id = message.from_user.id
    achievements_data = achievements_system.get_user_achievements(user_id)
    
    if not achievements_data:
        await message.answer("❌ Не удалось загрузить достижения.")
        return
    
    achievements = achievements_data.get('achievements', [])
    total_unlocked = achievements_data.get('total_unlocked', 0)
    total_achievements = achievements_data.get('total_achievements', 0)
    completion_percent = achievements_data.get('completion_percent', 0)
    total_score = achievements_data.get('total_score', 0)
    
    response = f"""
🏅 <b>Ваши достижения</b>

📊 Прогресс: {total_unlocked}/{total_achievements} ({completion_percent:.1f}%)
🏆 Очки: {total_score}

"""
    
    for ach in achievements:
        status = "✅" if ach['unlocked'] else "⏳"
        response += f"{status} {ach.get('icon', '🏅')} <b>{ach.get('title', 'Без названия')}</b>\n"
        response += f"   {ach.get('description', '')}\n"
        if not ach['unlocked'] and ach.get('target', 0) > 0:
            response += f"   Прогресс: {ach.get('progress', 0)}/{ach.get('target', 0)}\n"
        response += f"   Награда: {ach.get('reward', 0)} очков\n\n"
    
    await message.answer(response, parse_mode="HTML")

@dp.callback_query(F.data == "mini_game_tic_tac_toe")
async def mini_game_tic_tac_toe_handler(callback: types.CallbackQuery):
    # Пока что просто сообщение
    await callback.message.answer("🎮 Крестики-нолики будут добавлены в следующем обновлении!")
    await callback.answer()

@dp.callback_query(F.data == "mini_game_random_hero")
async def mini_game_random_hero_handler(callback: types.CallbackQuery):
    # Случайный герой
    with open('hero_names.json', 'r', encoding='utf-8') as f:
        heroes = json.load(f)
    
    hero_id, hero_name = random.choice(list(heroes.items()))
    await callback.message.answer(f"🎲 Ваш случайный герой: <b>{hero_name}</b> (ID: {hero_id})", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery):
    await callback.message.answer("Возвращаемся в главное меню.", reply_markup=get_main_keyboard())
    await callback.answer()
