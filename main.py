# main.py
import time
import requests
import traceback
from trading_engine import TradingEngine
from risk_manager import RiskManager
from config import SIGNAL_POOL_URL, SIGNAL_CHECK_INTERVAL, RISK_CHECK_INTERVAL, TELEGRAM_BOT_TOKEN, ADMIN_IDS

def send_admin_alert(message):
    """ارسال پیام اضطراری به ادمین"""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_IDS:
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # ارسال به اولین ادمین لیست
    admin_id = ADMIN_IDS[0] 
    
    payload = {
        "chat_id": admin_id,
        "text": f"⚠️ **هشدار سیستم:**\n\n{message}",
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        print("Failed to send admin alert")

def fetch_signals():
    try:
        resp = requests.get(SIGNAL_POOL_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'success' and data.get('count') > 0:
                return data['data']
    except Exception as e:
        # خطاهای شبکه را فقط پرینت کن، اسپم نکن
        print(f"Network Error: {e}")
    return []

def main():
    print("🚀 انجین تریدینگ فعال شد...")
    
    # اطمینان از وجود جداول
    from database import DatabaseHandler
    db = DatabaseHandler()
    db.init_db()

    engine = TradingEngine()
    risk_manager = RiskManager()
    
    processed_signals = set()
    last_risk_check = time.time()
    
    # ارسال پیام روشن شدن سیستم به ادمین
    send_admin_alert("🚀 سیستم تریدینگ با موفقیت روی سرور روشن شد.")

    while True:
        try:
            # 1. دریافت سیگنال
            signals = fetch_signals()
            for signal in signals:
                sig_id = f"{signal['coin']}_{signal['signal_time']}"
                if sig_id not in processed_signals:
                    # برای اطمینان از عدم وقوع خطای پیش‌بینی نشده در پردازش
                    try:
                        engine.process_signal(signal)
                    except Exception as e:
                        error_msg = f"خطا در پردازش سیگنال {signal.get('coin')}:\n{str(e)}"
                        print(error_msg)
                        send_admin_alert(error_msg)
                        
                    processed_signals.add(sig_id)
            
            # 2. مانیتورینگ
            engine.monitor_orders()
            
            # 3. مدیریت ریسک
            if time.time() - last_risk_check > RISK_CHECK_INTERVAL:
                risk_manager.check_active_stop_losses()
                last_risk_check = time.time()
            
            time.sleep(SIGNAL_CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            # خطاهای کلی لوپ اصلی (کرش)
            error_trace = traceback.format_exc()
            print(f"CRITICAL ERROR: {e}")
            send_admin_alert(f"❌ **خطای بحرانی در انجین:**\n`{str(e)}`\nسیستم تا 5 ثانیه دیگر مجدد تلاش می‌کند.")
            time.sleep(5)

if __name__ == "__main__":
    main()
