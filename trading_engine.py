# trading_engine.py
import json
import time
from datetime import datetime
from database import DatabaseHandler
from wallex_client import WallexClient
from config import BUY_TIMEOUT_SECONDS

class TradingEngine:
    def __init__(self):
        self.db_handler = DatabaseHandler()

    def process_signal(self, signal_data):
        """پردازش سیگنال ورودی و بررسی شرایط کاربران"""
        print(f"📩 سیگنال دریافت شد: {signal_data['coin']} ({signal_data['strategy_name']})")
        conn = self.db_handler.get_connection()
        cursor = conn.cursor()
        
        # دریافت کاربران فعال
        cursor.execute("SELECT * FROM users WHERE is_active = 1")
        users = cursor.fetchall()
        
        for user in users:
            if self._is_user_eligible(user, signal_data, conn):
                self._place_buy_order_for_user(user, signal_data, conn)
            else:
                # برای دیباگ میتوانید این خط را فعال کنید
                # print(f"کاربر {user['full_name']} واجد شرایط نبود.")
                pass
            
        conn.close()

    def _is_user_eligible(self, user, signal, conn):
        """بررسی تمام فیلترها (استراتژی، گرید، کوین، سرمایه)"""
        try:
            # 1. بررسی استراتژی
            allowed_strategies = json.loads(user['allowed_strategies'])
            if signal['strategy_name'] not in allowed_strategies:
                return False

            # 2. بررسی گرید (کیفیت سیگنال)
            allowed_grades = json.loads(user['allowed_grades'])
            if signal['signal_grade'] not in allowed_grades:
                return False

            # 3. بررسی ارزهای مجاز (تغییر جدید)
            allowed_coins = json.loads(user['allowed_coins'])
            if signal['coin'] not in allowed_coins:
                print(f"❌ ارز {signal['coin']} در لیست مجاز کاربر {user['full_name']} نیست.")
                return False

            # 4. بررسی سقف دارایی فریز شده
            cursor = conn.cursor()
            cursor.execute('''
                SELECT SUM(buy_amount * CAST(signal_entry_price AS REAL)) 
                FROM trades 
                WHERE user_id = ? AND (sell_status != 'SUCCESSFUL_TRADE' AND sell_status != 'STOP_LOSS_FILLED' AND buy_status != 'FAILED')
            ''', (user['id'],))
            current_frozen = cursor.fetchone()[0] or 0
            
            # تعیین سقف بر اساس نوع جفت ارز
            max_limit = user['max_frozen_tmn'] if signal['pair'] == 'TMN' else user['max_frozen_usdt']
            new_order_cost = user['buy_amount_tmn'] if signal['pair'] == 'TMN' else user['buy_amount_usdt']
            
            if (current_frozen + new_order_cost) > max_limit:
                print(f"⚠️ سقف دارایی پر است برای {user['full_name']}.")
                return False
                
            return True
            
        except Exception as e:
            print(f"Error checking eligibility: {e}")
            return False

    def _place_buy_order_for_user(self, user, signal, conn):
        client = WallexClient(user['wallex_api_key'])
        
        symbol = f"{signal['coin']}{signal['pair']}"
        entry_price = signal['entry_price']
        
        # تعیین بودجه
        budget = user['buy_amount_tmn'] if signal['pair'] == 'TMN' else user['buy_amount_usdt']
        
        # محاسبه حجم خرید
        # نکته: در نسخه پروداکشن باید step_size ارز را از مارکت بگیریم تا رند کنیم
        raw_quantity = float(budget) / float(entry_price)
        
        # ثبت سفارش
        resp = client.place_order(symbol, "BUY", "LIMIT", raw_quantity, entry_price)
        
        cursor = conn.cursor()
        if resp.get('success'):
            order_id = resp['result']['clientOrderId']
            print(f"✅ سفارش خرید برای {user['full_name']} ثبت شد: {symbol}")
            
            cursor.execute('''
                INSERT INTO trades (user_id, coin_pair, signal_entry_price, signal_target_price, 
                                  strategy_name, signal_grade,
                                  buy_order_id, buy_amount, buy_status, buy_submit_time, sell_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user['id'], symbol, entry_price, signal['target_price'], 
                  signal['strategy_name'], signal['signal_grade'],
                  order_id, raw_quantity, 'BUY_SUBMITTED', datetime.now(), 'PENDING'))
        else:
            print(f"❌ خطا در ثبت سفارش کاربر {user['full_name']}: {resp.get('message')}")
        conn.commit()

    def monitor_orders(self):
        """مدیریت تایم‌اوت خرید و ثبت سفارش فروش (تارگت)"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM trades WHERE buy_status = 'BUY_SUBMITTED'")
        active_buys = cursor.fetchall()
        
        for trade in active_buys:
            self._check_buy_status(trade, conn)
            
        conn.close()

    def _check_buy_status(self, trade, conn):
        cursor = conn.cursor()
        cursor.execute("SELECT wallex_api_key FROM users WHERE id = ?", (trade['user_id'],))
        user_row = cursor.fetchone()
        client = WallexClient(user_row['wallex_api_key'])
        
        status_resp = client.get_order_status(trade['buy_order_id'])
        if not status_resp.get('success'): return

        status = status_resp['result']['status']
        
        if status == 'FILLED':
            print(f"🎉 خرید {trade['coin_pair']} تکمیل شد. ثبت سفارش فروش (Target)...")
            
            sell_resp = client.place_order(
                trade['coin_pair'], "SELL", "LIMIT", 
                trade['buy_amount'], trade['signal_target_price']
            )
            
            if sell_resp.get('success'):
                sell_id = sell_resp['result']['clientOrderId']
                cursor.execute('''
                    UPDATE trades SET buy_status = 'FILLED', sell_status = 'SUBMITTED', sell_order_id = ?
                    WHERE id = ?
                ''', (sell_id, trade['id']))
            else:
                cursor.execute("UPDATE trades SET log_message = ? WHERE id = ?", 
                             (f"Sell Err: {sell_resp.get('message')}", trade['id']))

        else:
            # چک کردن تایم‌اوت
            submit_time = datetime.strptime(trade['buy_submit_time'], "%Y-%m-%d %H:%M:%S.%f")
            elapsed = (datetime.now() - submit_time).total_seconds()
            
            if elapsed > BUY_TIMEOUT_SECONDS:
                print(f"⏳ تایم‌اوت خرید {trade['coin_pair']}. لغو سفارش...")
                client.cancel_order(trade['buy_order_id'])
                cursor.execute("UPDATE trades SET buy_status = 'TIMEOUT_CANCELLED' WHERE id = ?", (trade['id'],))
        
        conn.commit()
