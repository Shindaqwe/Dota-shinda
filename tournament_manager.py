import sqlite3
import json
from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class TournamentManager:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
        self.init_tournament_db()
    
    def init_tournament_db(self):
        """Инициализация таблиц турниров"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                max_participants INTEGER DEFAULT 32,
                current_participants INTEGER DEFAULT 0,
                prize TEXT,
                status TEXT DEFAULT 'upcoming',
                start_date DATE,
                end_date DATE,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS tournament_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER,
                user_id INTEGER,
                account_id INTEGER,
                username TEXT,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                points INTEGER DEFAULT 0,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS tournament_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER,
                round_number INTEGER,
                player1_id INTEGER,
                player2_id INTEGER,
                winner_id INTEGER,
                status TEXT DEFAULT 'scheduled',
                match_data TEXT,
                scheduled_time TIMESTAMP,
                played_at TIMESTAMP,
                FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def create_tournament(self, name: str, max_participants: int, 
                         prize: str, start_date: datetime, 
                         created_by: int) -> int:
        """Создать новый турнир"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO tournaments 
            (name, max_participants, prize, start_date, created_by, status)
            VALUES (?, ?, ?, ?, ?, 'upcoming')
        ''', (name, max_participants, prize, start_date, created_by))
        
        tournament_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return tournament_id
    
    def join_tournament(self, tournament_id: int, user_id: int, 
                       account_id: int, username: str) -> bool:
        """Присоединиться к турниру"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Проверяем, есть ли место
        c.execute('''
            SELECT current_participants, max_participants 
            FROM tournaments 
            WHERE id = ?
        ''', (tournament_id,))
        
        tournament = c.fetchone()
        
        if not tournament or tournament[0] >= tournament[1]:
            conn.close()
            return False
        
        # Проверяем, не участвует ли уже
        c.execute('''
            SELECT id FROM tournament_participants 
            WHERE tournament_id = ? AND user_id = ?
        ''', (tournament_id, user_id))
        
        if c.fetchone():
            conn.close()
            return False
        
        # Добавляем участника
        c.execute('''
            INSERT INTO tournament_participants 
            (tournament_id, user_id, account_id, username)
            VALUES (?, ?, ?, ?)
        ''', (tournament_id, user_id, account_id, username))
        
        # Обновляем счетчик участников
        c.execute('''
            UPDATE tournaments 
            SET current_participants = current_participants + 1 
            WHERE id = ?
        ''', (tournament_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def get_active_tournaments(self) -> List[Dict]:
        """Получить активные турниры"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT * FROM tournaments 
            WHERE status IN ('upcoming', 'ongoing')
            ORDER BY start_date ASC
        ''')
        
        tournaments = []
        for row in c.fetchall():
            tournaments.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'max_participants': row[3],
                'current_participants': row[4],
                'prize': row[5],
                'status': row[6],
                'start_date': row[7],
                'end_date': row[8]
            })
        
        conn.close()
        return tournaments
    
    def get_tournament_standings(self, tournament_id: int) -> List[Dict]:
        """Получить таблицу лидеров турнира"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT username, wins, losses, points
            FROM tournament_participants
            WHERE tournament_id = ?
            ORDER BY points DESC, wins DESC
        ''', (tournament_id,))
        
        standings = []
        for row in c.fetchall():
            standings.append({
                'username': row[0],
                'wins': row[1],
                'losses': row[2],
                'points': row[3],
                'winrate': (row[1] / (row[1] + row[2]) * 100) if (row[1] + row[2]) > 0 else 0
            })
        
        conn.close()
        return standings
    
    def generate_bracket(self, tournament_id: int):
        """Генерировать сетку турнира"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Получаем участников
        c.execute('''
            SELECT id FROM tournament_participants 
            WHERE tournament_id = ?
            ORDER BY joined_at
        ''', (tournament_id,))
        
        participants = [row[0] for row in c.fetchall()]
        
        if len(participants) < 2:
            conn.close()
            return False
        
        # Случайно перемешиваем для создания пар
        random.shuffle(participants)
        
        # Создаем матчи первого раунда
        round_number = 1
        for i in range(0, len(participants), 2):
            if i + 1 < len(participants):
                c.execute('''
                    INSERT INTO tournament_matches 
                    (tournament_id, round_number, player1_id, player2_id, status)
                    VALUES (?, ?, ?, ?, 'scheduled')
                ''', (tournament_id, round_number, participants[i], participants[i+1]))
        
        # Обновляем статус турнира
        c.execute('''
            UPDATE tournaments 
            SET status = 'ongoing' 
            WHERE id = ?
        ''', (tournament_id,))
        
        conn.commit()
        conn.close()
        return True
