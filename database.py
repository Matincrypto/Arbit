# database.py
import sqlite3
import json
from config import DB_NAME


class DatabaseHandler:
    def __init__(self):
        self.db_name = DB_NAME

    def get_connection(self):
        """ایجاد اتصال به دیتابیس با خروجی دیکشنری‌مانند"""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. جدول کاربران (تنظیمات و فیلترها)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            wallex_api_key TEXT,

            -- مدیریت سرمایه
            buy_amount_tmn REAL DEFAULT 0,          -- مبلغ خرید تومانی
            buy_amount_usdt REAL DEFAULT 0,         -- مبلغ خرید تتری
            max_frozen_tmn REAL DEFAULT 0,          -- سقف مجاز دارایی درگیر (تومان)
            max_frozen_usdt REAL DEFAULT 0,         -- سقف مجاز دارایی درگیر (تتر)

            -- مدیریت ریسک
            stop_loss_percent REAL DEFAULT 0,       -- حد ضرر شناور (مثلا 2 درصد)

            -- فیلترها (به صورت JSON ذخیره می‌شوند)
            allowed_strategies TEXT DEFAULT '["Internal"]',
            allowed_grades TEXT DEFAULT '["Q1"]',
            blocked_coins TEXT DEFAULT '[]',

            is_active BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # 2. جدول معاملات (چرخه حیات سفارش)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,

            -- مشخصات سیگنال
            coin_pair TEXT,              -- نماد (مثلا BTCUSDT)
            signal_entry_price TEXT,
            signal_target_price TEXT,
            strategy_name TEXT,
            signal_grade TEXT,

            -- چرخه خرید
            buy_order_id TEXT,           -- Client Order ID
            buy_amount REAL,             -- مقدار ارز خریداری شده
            buy_status TEXT,             -- PENDING, SUBMITTED, FILLED, TIMEOUT_CANCELLED, FAILED
            buy_submit_time TIMESTAMP,   -- زمان دقیق ارسال سفارش

            -- چرخه فروش
            sell_order_id TEXT,
            sell_status TEXT,            -- PENDING, SUBMITTED, FILLED, STOP_LOSS_SUBMITTED, STOP_LOSS_FILLED

            log_message TEXT,            -- ثبت خطاها
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')

        conn.commit()
        conn.close()
        print(f"✅ دیتابیس {self.db_name} با موفقیت آماده‌سازی شد.")


if __name__ == "__main__":
    db = DatabaseHandler()
    db.init_db()