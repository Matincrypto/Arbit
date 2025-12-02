# risk_manager.py
import time
from database import DatabaseHandler
from wallex_client import WallexClient
from config import CHASING_ATTEMPTS, CHASING_DELAY

class RiskManager:
    def __init__(self):
        self.db_handler = DatabaseHandler()

    def check_active_stop_losses(self):
        """بررسی حد ضرر برای تمام معاملات باز"""
        conn = self.db_handler.get_connection()
        cursor = conn.cursor()
        
        # فقط معاملاتی را بگیر که:
        # 1. خریدشان کامل شده (buy_status=FILLED)
        # 2. هنوز با سود فروخته نشده‌اند (sell_status != SUCCESSFUL...)
        # 3. کاربر حد ضرر تعیین کرده باشد (stop_loss_percent > 0)
        query = '''
            SELECT t.*, u.stop_loss_percent, u.wallex_api_key, u.full_name
            FROM trades t
            JOIN users u ON t.user_id = u.id
            WHERE (t.sell_status = 'SUBMITTED' OR t.sell_status = 'PENDING')
            AND u.stop_loss_percent > 0
        '''
        cursor.execute(query)
        active_trades = cursor.fetchall()
        
        for trade in active_trades:
            self._process_single_trade_risk(trade, conn)
            
        conn.close()

    def _process_single_trade_risk(self, trade, conn):
        client = WallexClient(api_key=trade['wallex_api_key'])
        symbol = trade['coin_pair']
        
        current_price = client.get_last_price(symbol)
        if not current_price: return

        entry_price = float(trade['signal_entry_price'])
        stop_loss_pct = float(trade['stop_loss_percent'])
        
        # فرمول درصد سود/ضرر: (قیمت فعلی - قیمت خرید) / قیمت خرید * 100
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        
        # اگر ضرر (عدد منفی) بزرگتر از حد تعیین شده بود
        # مثال: PNL = -3% و StopLoss = 2%  ==>  -3 <= -2 (True)
        if pnl_percent <= (-1 * stop_loss_pct):
            print(f"⚠️ حد ضرر فعال شد برای {trade['full_name']} روی {symbol} (PNL: {pnl_percent:.2f}%)")
            self._execute_emergency_exit(trade, client, current_price, conn)

    def _execute_emergency_exit(self, trade, client, initial_price, conn):
        """لغو سفارش سود و فروش سریع به قیمت بازار"""
        cursor = conn.cursor()
        
        # 1. لغو سفارش تارگت قبلی
        if trade['sell_order_id']:
            client.cancel_order(trade['sell_order_id'])
            
        # 2. تلاش برای فروش (Chasing)
        market_price = initial_price
        quantity = trade['buy_amount']
        
        for attempt in range(CHASING_ATTEMPTS):
            print(f"🔥 فروش اضطراری {trade['coin_pair']} - تلاش {attempt+1}")
            
            # ثبت سفارش لیمیت با قیمت لحظه‌ای (چون والکس مارکت اوردر ندارد یا لیمیت مطمئن‌تر است)
            # برای اطمینان از فروش سریع، قیمت را کمی پایین‌تر می‌زنیم (Slippage)
            sell_price = market_price * 0.995 
            
            resp = client.place_order(trade['coin_pair'], "SELL", "LIMIT", quantity, sell_price)
            
            if resp.get('success'):
                new_order_id = resp['result']['clientOrderId']
                
                cursor.execute('''
                    UPDATE trades SET sell_order_id = ?, sell_status = 'STOP_LOSS_SUBMITTED', 
                    log_message = 'Stop Loss Triggered'
                    WHERE id = ?
                ''', (new_order_id, trade['id']))
                conn.commit()
                
                time.sleep(CHASING_DELAY)
                
                # چک کردن وضعیت
                status_resp = client.get_order_status(new_order_id)
                if status_resp.get('success') and status_resp['result']['status'] == 'FILLED':
                    print("✅ خروج با حد ضرر انجام شد.")
                    cursor.execute("UPDATE trades SET sell_status = 'STOP_LOSS_FILLED' WHERE id = ?", (trade['id'],))
                    conn.commit()
                    return
                else:
                    client.cancel_order(new_order_id)
            
            # آپدیت قیمت برای دور بعدی
            new_price = client.get_last_price(trade['coin_pair'])
            if new_price: market_price = new_price
