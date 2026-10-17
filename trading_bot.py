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
from ta.volatility import BollingerBands, AverageTrueRange

BOT_TOKEN = "8673591792:AAFSHOgBQerGUy8trOQpCgD_8casDTqn4uw"
CHAT_ID = "8355121174"

WATCHLIST = [
    {"name": "OLTIN (XAU/USD)", "ticker": "GC=F"},
    {"name": "BITCOIN (BTC/USD)", "ticker": "BTC-USD"},
    {"name": "ETHEREUM (ETH/USD)", "ticker": "ETH-USD"},
    {"name": "EUR/USD", "ticker": "EURUSD=X"}
]

# Bir xil signalni qayta-qayta yubormaslik uchun oxirgi sham vaqtini saqlash
last_processed_candle = {}

# Render portini ushlab turuvchi veb-server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Trading bot (Closed Candles Only) is running 24/7!")

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
        print(f"Telegramga jo'natishda xatolik: {e}")

def get_market_data(ticker: str):
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    if df.empty or len(df) < 200:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Indikatorlarni hisoblash
    df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi()
    df['EMA_200'] = EMAIndicator(close=df['Close'], window=200).ema_indicator()

    bb = BollingerBands(close=df['Close'], window=20, window_dev=2)
    df['BB_HIGH'] = bb.bollinger_hband()
    df['BB_LOW'] = bb.bollinger_lband()

    macd = MACD(close=df['Close'], window_fast=12, window_slow=26, window_sign=9)
    df['MACD'] = macd.macd()
    df['MACD_SIGNAL'] = macd.macd_signal()

    atr = AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14)
    df['ATR'] = atr.average_true_range()

    # DIQQAT: iloc[-1] hozir ochiq turgan sham, iloc[-2] esa TO'LIQ YOPILGAN oxirgi shamcha
    closed = df.iloc[-2]
    prev_closed = df.iloc[-3]
    candle_time = str(df.index[-2])

    return {
        "time": candle_time,
        "price": float(closed['Close']),
        "rsi": float(closed['RSI']),
        "prev_rsi": float(prev_closed['RSI']),
        "ema200": float(closed['EMA_200']),
        "bb_low": float(closed['BB_LOW']),
        "bb_high": float(closed['BB_HIGH']),
        "macd": float(closed['MACD']),
        "macd_signal": float(closed['MACD_SIGNAL']),
        "prev_macd": float(prev_closed['MACD']),
        "prev_macd_signal": float(prev_closed['MACD_SIGNAL']),
        "atr": float(closed['ATR']),
        "live_price": float(df.iloc[-1]['Close'])
    }

