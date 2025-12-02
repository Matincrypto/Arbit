# wallex_client.py
import requests
import json
from config import WALLEX_BASE_URL, DEFAULT_HEADERS


class WallexClient:
    def __init__(self, api_key=None):
        self.base_url = WALLEX_BASE_URL
        self.headers = DEFAULT_HEADERS.copy()
        if api_key:
            self.headers["X-API-Key"] = api_key

    def get_market_info(self, symbol):
        """دریافت اطلاعات بازار مثل تعداد اعشار (Precision)"""
        #
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
            print(f"API Error (Market Info): {e}")
        return None

    def get_last_price(self, symbol):
        """دریافت آخرین قیمت معامله شده (برای حد ضرر)"""
        #
        url = f"{self.base_url}/v1/trades?symbol={symbol}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success') and data['result']['latestTrades']:
                    # اولین آیتم لیست، آخرین معامله است
                    return float(data['result']['latestTrades'][0]['price'])
        except Exception as e:
            print(f"API Error (Price): {e}")
        return None

    def place_order(self, symbol, side, type, quantity, price=None):
        """ثبت سفارش خرید یا فروش"""
        # POST /v1/account/orders
        url = f"{self.base_url}/v1/account/orders"

        # نکته: مقادیر عددی باید به صورت رشته ارسال شوند
        payload = {
            "symbol": symbol,
            "side": side,  # "BUY" یا "SELL"
            "type": type,  # "LIMIT" یا "MARKET"
            "quantity": "{:.8f}".format(float(quantity)).rstrip('0').rstrip('.')  # فرمت استاندارد
        }
        if price and type == 'LIMIT':
            payload["price"] = str(price)

        try:
            resp = requests.post(url, json=payload, headers=self.headers, timeout=10)
            return resp.json()
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_order_status(self, client_order_id):
        """استعلام وضعیت یک سفارش خاص"""
        # GET /v1/account/orders/{id}
        url = f"{self.base_url}/v1/account/orders/{client_order_id}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            return resp.json()
        except Exception as e:
            return {"success": False, "message": str(e)}

    def cancel_order(self, client_order_id):
        """لغو سفارش"""
        # DELETE /v1/account/orders/{id}
        url = f"{self.base_url}/v1/account/orders/{client_order_id}"
        try:
            resp = requests.delete(url, headers=self.headers, timeout=10)
            return resp.json()
        except Exception as e:
            return {"success": False, "message": str(e)}