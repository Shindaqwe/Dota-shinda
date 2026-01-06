import sqlite3
from datetime import datetime
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class ClansSystem:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
        self.init_clans_db()
    
    def init_clans_db(self):
        """Инициализация таблиц кланов"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                tag TEXT,
                description TEXT,
                owner_id INTEGER,
                members_count INTEGER DEFAULT 1,
                total_score INTEGER DEFAULT 0,
                avg_mmr INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users(telegram_id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS clan_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER,
                user_id INTEGER,
                account_id INTEGER,
                role TEXT DEFAULT 'member',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                contribution INTEGER DEFAULT 0,
                FOREIGN KEY (clan_id) REFERENCES clans(id),
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS clan_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER,
                name TEXT,
                description TEXT,
                event_type TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                status TEXT DEFAULT 'upcoming',
                FOREIGN KEY (clan_id) REFERENCES clans(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def create_clan(self, name: str, tag: str, description: str, owner_id: int) -> Dict:
        """Создать новый клан"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            c.execute('''
                INSERT INTO clans (name, tag, description, owner_id, members_count)
                VALUES (?, ?, ?, ?, 1)
            ''', (name, tag, description, owner_id))
            
            clan_id = c.lastrowid
            
            # Добавляем владельца как участника
            c.execute('''
                INSERT INTO clan_members (clan_id, user_id, role)
                VALUES (?, ?, 'owner')
            ''', (clan_id, owner_id))
            
            conn.commit()
            
            return {
                'success': True,
                'clan_id': clan_id,
                'message': f'Клан {name} создан!'
            }
        except sqlite3.IntegrityError:
            return {
                'success': False,
                'message': 'Клан с таким именем уже существует'
            }
        finally:
            conn.close()
    
    def join_clan(self, clan_id: int, user_id: int, account_id: int) -> bool:
        """Вступить в клан"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Проверяем, не состоит ли уже
        c.execute('''
            SELECT id FROM clan_members 
            WHERE clan_id = ? AND user_id = ?
        ''', (clan_id, user_id))
        
        if c.fetchone():
            conn.close()
            return False
        
        # Проверяем лимит участников (например, 50)
        c.execute('''
            SELECT members_count FROM clans WHERE id = ?
        ''', (clan_id,))
        
        clan = c.fetchone()
        if clan and clan[0] >= 50:
            conn.close()
            return False
        
        # Добавляем участника
        c.execute('''
            INSERT INTO clan_members (clan_id, user_id, account_id)
            VALUES (?, ?, ?)
        ''', (clan_id, user_id, account_id))
        
        # Обновляем счетчик
        c.execute('''
            UPDATE clans 
            SET members_count = members_count + 1 
            WHERE id = ?
        ''', (clan_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def get_clan_info(self, clan_id: int) -> Dict:
        """Получить информацию о клане"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT c.*, u.username as owner_name
            FROM clans c
            LEFT JOIN users u ON c.owner_id = u.telegram_id
            WHERE c.id = ?
        ''', (clan_id,))
        
        clan = c.fetchone()
        
        if not clan:
            conn.close()
            return None
        
        # Получаем участников
        c.execute('''
            SELECT cm.user_id, u.username, cm.role, cm.contribution
            FROM clan_members cm
            LEFT JOIN users u ON cm.user_id = u.telegram_id
            WHERE cm.clan_id = ?
            ORDER BY cm.contribution DESC
            LIMIT 10
        ''', (clan_id,))
        
        members = []
        for row in c.fetchall():
            members.append({
                'user_id': row[0],
                'username': row[1],
                'role': row[2],
                'contribution': row[3]
            })
        
        conn.close()
        
        return {
            'id': clan[0],
            'name': clan[1],
            'tag': clan[2],
            'description': clan[3],
            'owner_id': clan[4],
            'owner_name': clan[9],
            'members_count': clan[5],
            'total_score': clan[6],
            'avg_mmr': clan[7],
            'created_at': clan[8],
            'top_members': members
        }
