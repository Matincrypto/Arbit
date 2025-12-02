# risk_manager.py
import time
from database import DatabaseHandler
from wallex_client import WallexClient
from config import CHASING_ATTEMPTS, CHASING_DELAY

class RiskManager:
    def __init__(self):
        self.db_handler = DatabaseHandler()

    def check_active_stop_losses(self):
        conn = self.db_handler.get_connection()
        cursor = conn.cursor()
        
        # استفاده از ستون جدید stop_loss_percent
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
        
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        
        if pnl_percent <= (-1 * stop_loss_pct):
            print(f"⚠️ استاپ لاس فعال شد: {trade['full_name']} | {symbol}")
            self._execute_emergency_exit(trade, client, current_price, conn)

    def _execute_emergency_exit(self, trade, client, initial_price, conn):
        cursor = conn.cursor()
        
        if trade['sell_order_id']:
            client.cancel_order(trade['sell_order_id'])
            
        market_price = initial_price
        quantity = trade['buy_amount']
        
        for attempt in range(CHASING_ATTEMPTS):
            # فروش با قیمت کمی پایینتر برای تضمین اجرا
            sell_price = market_price * 0.995 
            resp = client.place_order(trade['coin_pair'], "SELL", "LIMIT", quantity, sell_price)
            
            if resp.get('success'):
                new_id = resp['result']['clientOrderId']
                cursor.execute("UPDATE trades SET sell_order_id=?, sell_status='STOP_LOSS_SUBMITTED' WHERE id=?", (new_id, trade['id']))
                conn.commit()
                
                time.sleep(CHASING_DELAY)
                
                status = client.get_order_status(new_id)
                if status.get('success') and status['result']['status'] == 'FILLED':
                    cursor.execute("UPDATE trades SET sell_status='STOP_LOSS_FILLED' WHERE id=?", (trade['id'],))
                    conn.commit()
                    return
                else:
                    client.cancel_order(new_id)
            
            new_p = client.get_last_price(trade['coin_pair'])
            if new_p: market_price = new_p
