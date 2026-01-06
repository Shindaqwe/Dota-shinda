import sqlite3
from datetime import datetime, timedelta
import aiohttp
import json
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)

class AdvancedStats:
    def __init__(self, db_path='dota2.db'):
        self.db_path = db_path
    
    async def get_weekly_stats(self, account_id: int) -> Dict:
        """Получить статистику за неделю"""
        try:
            # Получаем матчи за последние 7 дней
            end_date = int(datetime.now().timestamp())
            start_date = int((datetime.now() - timedelta(days=7)).timestamp())
            
            async with aiohttp.ClientSession() as session:
                url = f"https://api.opendota.com/api/players/{account_id}/matches"
                params = {
                    'date': f'{start_date}-{end_date}',
                    'limit': 100
                }
                
                async with session.get(url, params=params) as r:
                    if r.status == 200:
                        matches = await r.json()
                        
                        if not matches:
                            return None
                        
                        stats = {
                            'total_games': len(matches),
                            'wins': 0,
                            'losses': 0,
                            'heroes': {},
                            'kills': 0,
                            'deaths': 0,
                            'assists': 0,
                            'durations': [],
                            'days': {}
                        }
                        
                        for match in matches:
                            # Определяем день
                            match_date = datetime.fromtimestamp(match.get('start_time', 0))
                            day_key = match_date.strftime('%Y-%m-%d')
                            
                            if day_key not in stats['days']:
                                stats['days'][day_key] = {'wins': 0, 'games': 0}
                            
                            stats['days'][day_key]['games'] += 1
                            
                            # Результат
                            is_radiant = match.get('player_slot', 0) < 128
                            radiant_win = match.get('radiant_win', False)
                            win = (is_radiant and radiant_win) or (not is_radiant and not radiant_win)
                            
                            if win:
                                stats['wins'] += 1
                                stats['days'][day_key]['wins'] += 1
                            else:
                                stats['losses'] += 1
                            
                            # Герой
                            hero_id = str(match.get('hero_id', 0))
                            if hero_id not in stats['heroes']:
                                stats['heroes'][hero_id] = {'games': 0, 'wins': 0}
                            
                            stats['heroes'][hero_id]['games'] += 1
                            if win:
                                stats['heroes'][hero_id]['wins'] += 1
                            
                            # KDA
                            stats['kills'] += match.get('kills', 0)
                            stats['deaths'] += match.get('deaths', 0)
                            stats['assists'] += match.get('assists', 0)
                            stats['durations'].append(match.get('duration', 0))
                        
                        return stats
        except Exception as e:
            logger.error(f"Weekly stats error: {e}")
            return None
    
    async def get_weakness_analysis(self, account_id: int) -> Dict:
        """Анализ слабых сторон"""
        try:
            # Получаем последние 50 игр
            async with aiohttp.ClientSession() as session:
                url = f"https://api.opendota.com/api/players/{account_id}/matches"
                params = {'limit': 50}
                
                async with session.get(url, params=params) as r:
                    if r.status == 200:
                        matches = await r.json()
                        
                        analysis = {
                            'early_game': {'wins': 0, 'total': 0},
                            'late_game': {'wins': 0, 'total': 0},
                            'teamfights': {'kills': 0, 'deaths': 0, 'assists': 0},
                            'farm': {'last_hits': 0, 'denies': 0, 'gpm': 0}
                        }
                        
                        for match in matches:
                            duration = match.get('duration', 0)
                            
                            # Анализ по фазам игры
                            if duration < 1800:  # Менее 30 минут
                                analysis['early_game']['total'] += 1
                                is_radiant = match.get('player_slot', 0) < 128
                                radiant_win = match.get('radiant_win', False)
                                if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                                    analysis['early_game']['wins'] += 1
                            else:
                                analysis['late_game']['total'] += 1
                                is_radiant = match.get('player_slot', 0) < 128
                                radiant_win = match.get('radiant_win', False)
                                if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                                    analysis['late_game']['wins'] += 1
                            
                            # Teamfights (упрощенно через KDA)
                            analysis['teamfights']['kills'] += match.get('kills', 0)
                            analysis['teamfights']['deaths'] += match.get('deaths', 0)
                            analysis['teamfights']['assists'] += match.get('assists', 0)
                            
                            # Farm
                            analysis['farm']['last_hits'] += match.get('last_hits', 0)
                            analysis['farm']['denies'] += match.get('denies', 0)
                            analysis['farm']['gpm'] += match.get('gold_per_min', 0)
                        
                        # Вычисляем проценты
                        if analysis['early_game']['total'] > 0:
                            analysis['early_game']['winrate'] = (
                                analysis['early_game']['wins'] / analysis['early_game']['total'] * 100
                            )
                        
                        if analysis['late_game']['total'] > 0:
                            analysis['late_game']['winrate'] = (
                                analysis['late_game']['wins'] / analysis['late_game']['total'] * 100
                            )
                        
                        analysis['teamfights']['kda'] = (
                            (analysis['teamfights']['kills'] + analysis['teamfights']['assists']) / 
                            analysis['teamfights']['deaths']
                            if analysis['teamfights']['deaths'] > 0 else 0
                        )
                        
                        if len(matches) > 0:
                            analysis['farm']['avg_last_hits'] = analysis['farm']['last_hits'] / len(matches)
                            analysis['farm']['avg_gpm'] = analysis['farm']['gpm'] / len(matches)
                        
                        return analysis
        except Exception as e:
            logger.error(f"Weakness analysis error: {e}")
            return None
    
    async def get_match_prediction(self, account_id: int, hero_id: int = None) -> Dict:
        """Прогноз матча на основе статистики"""
        try:
            # Получаем статистику по герою
            hero_stats = {}
            if hero_id:
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.opendota.com/api/players/{account_id}/heroes"
                    async with session.get(url) as r:
                        if r.status == 200:
                            heroes = await r.json()
                            for hero in heroes:
                                if hero.get('hero_id') == hero_id:
                                    games = hero.get('games', 0)
                                    wins = hero.get('win', 0)
                                    hero_stats = {
                                        'games': games,
                                        'wins': wins,
                                        'winrate': (wins / games * 100) if games > 0 else 0
                                    }
                                    break
            
            # Базовый прогноз
            prediction = {
                'win_chance': 50.0,  # Базовая вероятность
                'strengths': [],
                'weaknesses': [],
                'recommendations': []
            }
            
            # Если есть статистика по герою, корректируем прогноз
            if hero_stats.get('games', 0) > 10:
                prediction['win_chance'] = hero_stats['winrate']
                if hero_stats['winrate'] > 55:
                    prediction['strengths'].append(f"Вы сильны на этом герое ({hero_stats['winrate']:.1f}% винрейт)")
                elif hero_stats['winrate'] < 45:
                    prediction['weaknesses'].append(f"Слабый винрейт на этом герое ({hero_stats['winrate']:.1f}%)")
            
            # Рекомендации
            prediction['recommendations'] = [
                "Фокусируйтесь на своей роли",
                "Следите за картой",
                "Покупайте варды",
                "Коммуницируйте с командой"
            ]
            
            return prediction
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return None
