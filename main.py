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
        print(f"Network Error (Signal Fetch): {e}")
    return []


def main():
    print("🚀 سیستم معاملاتی شروع به کار کرد...")

    # راه‌اندازی اولیه دیتابیس
    from database import DatabaseHandler
    db = DatabaseHandler()
    db.init_db()

    engine = TradingEngine()
    risk_manager = RiskManager()

    # حافظه کش برای جلوگیری از ترید تکراری یک سیگنال
    processed_signals = set()
    last_risk_check = time.time()

    while True:
        try:
            # 1. دریافت سیگنال
            signals = fetch_signals()
            for signal in signals:
                # ایجاد کلید یکتا: کوین + زمان سیگنال
                sig_id = f"{signal['coin']}_{signal['signal_time']}"

                if sig_id not in processed_signals:
                    engine.process_signal(signal)
                    processed_signals.add(sig_id)

            # 2. مانیتورینگ سفارشات (چرخه خرید و فروش)
            engine.monitor_orders()

            # 3. مدیریت ریسک (چک کردن هر چند ثانیه یکبار)
            if time.time() - last_risk_check > RISK_CHECK_INTERVAL:
                risk_manager.check_active_stop_losses()
                last_risk_check = time.time()

            time.sleep(SIGNAL_CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("توقف دستی برنامه.")
            break
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()