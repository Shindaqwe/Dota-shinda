import sqlite3
import json
from datetime import datetime
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class AchievementsSystem:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
        self.init_achievements_db()
    
    def init_achievements_db(self):
        """Инициализация таблиц достижений"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_id TEXT,
                progress INTEGER DEFAULT 0,
                unlocked BOOLEAN DEFAULT 0,
                unlocked_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def unlock_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Разблокировать достижение"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Проверяем, не разблокировано ли уже
        c.execute('''
            SELECT unlocked FROM user_achievements 
            WHERE user_id = ? AND achievement_id = ?
        ''', (user_id, achievement_id))
        
        existing = c.fetchone()
        
        if existing and existing[0]:
            conn.close()
            return False
        
        # Разблокируем достижение
        if existing:
            c.execute('''
                UPDATE user_achievements 
                SET unlocked = 1, unlocked_at = ?
                WHERE user_id = ? AND achievement_id = ?
            ''', (datetime.now(), user_id, achievement_id))
        else:
            c.execute('''
                INSERT INTO user_achievements 
                (user_id, achievement_id, unlocked, unlocked_at)
                VALUES (?, ?, 1, ?)
            ''', (user_id, achievement_id, datetime.now()))
        
        # Загружаем данные достижения для награды
        with open('achievements.json', 'r', encoding='utf-8') as f:
            achievements_data = json.load(f)
        
        achievement = next(
            (a for a in achievements_data['achievements'] if a['id'] == achievement_id), 
            None
        )
        
        if achievement:
            # Начисляем награду
            reward = achievement.get('reward', 0)
            c.execute('''
                UPDATE users 
                SET score = score + ? 
                WHERE telegram_id = ?
            ''', (reward, user_id))
        
        conn.commit()
        conn.close()
        return True
    
    def update_achievement_progress(self, user_id: int, achievement_type: str, value: int = 1):
        """Обновить прогресс достижений"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Загружаем достижения
        with open('achievements.json', 'r', encoding='utf-8') as f:
            achievements_data = json.load(f)
        
        # Находим достижения данного типа
        for achievement in achievements_data['achievements']:
            if achievement.get('type') == achievement_type:
                achievement_id = achievement['id']
                target = achievement.get('target', 1)
                
                # Получаем текущий прогресс
                c.execute('''
                    SELECT progress FROM user_achievements 
                    WHERE user_id = ? AND achievement_id = ?
                ''', (user_id, achievement_id))
                
                result = c.fetchone()
                
                if result:
                    current_progress = result[0]
                    new_progress = min(current_progress + value, target)
                    
                    c.execute('''
                        UPDATE user_achievements 
                        SET progress = ?
                        WHERE user_id = ? AND achievement_id = ?
                    ''', (new_progress, user_id, achievement_id))
                    
                    # Проверяем, достигнута ли цель
                    if new_progress >= target and current_progress < target:
                        self.unlock_achievement(user_id, achievement_id)
                else:
                    # Создаем новую запись
                    new_progress = min(value, target)
                    
                    c.execute('''
                        INSERT INTO user_achievements 
                        (user_id, achievement_id, progress, unlocked)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, achievement_id, new_progress, 1 if new_progress >= target else 0))
                    
                    if new_progress >= target:
                        self.unlock_achievement(user_id, achievement_id)
        
        conn.commit()
        conn.close()
    
    def get_user_achievements(self, user_id: int) -> Dict:
        """Получить достижения пользователя"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT ua.achievement_id, ua.progress, ua.unlocked, 
                   a.title, a.description, a.reward, a.target, a.icon
            FROM user_achievements ua
            LEFT JOIN achievements_json a ON ua.achievement_id = a.id
            WHERE ua.user_id = ?
        ''', (user_id,))
        
        achievements = []
        total_unlocked = 0
        total_score = 0
        
        for row in c.fetchall():
            achievement = {
                'id': row[0],
                'progress': row[1],
                'unlocked': bool(row[2]),
                'title': row[3],
                'description': row[4],
                'reward': row[5],
                'target': row[6],
                'icon': row[7],
                'progress_percent': (row[1] / row[6] * 100) if row[6] else 100
            }
            
            achievements.append(achievement)
            
            if achievement['unlocked']:
                total_unlocked += 1
                total_score += achievement['reward']
        
        # Получаем все доступные достижения для подсчета общего количества
        with open('achievements.json', 'r', encoding='utf-8') as f:
            all_achievements = json.load(f)
        
        total_achievements = len(all_achievements['achievements'])
        
        conn.close()
        
        return {
            'achievements': achievements,
            'total_unlocked': total_unlocked,
            'total_achievements': total_achievements,
            'completion_percent': (total_unlocked / total_achievements * 100) if total_achievements > 0 else 0,
            'total_score': total_score
        }
