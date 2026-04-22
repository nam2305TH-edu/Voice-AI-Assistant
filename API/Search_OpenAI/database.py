import sqlite3
import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from API.Search_OpenAI.query_sqlite3 import Querry_massage

CACHE_TIMEOUT_SECONDS = 600


class SessionContext:
    def __init__(self, session_id: str, current_topic: str = "", 
                 last_questions: List[str] = None, conversation_summary: str = ""):
        self.session_id = session_id
        self.current_topic = current_topic
        self.last_questions = last_questions or []
        self.conversation_summary = conversation_summary
    
    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "current_topic": self.current_topic,
            "last_questions": self.last_questions,
            "conversation_summary": self.conversation_summary
        }
    
    def get_context_string(self, max_length: int = 500) -> str:
        """Tạo chuỗi ngữ cảnh để đưa vào prompt (giới hạn độ dài)"""
        context_parts = []
        if self.current_topic:
            context_parts.append(f"Chủ đề hiện tại: {self.current_topic}")
        if self.last_questions:
            recent = self.last_questions[-3:]  # Lấy 3 câu hỏi gần nhất
            context_parts.append(f"Các câu hỏi gần đây: {'; '.join(recent)}")
        if self.conversation_summary:
            summary = self.conversation_summary[:200]  # Giới hạn summary
            context_parts.append(f"Tóm tắt: {summary}")
        
        result = "\n".join(context_parts) if context_parts else ""
        return result[:max_length] if len(result) > max_length else result


