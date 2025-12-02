# main.py
import time
import requests
from trading_engine import TradingEngine
from risk_manager import RiskManager
from config import SIGNAL_POOL_URL, SIGNAL_CHECK_INTERVAL, RISK_CHECK_INTERVAL

def fetch_signals():
    try:
        resp = requests.get(SIGNAL_POOL_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'success' and data.get('count') > 0:
                return data['data']
    except Exception as e:
        print(f"Signal Fetch Error: {e}")
    return []

def main():
    print("🚀 انجین تریدینگ و مدیریت ریسک فعال شد...")
    
    # اطمینان از وجود جداول
    from database import DatabaseHandler
    db = DatabaseHandler()
    db.init_db()

    engine = TradingEngine()
    risk_manager = RiskManager()
    
    processed_signals = set()
    last_risk_check = time.time()

    while True:
        try:
            # 1. دریافت و پردازش سیگنال (خرید)
            signals = fetch_signals()
            for signal in signals:
                sig_id = f"{signal['coin']}_{signal['signal_time']}"
                if sig_id not in processed_signals:
                    engine.process_signal(signal)
                    processed_signals.add(sig_id)
            
            # 2. مانیتورینگ سفارشات (تارگت گذاری و تایم‌اوت)
            engine.monitor_orders()
            
            # 3. مدیریت ریسک (حد ضرر) - هر 5 ثانیه
            if time.time() - last_risk_check > RISK_CHECK_INTERVAL:
                risk_manager.check_active_stop_losses()
                last_risk_check = time.time()
            
            time.sleep(SIGNAL_CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