def check_asset(asset: dict):
    name = asset["name"]
    ticker = asset["ticker"]
    try:
        data = get_market_data(ticker)
        if not data:
            return

        candle_time = data["time"]
        # Agar ushbu yopilgan shamcha bo'yicha allaqachon tekshirilgan bo'lsa, qayta signal bermaydi
        if last_processed_candle.get(ticker) == candle_time:
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
        atr = data["atr"]

        # YOPILGAN SHAM BO'YICHA BUY SHARTLARI
        is_buy = (
            price > ema200 and
            price <= (bb_low * 1.01) and
            prev_rsi < 40 and rsi >= 40 and
            prev_macd <= prev_macd_signal and macd > macd_signal
        )

        # YOPILGAN SHAM BO'YICHA SELL SHARTLARI
        is_sell = (
            price >= (bb_high * 0.99) and
            rsi > 70 and
            prev_macd >= prev_macd_signal and macd < macd_signal
        )

        # SL va TP hisobi (1:2 Risk/Reward)
        sl_distance = atr * 1.5
        tp_distance = atr * 3.0

        if is_buy:
            sl_price = price - sl_distance
            tp_price = price + tp_distance
            msg = (
                f"🟢 *KUCHLI BUY SIGNALI (Yopilgan H1 shamcha tasdig'i)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Kirish narxi:* `{price:.2f}`\n\n"
                f"🎯 *Take Profit (TP):* `{tp_price:.2f}`\n"
                f"🛑 *Stop Loss (SL):* `{sl_price:.2f}`\n"
                f"⚖️ *Risk/Reward:* 1:2 nisbatda\n\n"
                f"📈 *RSI (H1):* `{rsi:.1f}`\n"
                f"⚡ *MACD:* Yuqoriga kesishma to'liq tasdiqlandi\n"
                f"🌊 *Bollinger:* Pastki chegaradan qaytdi\n"
                f"🛡 *Trend:* 200 EMA ustida (Xavfsiz)"
            )
            send_telegram(msg)
            print(f"[{name}] Yopilgan shamcha bo'yicha BUY yuborildi.")
            last_processed_candle[ticker] = candle_time

        elif is_sell:
            sl_price = price + sl_distance
            tp_price = price - tp_distance
            msg = (
                f"🔴 *KUCHLI SELL SIGNALI (Yopilgan H1 shamcha tasdig'i)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Kirish narxi:* `{price:.2f}`\n\n"
                f"🎯 *Take Profit (TP):* `{tp_price:.2f}`\n"
                f"🛑 *Stop Loss (SL):* `{sl_price:.2f}`\n"
                f"⚖️ *Risk/Reward:* 1:2 nisbatda\n\n"
                f"⚠️ *RSI (H1):* `{rsi:.1f}`\n"
                f"⚡ *MACD:* Pasayish signali tasdiqlandi\n"
                f"🌊 *Bollinger:* Yuqori tasmaga yetdi"
            )
            send_telegram(msg)
            print(f"[{name}] Yopilgan shamcha bo'yicha SELL yuborildi.")
            last_processed_candle[ticker] = candle_time
        else:
            print(f"[{name}] Yopilgan sham ({candle_time[-8:]}) | Narx: {price:.2f} | RSI: {rsi:.1f} | Kutilmoqda...")

    except Exception as e:
        print(f"Xatolik ({name}): {e}")

def daily_morning_report():
    msg = "☀️ *Xayrli tong!*\nBot yopilgan shamchalar (H1) bo'yicha 24/7 faol ishlamoqda.\n\n📊 *Oxirgi yopilgan shamlar holati:*\n"
    for asset in WATCHLIST:
        data = get_market_data(asset["ticker"])
        if data:
            msg += f"▫️ *{asset['name']}:* Yopilish: `{data['price']:.2f}` | RSI: `{data['rsi']:.1f}`\n"
    msg += "\n🔍 *Tasdiqlangan signallar kutilmoqda!*"
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
                                status_msg = "⚡ *Joriy holat (Oxirgi yopilgan H1 shamcha bo'yicha):*\n\n"
                                for asset in WATCHLIST:
                                    data = get_market_data(asset["ticker"])
                                    if data:
                                        status_msg += (
                                            f"📌 *{asset['name']}*\n"
                                            f"💵 Yopilish narxi: `{data['price']:.2f}` (Joriy: `{data['live_price']:.2f}`)\n"
                                            f"📊 RSI: `{data['rsi']:.1f}` | MACD: `{data['macd']:.2f}`\n"
                                            f"🌊 BB Pastki: `{data['bb_low']:.2f}` | Yuqori: `{data['bb_high']:.2f}`\n\n"
                                        )
                                status_msg += "✅ *Faqat tasdiqlangan signallar yuboriladi.*"
                                send_telegram(status_msg)
                            elif text in ["/start"]:
                                send_telegram("👋 Salom! Bot yopilgan shamchalar rejimida ishlamoqda. Holatni bilish uchun **/status** deb yozing.")
        except Exception:
            time.sleep(2)
        time.sleep(1)

def main_job():
    print(f"\n--- Bozor tekshiruvi: {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    for asset in WATCHLIST:
        check_asset(asset)

# Har soat boshida yangi sham yopilishi bilan tekshiradi (va har 15 daqiqada nazorat qiladi)
schedule.every(15).minutes.do(main_job)
schedule.every().day.at("08:00").do(daily_morning_report)

if __name__ == "__main__":
    send_telegram("🔒 *Bot yangilandi: Faqat to'liq yopilgan shamchalar (H1) rejimi yoqildi!*\nEndi soxta chayqalishlar bo'lmaydi, har bir signal qat'iy tasdiqlanadi.")

    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=listen_for_commands, daemon=True).start()

    main_job()
    while True:
        schedule.run_pending()
        time.sleep(1)