class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect('./data/tme_mess.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_tables()

    def _init_tables(self):
        tables_and_indexes = [
            Querry_massage.create_table_history,
            Querry_massage.create_table_cache,
            Querry_massage.create_table_session,
            Querry_massage.create_index_cache,
            Querry_massage.create_index_history,
            Querry_massage.create_index_session
        ]
        
        for query in tables_and_indexes:
            self.cursor.execute(query)
        self.conn.commit()

    def check_history(self, query: str) -> str:
        self.cursor.execute(
            "SELECT answer FROM conversations WHERE question LIKE ? LIMIT 1",
            (f'%{query}%',)
        )
        result = self.cursor.fetchone()
        return f"[From history] {result[0]}" if result else None

    def check_cache(self, query: str) -> str:
        """Kiểm tra cache, trả về None nếu cache quá 10 phút"""
        self.cursor.execute(
            "SELECT result, timestamp FROM search_cache WHERE query = ?",
            (query,)
        )
        result = self.cursor.fetchone()
        if result:
            cache_result, cache_time = result
            # Parse timestamp và kiểm tra timeout
            try:
                cache_datetime = datetime.strptime(cache_time, "%Y-%m-%d %H:%M:%S")
                age_seconds = (datetime.now() - cache_datetime).total_seconds()
                if age_seconds > CACHE_TIMEOUT_SECONDS:
                    # Cache quá hạn, xóa và trả về None
                    self.delete_cache(query)
                    print(f"[Cache] Expired ({age_seconds:.0f}s > {CACHE_TIMEOUT_SECONDS}s): {query[:50]}")
                    return None
                print(f"[Cache] Hit ({age_seconds:.0f}s old): {query[:50]}")
                return cache_result
            except Exception as e:
                print(f"[Cache] Parse error: {e}")
                return cache_result
        return None

    def delete_cache(self, query: str):
        """Xóa một cache entry"""
        self.cursor.execute("DELETE FROM search_cache WHERE query = ?", (query,))
        self.conn.commit()

    def clear_expired_cache(self):
        """Xóa tất cả cache quá 10 phút"""
        cutoff_time = datetime.now() - timedelta(seconds=CACHE_TIMEOUT_SECONDS)
        self.cursor.execute(
            "DELETE FROM search_cache WHERE timestamp < ?",
            (cutoff_time.strftime("%Y-%m-%d %H:%M:%S"),)
        )
        deleted = self.cursor.rowcount
        self.conn.commit()
        if deleted > 0:
            print(f"[Cache] Cleared {deleted} expired entries")
        return deleted

    def clear_all_cache(self):
        """Xóa toàn bộ cache"""
        self.cursor.execute("DELETE FROM search_cache")
        deleted = self.cursor.rowcount
        self.conn.commit()
        print(f"[Cache] Cleared all {deleted} entries")
        return deleted

    def save_cache(self, query: str, result: str):
        self.cursor.execute(
            "INSERT OR REPLACE INTO search_cache (query, result) VALUES (?, ?)",
            (query, result)
        )
        self.conn.commit()

    def save_conversation(self, question: str, answer: str, source: str):
        self.cursor.execute(
            "INSERT INTO conversations (question, answer, source) VALUES (?, ?, ?)",
            (question, answer, source)
        )
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()

    # ==================== SESSION CONTEXT METHODS ====================
    
    def get_session(self, session_id: str) -> Optional[SessionContext]:
        """Lấy ngữ cảnh session từ database"""
        self.cursor.execute(
            "SELECT current_topic, last_questions, conversation_summary FROM session_context WHERE session_id = ?",
            (session_id,)
        )
        result = self.cursor.fetchone()
        if result:
            current_topic, last_questions_json, conversation_summary = result
            last_questions = json.loads(last_questions_json) if last_questions_json else []
            return SessionContext(
                session_id=session_id,
                current_topic=current_topic or "",
                last_questions=last_questions,
                conversation_summary=conversation_summary or ""
            )
        return None
    
    def create_session(self, session_id: str) -> SessionContext:
        """Tạo session mới"""
        self.cursor.execute(
            "INSERT OR IGNORE INTO session_context (session_id, last_questions) VALUES (?, ?)",
            (session_id, json.dumps([]))
        )
        self.conn.commit()
        return SessionContext(session_id=session_id)
    
    def get_or_create_session(self, session_id: str) -> SessionContext:
        """Lấy session hoặc tạo mới nếu chưa tồn tại"""
        session = self.get_session(session_id)
        if session is None:
            session = self.create_session(session_id)
        return session
    
    def update_session_topic(self, session_id: str, topic: str):
        """Cập nhật chủ đề hiện tại của session"""
        self.cursor.execute(
            """UPDATE session_context 
               SET current_topic = ?, updated_at = CURRENT_TIMESTAMP 
               WHERE session_id = ?""",
            (topic, session_id)
        )
        self.conn.commit()
    
    def add_question_to_session(self, session_id: str, question: str, max_questions: int = 10):
        """Thêm câu hỏi vào lịch sử session (giới hạn số lượng)"""
        session = self.get_or_create_session(session_id)
        session.last_questions.append(question)
        # Giữ lại max_questions câu hỏi gần nhất
        if len(session.last_questions) > max_questions:
            session.last_questions = session.last_questions[-max_questions:]
        
        self.cursor.execute(
            """UPDATE session_context 
               SET last_questions = ?, updated_at = CURRENT_TIMESTAMP 
               WHERE session_id = ?""",
            (json.dumps(session.last_questions), session_id)
        )
        self.conn.commit()
    
    def update_session_summary(self, session_id: str, summary: str):
        """Cập nhật tóm tắt cuộc trò chuyện"""
        self.cursor.execute(
            """UPDATE session_context 
               SET conversation_summary = ?, updated_at = CURRENT_TIMESTAMP 
               WHERE session_id = ?""",
            (summary, session_id)
        )
        self.conn.commit()
    
    def clear_session(self, session_id: str):
        """Xóa ngữ cảnh session"""
        self.cursor.execute(
            "DELETE FROM session_context WHERE session_id = ?",
            (session_id,)
        )
        self.conn.commit()
    
    def get_session_history(self, session_id: str, limit: int = 5) -> List[Dict]:
        """Lấy lịch sử hội thoại của session từ bảng conversations"""
        self.cursor.execute(
            """SELECT question, answer, timestamp 
               FROM conversations 
               WHERE question IN (
                   SELECT json_each.value 
                   FROM session_context, json_each(session_context.last_questions) 
                   WHERE session_context.session_id = ?
               )
               ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit)
        )
        results = self.cursor.fetchall()
        return [
            {"question": r[0], "answer": r[1], "timestamp": r[2]}
            for r in results
        ]