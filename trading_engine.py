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
        print(f"📩 سیگنال: {signal_data['coin']} | استراتژی: {signal_data['strategy_name']}")
        conn = self.db_handler.get_connection()
        cursor = conn.cursor()
        
        # دریافت کاربران فعال
        cursor.execute("SELECT * FROM users WHERE is_active = 1")
        users = cursor.fetchall()
        
        for user in users:
            if self._is_user_eligible(user, signal_data, conn):
                self._place_buy_order_for_user(user, signal_data, conn)
            
        conn.close()

    def _is_user_eligible(self, user, signal, conn):
        try:
            # 1. بررسی استراتژی
            # اگر ستون allowed_strategies خالی یا نال بود، لیست خالی بذار
            strats_json = user['allowed_strategies'] if user['allowed_strategies'] else '[]'
            allowed_strategies = json.loads(strats_json)
            if signal['strategy_name'] not in allowed_strategies:
                return False

            # 2. بررسی گرید
            grades_json = user['allowed_grades'] if user['allowed_grades'] else '[]'
            allowed_grades = json.loads(grades_json)
            if signal['signal_grade'] not in allowed_grades:
                return False

            # 3. بررسی کوین‌های مجاز (اینجا قبلاً خطا می‌داد چون ستون جدید است)
            coins_json = user['allowed_coins'] if user['allowed_coins'] else '[]'
            allowed_coins = json.loads(coins_json)
            if signal['coin'] not in allowed_coins:
                # print(f"ارز {signal['coin']} برای {user['full_name']} مجاز نیست.")
                return False

            # 4. بررسی سقف دارایی فریز شده (ستون‌های جدید)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT SUM(buy_amount * CAST(signal_entry_price AS REAL)) 
                FROM trades 
                WHERE user_id = ? AND (sell_status != 'SUCCESSFUL_TRADE' AND sell_status != 'STOP_LOSS_FILLED' AND buy_status != 'FAILED')
            ''', (user['id'],))
            res = cursor.fetchone()
            current_frozen = res[0] if res and res[0] else 0
            
            # استفاده از ستون‌های جدید max_frozen_tmn/usdt
            if signal['pair'] == 'TMN':
                max_limit = user['max_frozen_tmn']
                new_cost = user['buy_amount_tmn']
            else:
                max_limit = user['max_frozen_usdt']
                new_cost = user['buy_amount_usdt']
            
            if (current_frozen + new_cost) > max_limit:
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
        
        # تعیین بودجه بر اساس نوع جفت ارز
        budget = user['buy_amount_tmn'] if signal['pair'] == 'TMN' else user['buy_amount_usdt']
        
        raw_quantity = float(budget) / float(entry_price)
        
        resp = client.place_order(symbol, "BUY", "LIMIT", raw_quantity, entry_price)
        
        cursor = conn.cursor()
        if resp.get('success'):
            order_id = resp['result']['clientOrderId']
            print(f"✅ خرید ثبت شد: {symbol} برای {user['full_name']}")
            
            cursor.execute('''
                INSERT INTO trades (user_id, coin_pair, signal_entry_price, signal_target_price, 
                                  strategy_name, signal_grade,
                                  buy_order_id, buy_amount, buy_status, buy_submit_time, sell_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user['id'], symbol, entry_price, signal['target_price'], 
                  signal['strategy_name'], signal['signal_grade'],
                  order_id, raw_quantity, 'BUY_SUBMITTED', datetime.now(), 'PENDING'))
        else:
            print(f"❌ خطا در خرید: {resp.get('message')}")
        conn.commit()

    def monitor_orders(self):
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
        if not user_row: return
        
        client = WallexClient(user_row['wallex_api_key'])
        status_resp = client.get_order_status(trade['buy_order_id'])
        
        if not status_resp.get('success'): return

        status = status_resp['result']['status']
        
        if status == 'FILLED':
            print(f"🎉 خرید {trade['coin_pair']} کامل شد. ثبت فروش...")
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
            submit_time = datetime.strptime(trade['buy_submit_time'], "%Y-%m-%d %H:%M:%S.%f")
            if (datetime.now() - submit_time).total_seconds() > BUY_TIMEOUT_SECONDS:
                print(f"⏳ تایم‌اوت خرید {trade['coin_pair']}.")
                client.cancel_order(trade['buy_order_id'])
                cursor.execute("UPDATE trades SET buy_status = 'TIMEOUT_CANCELLED' WHERE id = ?", (trade['id'],))
        
        conn.commit()
