# wallex_client.py
import requests
from config import WALLEX_BASE_URL, DEFAULT_HEADERS

class WallexClient:
    def __init__(self, api_key=None):
        self.base_url = WALLEX_BASE_URL
        self.headers = DEFAULT_HEADERS.copy()
        if api_key:
            self.headers["X-API-Key"] = api_key

    def get_market_info(self, symbol):
        url = f"{self.base_url}/hector/web/v1/markets"
        try:
            resp = requests.get(url, headers=self.headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    for m in data['result']['markets']:
                        if m['symbol'] == symbol:
                            return m
        except Exception as e:
            print(f"API Error: {e}")
        return None

    def get_available_coins(self):
        """دریافت لیست کامل و یکتای ارزها از والکس"""
        # /hector/web/v1/markets
        url = f"{self.base_url}/hector/web/v1/markets"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    coins = set()
                    for m in data['result']['markets']:
                        # استخراج نام ارز پایه (مثلا از BTCUSDT -> BTC)
                        base = m.get('base_asset')
                        if base:
                            coins.add(base)
                    
                    # مرتب‌سازی الفبایی
                    return sorted(list(coins))
        except Exception as e:
            print(f"Error fetching coins: {e}")
        # لیست اضطراری در صورت خرابی API
        return ['BTC', 'ETH', 'USDT', 'TRX', 'SHIB', 'DOGE', 'ADA', 'XRP', 'LTC', 'BCH']

    # ... (بقیه توابع: get_last_price, place_order, get_order_status, cancel_order بدون تغییر)
    # حتما توابع قبلی که برای ترید و کنسل کردن بود را اینجا نگه دارید
    def get_last_price(self, symbol):
        url = f"{self.base_url}/v1/trades?symbol={symbol}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=5)
            if resp.status_code == 200 and resp.json().get('success'):
                return float(resp.json()['result']['latestTrades'][0]['price'])
        except: pass
        return None

    def place_order(self, symbol, side, type, quantity, price=None):
        url = f"{self.base_url}/v1/account/orders"
        payload = {"symbol": symbol, "side": side, "type": type, "quantity": str(quantity)}
        if price: payload["price"] = str(price)
        try:
            return requests.post(url, json=payload, headers=self.headers, timeout=10).json()
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_order_status(self, client_order_id):
        url = f"{self.base_url}/v1/account/orders/{client_order_id}"
        try: return requests.get(url, headers=self.headers, timeout=10).json()
        except: return {"success": False}

    def cancel_order(self, client_order_id):
        url = f"{self.base_url}/v1/account/orders/{client_order_id}"
        try: requests.delete(url, headers=self.headers, timeout=10); return {"success": True}
        except: return {"success": False}
