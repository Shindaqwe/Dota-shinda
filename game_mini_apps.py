import sqlite3
import random
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class MiniGamesManager:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
        self.init_games_db()
    
    def init_games_db(self):
        """Инициализация таблиц мини-игр"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS tic_tac_toe_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player1_id INTEGER,
                player2_id INTEGER,
                board_state TEXT DEFAULT '000000000',
                current_turn INTEGER DEFAULT 1,
                winner_id INTEGER,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def create_tic_tac_toe_game(self, player1_id: int, player2_id: Optional[int] = None) -> int:
        """Создать новую игру в крестики-нолики"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO tic_tac_toe_games 
            (player1_id, player2_id, board_state, current_turn, status)
            VALUES (?, ?, '000000000', 1, 'waiting')
        ''', (player1_id, player2_id))
        
        game_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return game_id
    
    def join_tic_tac_toe_game(self, game_id: int, player2_id: int) -> bool:
        """Присоединиться к игре"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT player2_id, status FROM tic_tac_toe_games 
            WHERE id = ?
        ''', (game_id,))
        
        game = c.fetchone()
        
        if not game or game[1] != 'waiting':
            conn.close()
            return False
        
        if game[0] is None:
            c.execute('''
                UPDATE tic_tac_toe_games 
                SET player2_id = ?, status = 'active'
                WHERE id = ?
            ''', (player2_id, game_id))
            
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False
    
    def make_move(self, game_id: int, player_id: int, position: int) -> Dict:
        """Сделать ход в игре"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Получаем текущее состояние игры
        c.execute('''
            SELECT board_state, current_turn, player1_id, player2_id, status
            FROM tic_tac_toe_games 
            WHERE id = ?
        ''', (game_id,))
        
        game = c.fetchone()
        
        if not game or game[4] != 'active':
            conn.close()
            return {'success': False, 'error': 'Game not active'}
        
        board_state = list(game[0])
        current_turn = game[1]
        
        # Проверяем, чей ход
        if (current_turn == 1 and player_id != game[2]) or \
           (current_turn == 2 and player_id != game[3]):
            conn.close()
            return {'success': False, 'error': 'Not your turn'}
        
        # Проверяем, что клетка свободна
        if board_state[position] != '0':
            conn.close()
            return {'success': False, 'error': 'Position already taken'}
        
        # Делаем ход
        symbol = '1' if current_turn == 1 else '2'
        board_state[position] = symbol
        
        # Проверяем победу
        winner = self.check_winner(board_state)
        
        # Обновляем состояние
        new_turn = 2 if current_turn == 1 else 1
        new_status = 'finished' if winner else 'active'
        
        c.execute('''
            UPDATE tic_tac_toe_games 
            SET board_state = ?, current_turn = ?, 
                winner_id = ?, status = ?, 
                finished_at = ?
            WHERE id = ?
        ''', (
            ''.join(board_state), 
            new_turn if not winner else None,
            winner,
            new_status,
            datetime.now() if winner else None,
            game_id
        ))
        
        conn.commit()
        conn.close()
        
        return {
            'success': True,
            'board': board_state,
            'winner': winner,
            'next_turn': new_turn if not winner else None
        }
    
    def check_winner(self, board: List[str]) -> Optional[int]:
        """Проверка победителя"""
        # Все выигрышные комбинации
        winning_combinations = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],  # Горизонтальные
            [0, 3, 6], [1, 4, 7], [2, 5, 8],  # Вертикальные
            [0, 4, 8], [2, 4, 6]              # Диагональные
        ]
        
        for combo in winning_combinations:
            if (board[combo[0]] == board[combo[1]] == board[combo[2]] and 
                board[combo[0]] != '0'):
                return 1 if board[combo[0]] == '1' else 2
        
        # Проверка на ничью
        if '0' not in board:
            return 0  # Ничья
        
        return None
    
    def format_board(self, board_state: str) -> str:
        """Форматирует доску для отображения"""
        symbols = {'0': '⬜', '1': '❌', '2': '⭕'}
        board = []
        
        for i, cell in enumerate(board_state):
            board.append(symbols[cell])
        
        formatted = f"""
🎮 <b>Dota Tic-Tac-Toe</b>

1️⃣ {board[0]} │ {board[1]} │ {board[2]}
───────────
2️⃣ {board[3]} │ {board[4]} │ {board[5]}
───────────
3️⃣ {board[6]} │ {board[7]} │ {board[8]}

   🅰️   🅱️   🅲️
"""
        return formatted
