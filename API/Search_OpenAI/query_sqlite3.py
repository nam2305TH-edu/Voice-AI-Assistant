class Querry_massage:
    create_table_session = ("""
                    CREATE TABLE IF NOT EXISTS session_context (
                    session_id TEXT PRIMARY KEY,
                    current_topic TEXT,
                    last_questions TEXT,  -- JSON encoded listtme_co
                    conversation_summary TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
    create_table_history = (""" 
                    CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                        """
                    )

    create_table_cache = ("""
                    CREATE TABLE IF NOT EXISTS search_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL UNIQUE,
                    result TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP   
                    )
                        """
                    )
    create_index_cache = ("""
                    CREATE INDEX IF NOT EXISTS idx_search_cache_query 
                        ON search_cache(query)
                    """)
    create_index_history = ("""
                    CREATE INDEX IF NOT EXISTS idx_conversations_question 
                        ON conversations(question)
                    """
                    )    
    create_index_session = (""" 
                    CREATE INDEX IF NOT EXISTS idx_session_context_updated 
                        ON session_context(updated_at)
                    """
                    )  
      