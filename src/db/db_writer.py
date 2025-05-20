import sqlite3
import time
from typing import Optional

class SessionManager:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()
        self.current_session_id: Optional[int] = None
        self.current_user_id: Optional[int] = None  # None for guest

    def start_session(self, user_id: Optional[int] = None):
        cursor = self.conn.cursor()
        start_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cursor.execute(
            "INSERT INTO sessions (user_id, start_time) VALUES (?, ?)",
            (user_id, start_time)
        )
        self.conn.commit()
        self.current_session_id = cursor.lastrowid
        self.current_user_id = user_id

    def record_metrics(self, metrics: dict):
        if self.current_session_id is None:
            # Optionally, auto-start guest session here
            self.start_session()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO metrics
            (session_id, timestamp, stroke_rate, heart_rate, pace, distance, elapsed_time, power)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.current_session_id,
            metrics["timestamp"],
            metrics.get("stroke_rate"),
            metrics.get("heart_rate"),
            metrics.get("pace"),
            metrics.get("distance"),
            metrics.get("elapsed_time"),
            metrics.get("power"),
        ))
        self.conn.commit()

    def end_session(self, completed: bool = True):
        if self.current_session_id is None:
            return
        cursor = self.conn.cursor()
        end_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cursor.execute("""
            UPDATE sessions
            SET end_time = ?, completed = ?
            WHERE id = ?
        """, (end_time, int(completed), self.current_session_id))
        self.conn.commit()
        self.current_session_id = None
        self.current_user_id = None

    # Additional methods for user management and claiming guest sessions can be added here.
