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

        # جدول کاربران با فیلد نام و پیش‌فرض‌های جدید
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            full_name TEXT,                         -- نام کاربر (جدید)
            phone_number TEXT,                      -- شماره موبایل
            wallex_api_key TEXT,
            
            -- مدیریت سرمایه
            buy_amount_tmn REAL DEFAULT 0,
            buy_amount_usdt REAL DEFAULT 0,
            max_frozen_tmn REAL DEFAULT 0,
            max_frozen_usdt REAL DEFAULT 0,
            
            -- مدیریت ریسک
            stop_loss_percent REAL DEFAULT 0,
            
            -- فیلترها (ذخیره به صورت JSON)
            allowed_strategies TEXT DEFAULT '[]',   -- استراتژی‌های انتخاب شده
            allowed_grades TEXT DEFAULT '[]',       -- گریدهای انتخاب شده (Q1, Q2...)
            blocked_coins TEXT DEFAULT '[]',

            is_active BOOLEAN DEFAULT 0,            -- پیش‌فرض غیرفعال
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # جدول معاملات (بدون تغییر)
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
        print(f"✅ دیتابیس {self.db_name} با ساختار جدید آپدیت شد.")

if __name__ == "__main__":
    db = DatabaseHandler()
    db.init_db()
