import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import schedule
import yfinance as yf
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

BOT_TOKEN = "8673591792:AAFSHOgBQerGUy8trOQpCgD_8casDTqn4uw"
CHAT_ID = "8355121174"

WATCHLIST = [
    {"name": "OLTIN (XAU/USD)", "ticker": "GC=F"},
    {"name": "BITCOIN (BTC/USD)", "ticker": "BTC-USD"},
    {"name": "ETHEREUM (ETH/USD)", "ticker": "ETH-USD"},
    {"name": "EUR/USD", "ticker": "EURUSD=X"}
]

# Render port talabini qondirish uchun yengil veb-server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Trading bot is running 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Xatolik: {e}")

def get_market_data(ticker: str):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    if df.empty or len(df) < 200:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi()
    df['EMA_200'] = EMAIndicator(close=df['Close'], window=200).ema_indicator()
    df['EMA_50'] = EMAIndicator(close=df['Close'], window=50).ema_indicator()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "price": float(last['Close']),
        "rsi": float(last['RSI']),
        "prev_rsi": float(prev['RSI']),
        "ema200": float(last['EMA_200']),
        "ema50": float(last['EMA_50']),
        "prev_ema50": float(prev['EMA_50']),
        "prev_ema200": float(prev['EMA_200'])
    }

def check_asset(asset: dict):
    name = asset["name"]
    ticker = asset["ticker"]
    try:
        data = get_market_data(ticker)
        if not data:
            return

        price = data["price"]
        rsi = data["rsi"]
        prev_rsi = data["prev_rsi"]
        ema200 = data["ema200"]
        ema50 = data["ema50"]
        prev_ema50 = data["prev_ema50"]
        prev_ema200 = data["prev_ema200"]

        if price > ema200 and prev_rsi < 35 and rsi >= 35:
            msg = f"🟢 *SAVDOGA KIRISH (BUY)*\n\n📊 *Aktiv:* {name}\n💵 *Narx:* `{price:.2f}`\n📈 *RSI:* `{rsi:.1f}`"
            send_telegram(msg)
        elif prev_ema50 <= prev_ema200 and ema50 > ema200:
            msg = f"🚀 *KUCHLI BUY (Golden Cross)*\n\n📊 *Aktiv:* {name}\n💵 *Narx:* `{price:.2f}`"
            send_telegram(msg)
        elif rsi > 70 and prev_rsi <= 70:
            msg = f"🔴 *FOYDANI OLISH / SOTISH (SELL)*\n\n📊 *Aktiv:* {name}\n💵 *Narx:* `{price:.2f}`\n⚠️ *RSI:* `{rsi:.1f}`"
            send_telegram(msg)
        else:
            print(f"[{name}] Narx: {price:.2f} | RSI: {rsi:.1f} | Kutilmoqda...")

    except Exception as e:
        print(f"Xatolik ({name}): {e}")

def daily_morning_report():
    msg = "☀️ *Xayrli tong!*\nBot serverda 24/7 faol ishlamoqda.\n\n📊 *Joriy bozor holati:*\n"
    for asset in WATCHLIST:
        data = get_market_data(asset["ticker"])
        if data:
            msg += f"▫️ *{asset['name']}:* Narx: `{data['price']:.2f}` | RSI: `{data['rsi']:.1f}`\n"
    msg += "\n🔍 *Bozor to'liq nazorat ostida!*"
    send_telegram(msg)

def listen_for_commands():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            resp = requests.get(url, timeout=35).json()
            if "result" in resp:
                for update in resp["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].strip()
                        sender_id = str(update["message"]["chat"]["id"])

                        if sender_id == CHAT_ID:
                            if text in ["/status", "status", "/holat"]:
                                status_msg = "⚡ *Joriy bozor holati va narxlar:*\n\n"
                                for asset in WATCHLIST:
                                    data = get_market_data(asset["ticker"])
                                    if data:
                                        status_msg += f"📌 *{asset['name']}*\n💵 Narx: `{data['price']:.2f}`\n📊 RSI (H1): `{data['rsi']:.1f}`\n\n"
                                status_msg += "✅ *Bot faol ishlamoqda.*"
                                send_telegram(status_msg)
                            elif text in ["/start"]:
                                send_telegram("👋 Salom! Bot aloqada. Bozor holatini bilish uchun **/status** deb yozing.")
        except Exception:
            time.sleep(2)
        time.sleep(1)

def main_job():
    print(f"\n--- Bozor tekshiruvi: {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    for asset in WATCHLIST:
        check_asset(asset)

schedule.every(15).minutes.do(main_job)
schedule.every().day.at("08:00").do(daily_morning_report)

if __name__ == "__main__":
    send_telegram("🤖 *Bot yangilandi va portga ulandi!*\nServer endi to'xtamaydi. **/status** buyrug'i faol.")

    # Render portini ushlab turish uchun veb-serverni ishga tushirish
    threading.Thread(target=run_web_server, daemon=True).start()

    # Telegram buyruqlarini tinglash
    threading.Thread(target=listen_for_commands, daemon=True).start()

    main_job()
    while True:
        schedule.run_pending()
        time.sleep(1)
