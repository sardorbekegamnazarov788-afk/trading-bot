import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import schedule
import yfinance as yf
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands

BOT_TOKEN = "8673591792:AAFSHOgBQerGUy8trOQpCgD_8casDTqn4uw"
CHAT_ID = "8355121174"

WATCHLIST = [
    {"name": "OLTIN (XAU/USD)", "ticker": "GC=F"},
    {"name": "BITCOIN (BTC/USD)", "ticker": "BTC-USD"},
    {"name": "ETHEREUM (ETH/USD)", "ticker": "ETH-USD"},
    {"name": "EUR/USD", "ticker": "EURUSD=X"}
]

# Render portini ushlab turuvchi veb-server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Trading bot with MACD and Bollinger Bands is running 24/7!")

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

    # 1. RSI (14)
    df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi()

    # 2. Trend (EMA 200 va EMA 50)
    df['EMA_200'] = EMAIndicator(close=df['Close'], window=200).ema_indicator()
    df['EMA_50'] = EMAIndicator(close=df['Close'], window=50).ema_indicator()

    # 3. Bollinger Bands (20, std=2)
    bb = BollingerBands(close=df['Close'], window=20, window_dev=2)
    df['BB_HIGH'] = bb.bollinger_hband()
    df['BB_LOW'] = bb.bollinger_lband()

    # 4. MACD (12, 26, 9)
    macd = MACD(close=df['Close'], window_fast=12, window_slow=26, window_sign=9)
    df['MACD'] = macd.macd()
    df['MACD_SIGNAL'] = macd.macd_signal()
    df['MACD_DIFF'] = macd.macd_diff()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "price": float(last['Close']),
        "rsi": float(last['RSI']),
        "prev_rsi": float(prev['RSI']),
        "ema200": float(last['EMA_200']),
        "bb_low": float(last['BB_LOW']),
        "bb_high": float(last['BB_HIGH']),
        "macd": float(last['MACD']),
        "macd_signal": float(last['MACD_SIGNAL']),
        "prev_macd": float(prev['MACD']),
        "prev_macd_signal": float(prev['MACD_SIGNAL']),
        "macd_diff": float(last['MACD_DIFF'])
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
        bb_low = data["bb_low"]
        bb_high = data["bb_high"]
        macd = data["macd"]
        macd_signal = data["macd_signal"]
        prev_macd = data["prev_macd"]
        prev_macd_signal = data["prev_macd_signal"]

        # 🟢 YUQORI ANIKLIKDAGI BUY SIGNALI:
        # Shart 1: Narx 200 EMA ustida (Trend o'sishda)
        # Shart 2: Narx Bollinger Bands'ning pastki chegarasiga yaqin yoki undan qaytgan
        # Shart 3: RSI 30-40 oralig'idan yuqoriga qayrilyapti
        # Shart 4: MACD chizig'i Signal chizig'ini pastdan yuqoriga kesib o'tmoqda
        is_buy = (
            price > ema200 and
            price <= (bb_low * 1.01) and
            prev_rsi < 40 and rsi >= 40 and
            prev_macd <= prev_macd_signal and macd > macd_signal
        )

        # 🔴 YUQORI ANIKLIKDAGI SELL SIGNALI:
        # Shart 1: Narx Bollinger Bands yuqori chegarasiga yetgan/kesgan
        # Shart 2: RSI 70 dan baland (haddan tashqari qizigan)
        # Shart 3: MACD tepadan pastga qarab kesishmoqda
        is_sell = (
            price >= (bb_high * 0.99) and
            rsi > 70 and
            prev_macd >= prev_macd_signal and macd < macd_signal
        )

        if is_buy:
            msg = (
                f"🟢 *KUCHLI SIGNAL: SAVDOGA KIRISH (BUY)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Kirish narxi:* `{price:.2f}`\n"
                f"📈 *RSI (H1):* `{rsi:.1f}`\n"
                f"🌊 *Bollinger Bands:* Pastki tasmadan qaytish\n"
                f"⚡ *MACD:* Yuqoriga kesishma tasdiqlandi\n"
                f"🛡 *Trend:* 200 EMA ustida (Xavfsiz)"
            )
            send_telegram(msg)
            print(f"[{name}] KUCHLI BUY signali yuborildi.")
        elif is_sell:
            msg = (
                f"🔴 *KUCHLI SIGNAL: SOTISH / FOYDANI YOPISH (SELL)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Chiqish narxi:* `{price:.2f}`\n"
                f"⚠️ *RSI (H1):* `{rsi:.1f}`\n"
                f"🌊 *Bollinger Bands:* Yuqori chegaraga yetdi\n"
                f"⚡ *MACD:* Pasayish signali tasdiqlandi"
            )
            send_telegram(msg)
            print(f"[{name}] KUCHLI SELL signali yuborildi.")
        else:
            print(f"[{name}] Narx: {price:.2f} | RSI: {rsi:.1f} | MACD: {macd:.2f} | Kutilmoqda...")

    except Exception as e:
        print(f"Xatolik ({name}): {e}")

def daily_morning_report():
    msg = "☀️ *Xayrli tong!*\nBot to'liq filtrlash rejimida faol ishlamoqda.\n\n📊 *Joriy bozor holati (H1):*\n"
    for asset in WATCHLIST:
        data = get_market_data(asset["ticker"])
        if data:
            msg += f"▫️ *{asset['name']}:* `{data['price']:.2f}` | RSI: `{data['rsi']:.1f}` | MACD: `{data['macd']:.2f}`\n"
    msg += "\n🔍 *Kuchli signallar kutilmoqda!*"
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
                                status_msg = "⚡ *Joriy bozor holati (Kuchaytirilgan indikatorlar):*\n\n"
                                for asset in WATCHLIST:
                                    data = get_market_data(asset["ticker"])
                                    if data:
                                        status_msg += (
                                            f"📌 *{asset['name']}*\n"
                                            f"💵 Narx: `{data['price']:.2f}`\n"
                                            f"📊 RSI: `{data['rsi']:.1f}` | MACD: `{data['macd']:.2f}`\n"
                                            f"🌊 BB Pastki: `{data['bb_low']:.2f}` | Yuqori: `{data['bb_high']:.2f}`\n\n"
                                        )
                                status_msg += "✅ *Tahlil davom etmoqda.*"
                                send_telegram(status_msg)
                            elif text in ["/start"]:
                                send_telegram("👋 Salom! Kuchaytirilgan savdo boti aloqada. Holatni ko'rish uchun **/status** deb yozing.")
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
    send_telegram("🚀 *Bot yangilandi: MACD va Bollinger Bands qo'shildi!*\nSignallar sifati va filtri maksimal darajaga ko'tarildi.")

    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=listen_for_commands, daemon=True).start()

    main_job()
    while True:
        schedule.run_pending()
        time.sleep(1)
