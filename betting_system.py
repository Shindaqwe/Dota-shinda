import sqlite3
from datetime import datetime
from typing import Dict, List
import random
import logging

logger = logging.getLogger(__name__)

class BettingSystem:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
        self.init_betting_db()
    
    def init_betting_db(self):
        """Инициализация таблиц ставок"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS matches_to_bet (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team1 TEXT NOT NULL,
                team2 TEXT NOT NULL,
                odds1 REAL DEFAULT 1.8,
                odds2 REAL DEFAULT 2.1,
                start_time TIMESTAMP,
                status TEXT DEFAULT 'upcoming',
                winner TEXT,
                match_data TEXT
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                match_id INTEGER,
                team TEXT,
                amount INTEGER,
                potential_win INTEGER,
                status TEXT DEFAULT 'pending',
                placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches_to_bet(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def create_betting_match(self, team1: str, team2: str, odds1: float, odds2: float) -> int:
        """Создать матч для ставок"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        start_time = datetime.now().timestamp() + 3600  # Через час
        
        c.execute('''
            INSERT INTO matches_to_bet (team1, team2, odds1, odds2, start_time)
            VALUES (?, ?, ?, ?, ?)
        ''', (team1, team2, odds1, odds2, start_time))
        
        match_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return match_id
    
    def place_bet(self, user_id: int, match_id: int, team: str, amount: int) -> Dict:
        """Сделать ставку"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Проверяем баланс пользователя
        c.execute('SELECT score FROM users WHERE telegram_id = ?', (user_id,))
        user = c.fetchone()
        
        if not user or user[0] < amount:
            conn.close()
            return {
                'success': False,
                'message': 'Недостаточно очков для ставки'
            }
        
        # Получаем коэффициенты
        c.execute('''
            SELECT odds1, odds2, team1, team2 FROM matches_to_bet 
            WHERE id = ? AND status = 'upcoming'
        ''', (match_id,))
        
        match = c.fetchone()
        
        if not match:
            conn.close()
            return {
                'success': False,
                'message': 'Матч не найден или уже начался'
            }
        
        # Определяем коэффициент
        odds = match[0] if team == match[2] else match[1]
        potential_win = int(amount * odds)
        
        # Вычитаем очки
        c.execute('''
            UPDATE users SET score = score - ? 
            WHERE telegram_id = ?
        ''', (amount, user_id))
        
        # Создаем ставку
        c.execute('''
            INSERT INTO user_bets (user_id, match_id, team, amount, potential_win)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, match_id, team, amount, potential_win))
        
        conn.commit()
        conn.close()
        
        return {
            'success': True,
            'message': f'Ставка на {team} принята!',
            'bet_id': c.lastrowid,
            'potential_win': potential_win
        }
