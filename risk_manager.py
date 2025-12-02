# risk_manager.py
import time
from database import DatabaseHandler
from wallex_client import WallexClient
from config import CHASING_ATTEMPTS, CHASING_DELAY


class RiskManager:
    def __init__(self):
        self.db_handler = DatabaseHandler()

    def check_active_stop_losses(self):
        """بررسی مداوم قیمت بازار و فعال کردن حد ضرر"""
        conn = self.db_handler.get_connection()
        cursor = conn.cursor()

        # 1. پیدا کردن معاملاتی که منتظر فروش هستند
        query = '''
            SELECT t.*, u.stop_loss_percent, u.wallex_api_key 
            FROM trades t
            JOIN users u ON t.user_id = u.id
            WHERE (t.sell_status = 'PENDING' OR t.sell_status = 'SUBMITTED')
            AND u.stop_loss_percent > 0
        '''
        cursor.execute(query)
        active_trades = cursor.fetchall()

        for trade in active_trades:
            self._process_single_trade(trade, conn)

        conn.close()

    def _process_single_trade(self, trade, conn):
        client = WallexClient(api_key=trade['wallex_api_key'])
        symbol = trade['coin_pair']

        # 2. گرفتن قیمت لحظه‌ای
        current_price = client.get_last_price(symbol)
        if not current_price:
            return

        entry_price = float(trade['signal_entry_price'])
        stop_loss_pct = float(trade['stop_loss_percent'])

        # 3. محاسبه درصد سود/ضرر
        pnl_percent = ((current_price - entry_price) / entry_price) * 100

        # 4. شرط خروج اضطراری
        if pnl_percent <= (-1 * stop_loss_pct):
            print(f"⚠️ حد ضرر فعال شد: {symbol} | قیمت جاری: {current_price} | ضرر: {pnl_percent:.2f}%")
            self._execute_emergency_exit(trade, client, current_price, conn)

    def _execute_emergency_exit(self, trade, client, initial_price, conn):
        """چرخه نقدشوندگی سریع (Order Chasing Loop)"""
        cursor = conn.cursor()

        # الف) لغو سفارش تارگت (فروش سود) قبلی
        if trade['sell_order_id']:
            client.cancel_order(trade['sell_order_id'])
            print(f"سفارش تارگت قبلی برای {trade['coin_pair']} لغو شد.")

        # ب) حلقه تلاش برای فروش با قیمت لحظه‌ای
        market_price = initial_price
        quantity = trade['buy_amount']

        for attempt in range(CHASING_ATTEMPTS):
            print(f"🔥 تلاش خروج اضطراری {attempt + 1}/{CHASING_ATTEMPTS} - قیمت: {market_price}")

            # ثبت سفارش جدید
            resp = client.place_order(trade['coin_pair'], "SELL", "LIMIT", quantity, market_price)

            if resp.get('success'):
                new_order_id = resp['result']['clientOrderId']

                # آپدیت دیتابیس
                cursor.execute('''
                    UPDATE trades SET sell_order_id = ?, sell_status = 'STOP_LOSS_SUBMITTED'
                    WHERE id = ?
                ''', (new_order_id, trade['id']))
                conn.commit()

                # صبر کوتاه
                time.sleep(CHASING_DELAY)

                # چک کردن وضعیت
                status_resp = client.get_order_status(new_order_id)
                if status_resp.get('success') and status_resp['result']['status'] == 'FILLED':
                    print("✅ خروج اضطراری انجام شد.")
                    cursor.execute("UPDATE trades SET sell_status = 'STOP_LOSS_FILLED' WHERE id = ?", (trade['id'],))
                    conn.commit()
                    return
                else:
                    # اگر پر نشد، لغو کن تا با قیمت جدید امتحان کنیم
                    client.cancel_order(new_order_id)

            # آپدیت قیمت برای دور بعدی حلقه
            new_price = client.get_last_price(trade['coin_pair'])
            if new_price:
                market_price = new_price

        print("❌ نقدشوندگی سریع موفق نبود (نوسان شدید بازار).")