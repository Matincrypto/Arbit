# database.py
import sqlite3
import json
from config import DB_NAME

class DatabaseHandler:
    def __init__(self):
        self.db_name = DB_NAME

    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Users table (Now supports multiple accounts per telegram_id)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,           -- Removed UNIQUE constraint
            account_name TEXT,                      -- New column for account label
            full_name TEXT,
            phone_number TEXT,
            wallex_api_key TEXT,
            
            -- Capital Management
            buy_amount_tmn REAL DEFAULT 0,
            buy_amount_usdt REAL DEFAULT 0,
            max_frozen_tmn REAL DEFAULT 0,
            max_frozen_usdt REAL DEFAULT 0,
            
            -- Risk Management
            stop_loss_percent REAL DEFAULT 0,
            
            -- Filters
            allowed_strategies TEXT DEFAULT '[]',
            allowed_grades TEXT DEFAULT '[]',
            allowed_coins TEXT DEFAULT '[]',

            is_active BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Trades table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            coin_pair TEXT,
            signal_entry_price TEXT,
            signal_target_price TEXT,
            strategy_name TEXT,
            signal_grade TEXT,
            buy_order_id TEXT,
            buy_amount REAL,
            buy_status TEXT,
            buy_submit_time TIMESTAMP,
            sell_order_id TEXT,
            sell_status TEXT,
            log_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        
        conn.commit()
        conn.close()
        print(f"✅ Database {self.db_name} ready for Multi-Account support.")

if __name__ == "__main__":
    db = DatabaseHandler()
    db.init_db()
