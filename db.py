import sqlite3
import json
import uuid
import time
from typing import List, Dict, Optional, Any

DB_FILE = "risiko.db"

class Database:
    def __init__(self):
        self.conn = None

    def connect(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()

    def init_db(self):
        self.connect()
        cursor = self.conn.cursor()
        
        # Enable Foreign Keys
        cursor.execute("PRAGMA foreign_keys = ON;")

        # Players
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                rating REAL DEFAULT 1200.0,
                games_played INTEGER DEFAULT 0,
                created_at REAL
            )
        """)

        # Matches
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                k_factor_used REAL NOT NULL,
                winner_id TEXT NOT NULL,
                created_at REAL,
                FOREIGN KEY(winner_id) REFERENCES players(id)
            )
        """)

        # Participations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS participations (
                id TEXT PRIMARY KEY,
                match_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                is_winner INTEGER NOT NULL, -- 0 or 1
                rating_before REAL NOT NULL,
                rating_after REAL NOT NULL,
                rating_delta REAL NOT NULL,
                FOREIGN KEY(match_id) REFERENCES matches(id),
                FOREIGN KEY(player_id) REFERENCES players(id)
            )
        """)

        # Settings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Insert Default K-Factor if not exists
        cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", ("k_factor", "32"))

        self.conn.commit()
    
    # --- Settings ---
    def get_k_factor(self) -> float:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = 'k_factor'")
        row = cursor.fetchone()
        return float(row['value']) if row else 32.0

    def set_k_factor(self, k: float):
        cursor = self.conn.cursor()
        cursor.execute("REPLACE INTO system_settings (key, value) VALUES ('k_factor', ?)", (str(k),))
        self.conn.commit()

    # --- Players ---
    def create_player(self, name: str) -> str:
        new_id = str(uuid.uuid4())
        try:
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO players (id, name, created_at) VALUES (?, ?, ?)", 
                           (new_id, name, time.time()))
            self.conn.commit()
            return new_id
        except sqlite3.IntegrityError:
            raise ValueError("Player name already exists")

    def delete_player(self, player_id: str):
        """
        Deletes a player and cleans up associated data (matches won, participations).
        """
        try:
            cursor = self.conn.cursor()
            
            # 1. Get matches won by this player to delete them entirely
            cursor.execute("SELECT id FROM matches WHERE winner_id = ?", (player_id,))
            matches_won = [row['id'] for row in cursor.fetchall()]
            
            # 2. Delete participations for matches won by this player (everyone else's record in those matches)
            for mid in matches_won:
                cursor.execute("DELETE FROM participations WHERE match_id = ?", (mid,))
            
            # 3. Delete the matches won by this player
            cursor.execute("DELETE FROM matches WHERE winner_id = ?", (player_id,))

            # 4. Delete participations of this player (where they lost)
            cursor.execute("DELETE FROM participations WHERE player_id = ?", (player_id,))

            # 5. Delete the player
            cursor.execute("DELETE FROM players WHERE id = ?", (player_id,))
            
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e

    def delete_match(self, match_id: str):
        """
        Deletes a match and reverts the rating changes for all involved players.
        """
        try:
            cursor = self.conn.cursor()
            
            # 1. Get participations to know what to reverse
            cursor.execute("SELECT player_id, rating_delta FROM participations WHERE match_id = ?", (match_id,))
            parts = cursor.fetchall()
            
            if not parts:
                raise ValueError("Match not found")

            # 2. Reverse ratings
            for p in parts:
                # Subtract the delta to revert. Decrease games_played.
                cursor.execute("UPDATE players SET rating = rating - ?, games_played = games_played - 1 WHERE id = ?", 
                               (p['rating_delta'], p['player_id']))

            # 3. Delete from participations
            cursor.execute("DELETE FROM participations WHERE match_id = ?", (match_id,))
            
            # 4. Delete from matches
            cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))
            
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e

    def get_player(self, player_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_all_players(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM players")
        players = [dict(row) for row in cursor.fetchall()]

        if not players:
            return []

        # 1. Calculate Dynamic Threshold
        max_games = max(p['games_played'] for p in players) if players else 0
        
        # Logic: At least 5 games. At least 20% of leader. Cap at 15 games.
        # MIN(15, MAX(5, max_games * 0.20))
        calculated_threshold = max(5, int(max_games * 0.20))
        threshold = min(15, calculated_threshold)

        # 2. Separate Ranked vs Provisional
        ranked = []
        provisional = []

        for p in players:
            p['is_ranked'] = p['games_played'] >= threshold
            p['threshold'] = threshold # Pass this info to frontend
            
            if p['is_ranked']:
                ranked.append(p)
            else:
                provisional.append(p)

        # 3. Sort
        # Ranked: By Rating DESC
        ranked.sort(key=lambda x: x['rating'], reverse=True)
        
        # Provisional: By Rating DESC too (or games played? Usually rating is fine, just separated)
        # Let's sort provisional by Rating too so they see where they "would" be
        provisional.sort(key=lambda x: x['rating'], reverse=True)

        return ranked + provisional

    # --- Matches ---
    def record_match(self, date: str, winner_id: str, loser_ids: List[str], winner_delta: float, winner_new_rating: float, losers_data: List[Dict]):
        """
        losers_data: List of dicts {id, delta, new_rating, old_rating}
        Transactional.
        """
        match_id = str(uuid.uuid4())
        k_used = self.get_k_factor()
        
        try:
            cursor = self.conn.cursor()
            
            # 1. Create Match
            cursor.execute("INSERT INTO matches (id, date, k_factor_used, winner_id, created_at) VALUES (?, ?, ?, ?, ?)",
                           (match_id, date, k_used, winner_id, time.time()))

            # 2. Update Winner
            # Get old rating first (though we likely passed it in, let's trust the calc matches the db state if concurrency wasn't an issue. 
            # Ideally we lock or re-read, but for this simple app we assume single-threaded logic in server.py calls this)
            
            winner_old_rating = winner_new_rating - winner_delta # Reverse just to store 'before' snapshot correctly
            
            cursor.execute("UPDATE players SET rating = ?, games_played = games_played + 1 WHERE id = ?", 
                           (winner_new_rating, winner_id))
            
            cursor.execute("""
                INSERT INTO participations (id, match_id, player_id, is_winner, rating_before, rating_after, rating_delta)
                VALUES (?, ?, ?, 1, ?, ?, ?)
            """, (str(uuid.uuid4()), match_id, winner_id, winner_old_rating, winner_new_rating, winner_delta))

            # 3. Update Losers
            for l_data in losers_data:
                pid = l_data['id']
                delta = l_data['delta']
                new_r = l_data['new_rating']
                old_r = l_data['old_rating']
                
                cursor.execute("UPDATE players SET rating = ?, games_played = games_played + 1 WHERE id = ?", 
                               (new_r, pid))
                
                cursor.execute("""
                    INSERT INTO participations (id, match_id, player_id, is_winner, rating_before, rating_after, rating_delta)
                    VALUES (?, ?, ?, 0, ?, ?, ?)
                """, (str(uuid.uuid4()), match_id, pid, old_r, new_r, delta))

            self.conn.commit()
            return match_id
        except Exception as e:
            self.conn.rollback()
            raise e
            
    def get_player_history(self, player_id: str) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                p.match_id, 
                m.date, 
                p.is_winner, 
                p.rating_delta, 
                p.rating_after 
            FROM participations p
            JOIN matches m ON p.match_id = m.id
            WHERE p.player_id = ?
            ORDER BY m.date DESC
        """, (player_id,))
        return [dict(row) for row in cursor.fetchall()]

    def get_matches_history(self) -> List[Dict]:
        cursor = self.conn.cursor()
        # Get Match + Winner + Losers concatenated
        cursor.execute("""
            SELECT 
                m.id, 
                m.date, 
                w.name as winner_name,
                GROUP_CONCAT(l.name, ', ') as losers_names
            FROM matches m
            JOIN players w ON m.winner_id = w.id
            JOIN participations p ON p.match_id = m.id AND p.is_winner = 0
            JOIN players l ON p.player_id = l.id
            GROUP BY m.id
            ORDER BY m.date DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

