import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class SeasonsSystem:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
        self.init_seasons_db()
    
    def init_seasons_db(self):
        """Инициализация таблиц сезонов"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                number INTEGER,
                start_date DATE,
                end_date DATE,
                status TEXT DEFAULT 'active',
                rewards TEXT
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS season_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER,
                user_id INTEGER,
                account_id INTEGER,
                username TEXT,
                rating INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                rank TEXT DEFAULT 'Unranked',
                rewards_claimed BOOLEAN DEFAULT 0,
                FOREIGN KEY (season_id) REFERENCES seasons(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_current_season(self) -> Dict:
        """Получить текущий сезон"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        c.execute('''
            SELECT * FROM seasons 
            WHERE start_date <= ? AND end_date >= ? 
            AND status = 'active'
            ORDER BY start_date DESC
            LIMIT 1
        ''', (today, today))
        
        season = c.fetchone()
        conn.close()
        
        if season:
            return {
                'id': season[0],
                'name': season[1],
                'number': season[2],
                'start_date': season[3],
                'end_date': season[4],
                'status': season[5],
                'rewards': season[6]
            }
        
        # Создаем новый сезон если нет активного
        return self.create_new_season()
    
    def create_new_season(self) -> Dict:
        """Создать новый сезон"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Определяем номер нового сезона
        c.execute('SELECT MAX(number) FROM seasons')
        max_number = c.fetchone()[0] or 0
        
        season_name = f"Сезон {max_number + 1}"
        start_date = datetime.now().strftime('%Y-%m-%d')
        end_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        c.execute('''
            INSERT INTO seasons (name, number, start_date, end_date)
            VALUES (?, ?, ?, ?)
        ''', (season_name, max_number + 1, start_date, end_date))
        
        season_id = c.lastrowid
        
        conn.commit()
        conn.close()
        
        return {
            'id': season_id,
            'name': season_name,
            'number': max_number + 1,
            'start_date': start_date,
            'end_date': end_date,
            'status': 'active'
        }
    
    def get_user_season_stats(self, user_id: int, season_id: int = None) -> Dict:
        """Получить статистику пользователя в сезоне"""
        if not season_id:
            season = self.get_current_season()
            season_id = season['id']
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT * FROM season_rankings 
            WHERE user_id = ? AND season_id = ?
        ''', (user_id, season_id))
        
        stats = c.fetchone()
        
        if stats:
            return {
                'season_id': stats[1],
                'rating': stats[4],
                'games_played': stats[5],
                'games_won': stats[6],
                'rank': stats[7],
                'winrate': (stats[6] / stats[5] * 100) if stats[5] > 0 else 0
            }
        
        # Создаем запись если нет
        c.execute('''
            INSERT INTO season_rankings (season_id, user_id, rating)
            VALUES (?, ?, 1000)
        ''', (season_id, user_id))
        
        conn.commit()
        conn.close()
        
        return {
            'season_id': season_id,
            'rating': 1000,
            'games_played': 0,
            'games_won': 0,
            'rank': 'Unranked',
            'winrate': 0
        }
