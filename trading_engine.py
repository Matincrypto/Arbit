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
                print(f"کاربر {user['telegram_id']} واجد شرایط این سیگنال نیست.")

        conn.close()

    def _is_user_eligible(self, user, signal, conn):
        """بررسی فیلترها و سقف دارایی فریز شده"""
        # 1. بررسی استراتژی
        allowed_strategies = json.loads(user['allowed_strategies'])
        if signal['strategy_name'] not in allowed_strategies:
            return False

        # 2. بررسی لیست سیاه
        blocked_coins = json.loads(user['blocked_coins'])
        if signal['coin'] in blocked_coins:
            return False

        # 3. بررسی سقف دارایی فریز شده (مهم)
        cursor = conn.cursor()
        # جمع مبالغ درگیر در سفارشات باز (خرید یا فروش کامل نشده)
        cursor.execute('''
            SELECT SUM(buy_amount * CAST(signal_entry_price AS REAL)) 
            FROM trades 
            WHERE user_id = ? AND (sell_status != 'SUCCESSFUL_TRADE' AND sell_status != 'STOP_LOSS_FILLED' AND buy_status != 'FAILED')
        ''', (user['id'],))
        current_frozen = cursor.fetchone()[0] or 0

        max_limit = user['max_frozen_tmn'] if signal['pair'] == 'TMN' else user['max_frozen_usdt']

        # مبلغ سفارش جدید
        new_order_cost = user['buy_amount_tmn'] if signal['pair'] == 'TMN' else user['buy_amount_usdt']

        if (current_frozen + new_order_cost) > max_limit:
            print(f"⚠️ سقف دارایی پر است. درگیر: {current_frozen}, حد مجاز: {max_limit}")
            return False

        return True

    def _place_buy_order_for_user(self, user, signal, conn):
        client = WallexClient(user['wallex_api_key'])

        symbol = f"{signal['coin']}{signal['pair']}"
        entry_price = signal['entry_price']

        # محاسبه حجم خرید
        budget = user['buy_amount_tmn'] if signal['pair'] == 'TMN' else user['buy_amount_usdt']

        # برای دقت بیشتر، بهتر است مقدار دقیق اعشار (Step Size) را از والکس بگیریم
        market_info = client.get_market_info(symbol)
        if not market_info:
            print(f"خطا در دریافت اطلاعات بازار {symbol}")
            return

        # محاسبه Quantity ساده
        raw_quantity = float(budget) / float(entry_price)

        # ثبت سفارش خرید Limit
        resp = client.place_order(symbol, "BUY", "LIMIT", raw_quantity, entry_price)

        cursor = conn.cursor()
        if resp.get('success'):
            order_id = resp['result']['clientOrderId']
            print(f"✅ سفارش خرید ثبت شد: {symbol} | کاربر: {user['telegram_id']}")

            cursor.execute('''
                INSERT INTO trades (user_id, coin_pair, signal_entry_price, signal_target_price, 
                                  strategy_name, signal_grade,
                                  buy_order_id, buy_amount, buy_status, buy_submit_time, sell_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user['id'], symbol, entry_price, signal['target_price'],
                  signal['strategy_name'], signal['signal_grade'],
                  order_id, raw_quantity, 'BUY_SUBMITTED', datetime.now(), 'PENDING'))
        else:
            print(f"❌ خطا در ثبت سفارش: {resp.get('message')}")
        conn.commit()

    def monitor_orders(self):
        """مدیریت تایم‌اوت خرید و ثبت سفارش فروش"""
        conn = self.db_handler.get_connection()
        cursor = conn.cursor()

        # فقط خریدهایی که سابمیت شده‌اند را چک کن
        cursor.execute("SELECT * FROM trades WHERE buy_status = 'BUY_SUBMITTED'")
        active_buys = cursor.fetchall()

        for trade in active_buys:
            self._check_buy_status(trade, conn)

        conn.close()

    def _check_buy_status(self, trade, conn):
        # ساخت کلاینت موقت برای کاربر
        cursor = conn.cursor()
        cursor.execute("SELECT wallex_api_key FROM users WHERE id = ?", (trade['user_id'],))
        user_row = cursor.fetchone()
        client = WallexClient(user_row['wallex_api_key'])

        status_resp = client.get_order_status(trade['buy_order_id'])
        if not status_resp.get('success'): return

        status = status_resp['result']['status']

        # حالت ۱: خرید کامل شده -> ثبت تارگت فروش
        if status == 'FILLED':
            print(f"🎉 خرید {trade['coin_pair']} پر شد. ثبت تارگت فروش...")

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
                               (f"Sell Error: {sell_resp.get('message')}", trade['id']))

        # حالت ۲: بررسی تایم‌اوت (۱ دقیقه)
        else:
            submit_time = datetime.strptime(trade['buy_submit_time'], "%Y-%m-%d %H:%M:%S.%f")
            elapsed = (datetime.now() - submit_time).total_seconds()

            if elapsed > BUY_TIMEOUT_SECONDS:
                print(f"⏳ تایم‌اوت سفارش خرید {trade['coin_pair']}. لغو سفارش...")
                client.cancel_order(trade['buy_order_id'])
                cursor.execute("UPDATE trades SET buy_status = 'TIMEOUT_CANCELLED' WHERE id = ?", (trade['id'],))

        conn.commit()