import sqlite3
import json
from datetime import datetime, timedelta
import random
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class DailyQuestsManager:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
        self.init_quests_db()
    
    def init_quests_db(self):
        """Инициализация таблицы квестов"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                quest_id INTEGER,
                progress INTEGER DEFAULT 0,
                completed BOOLEAN DEFAULT 0,
                claimed BOOLEAN DEFAULT 0,
                assigned_date DATE,
                completed_date DATE,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS quest_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                quest_type TEXT,
                value INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def generate_daily_quests(self, user_id: int) -> List[Dict]:
        """Генерирует ежедневные задания для пользователя"""
        # Загружаем шаблоны заданий
        with open('daily_quests.json', 'r', encoding='utf-8') as f:
            quest_templates = json.load(f)
        
        # Выбираем случайные 3 задания
        daily_quests = random.sample(quest_templates['quests'], min(3, len(quest_templates['quests'])))
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Удаляем старые невыполненные задания
        c.execute('''
            DELETE FROM user_quests 
            WHERE user_id = ? AND assigned_date < ? AND completed = 0
        ''', (user_id, today))
        
        # Добавляем новые задания
        for quest in daily_quests:
            c.execute('''
                INSERT OR REPLACE INTO user_quests 
                (user_id, quest_id, assigned_date, progress, completed)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, quest['id'], today, 0, 0))
        
        conn.commit()
        conn.close()
        
        return daily_quests
    
    def get_user_quests(self, user_id: int) -> List[Dict]:
        """Получить текущие задания пользователя"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        c.execute('''
            SELECT q.*, t.title, t.description, t.target, t.reward, t.type
            FROM user_quests q
            LEFT JOIN daily_quests_json t ON q.quest_id = t.id
            WHERE q.user_id = ? AND q.assigned_date = ? AND q.completed = 0
        ''', (user_id, today))
        
        rows = c.fetchall()
        conn.close()
        
        # Загружаем шаблоны для полных данных
        with open('daily_quests.json', 'r', encoding='utf-8') as f:
            quest_templates = json.load(f)
        
        quests = []
        for row in rows:
            quest_id = row[2]
            progress = row[3]
            
            # Находим шаблон
            template = next((q for q in quest_templates['quests'] if q['id'] == quest_id), None)
            
            if template:
                quests.append({
                    'id': quest_id,
                    'title': template['title'],
                    'description': template['description'],
                    'target': template.get('target', 1),
                    'reward': template['reward'],
                    'type': template['type'],
                    'progress': progress,
                    'completed': progress >= template.get('target', 1)
                })
        
        return quests
    
    def update_quest_progress(self, user_id: int, quest_type: str, value: int = 1):
        """Обновить прогресс заданий"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Обновляем прогресс
        c.execute('''
            UPDATE user_quests 
            SET progress = progress + ?
            WHERE user_id = ? 
            AND quest_id IN (
                SELECT id FROM daily_quests_json WHERE type = ?
            )
            AND assigned_date = ?
            AND completed = 0
        ''', (value, user_id, quest_type, today))
        
        # Проверяем завершенные задания
        c.execute('''
            UPDATE user_quests 
            SET completed = 1, completed_date = ?
            WHERE user_id = ? 
            AND progress >= (
                SELECT target FROM daily_quests_json 
                WHERE id = user_quests.quest_id
            )
            AND assigned_date = ?
            AND completed = 0
        ''', (today, user_id, today))
        
        conn.commit()
        conn.close()
    
    def claim_quest_reward(self, user_id: int, quest_id: int) -> int:
        """Получить награду за задание"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Проверяем, что задание выполнено и не получено
        c.execute('''
            SELECT q.reward 
            FROM user_quests uq
            JOIN daily_quests_json q ON uq.quest_id = q.id
            WHERE uq.user_id = ? 
            AND uq.quest_id = ? 
            AND uq.completed = 1 
            AND uq.claimed = 0
        ''', (user_id, quest_id))
        
        reward = c.fetchone()
        
        if reward:
            reward_amount = reward[0]
            
            # Отмечаем как полученное
            c.execute('''
                UPDATE user_quests 
                SET claimed = 1 
                WHERE user_id = ? AND quest_id = ?
            ''', (user_id, quest_id))
            
            # Добавляем очки пользователю
            c.execute('''
                UPDATE users 
                SET score = score + ? 
                WHERE telegram_id = ?
            ''', (reward_amount, user_id))
            
            conn.commit()
            conn.close()
            return reward_amount
        
        conn.close()
        return 0
