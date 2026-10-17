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

# Yangilangan aktivlar: Oltin, Neft, GBP/USD, EUR/USD
WATCHLIST = [
    {"name": "OLTIN (XAU/USD)", "ticker": "GC=F"},
    {"name": "NEFT (Crude Oil WTI)", "ticker": "CL=F"},
    {"name": "GBP/USD", "ticker": "GBPUSD=X"},
    {"name": "EUR/USD", "ticker": "EURUSD=X"}
]

last_processed_candle = {}

# Render portini ushlab turuvchi veb-server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Trading bot (Multi-TF: H1, H4, D1, W1) is running 24/7!")

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

def get_higher_tf_trend(ticker: str):
    """H4, D1 va W1 trendlarini aniqlash (200 EMA bo'yicha)"""
    trends = {"H4": "NEUTRAL", "D1": "NEUTRAL", "W1": "NEUTRAL"}
    try:
        # H4 trend
        df_h4 = yf.download(ticker, period="3mo", interval="1h", progress=False)
        if isinstance(df_h4.columns, pd.MultiIndex):
            df_h4.columns = df_h4.columns.get_level_values(0)
        if not df_h4.empty and len(df_h4) >= 200:
            ema200_h4 = EMAIndicator(close=df_h4['Close'], window=200).ema_indicator().iloc[-1]
            trends["H4"] = "UP" if df_h4['Close'].iloc[-1] > ema200_h4 else "DOWN"

        # D1 trend
        df_d1 = yf.download(ticker, period="1y", interval="1d", progress=False)
        if isinstance(df_d1.columns, pd.MultiIndex):
            df_d1.columns = df_d1.columns.get_level_values(0)
        if not df_d1.empty and len(df_d1) >= 200:
            ema200_d1 = EMAIndicator(close=df_d1['Close'], window=200).ema_indicator().iloc[-1]
            trends["D1"] = "UP" if df_d1['Close'].iloc[-1] > ema200_d1 else "DOWN"

        # W1 trend
        df_w1 = yf.download(ticker, period="2y", interval="1wk", progress=False)
        if isinstance(df_w1.columns, pd.MultiIndex):
            df_w1.columns = df_w1.columns.get_level_values(0)
        if not df_w1.empty and len(df_w1) >= 50:
            ema50_w1 = EMAIndicator(close=df_w1['Close'], window=50).ema_indicator().iloc[-1]
            trends["W1"] = "UP" if df_w1['Close'].iloc[-1] > ema50_w1 else "DOWN"

    except Exception as e:
        print(f"Trend xatoligi ({ticker}): {e}")

    return trends

def get_market_data(ticker: str):
    """H1 yopilgan shamcha bo'yicha indikatorlar"""
    df = yf.download(ticker, period="1mo", interval="1h", progress=False)
    if df.empty or len(df) < 200:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

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
        if last_processed_candle.get(ticker) == candle_time:
            return

        trends = get_higher_tf_trend(ticker)
        h4_trend = trends["H4"]
        d1_trend = trends["D1"]
        w1_trend = trends["W1"]

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

        # H1 texnik shartlari
        h1_buy = (
            price > ema200 and
            price <= (bb_low * 1.01) and
            prev_rsi < 40 and rsi >= 40 and
            prev_macd <= prev_macd_signal and macd > macd_signal
        )

        h1_sell = (
            price >= (bb_high * 0.99) and
            rsi > 70 and
            prev_macd >= prev_macd_signal and macd < macd_signal
        )

        # SL va TP (1:2 Risk/Reward)
        sl_distance = atr * 1.5
        tp_distance = atr * 3.0

        # BUY: H4 va D1 ham o'sishda (UP) bo'lishi kerak
        if h1_buy and h4_trend == "UP" and d1_trend == "UP":
            sl_price = price - sl_distance
            tp_price = price + tp_distance

            w1_extra = ""
            if w1_trend == "UP":
                w1_extra = "\n🔥 *MAXSUS:* W1 (Haftalik) global trendi ham to'liq tasdiqlandi (Maksimal ishonch)!"

            msg = (
                f"🟢 *KUCHLI SIGNAL: SAVDOGA KIRISH (BUY)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Kirish narxi:* `{price:.4f}`\n\n"
                f"🎯 *Take Profit (TP):* `{tp_price:.4f}`\n"
                f"🛑 *Stop Loss (SL):* `{sl_price:.4f}`\n"
                f"⚖️ *Risk/Reward:* 1:2 nisbatda\n\n"
                f"📈 *H1 holati:* RSI `{rsi:.1f}`, MACD yuqoriga\n"
                f"🧭 *Trendlar:* H4 [🟢 UP] | D1 [🟢 UP]{w1_extra}"
            )
            send_telegram(msg)
            print(f"[{name}] H4+D1 tasdiqlangan BUY yuborildi.")
            last_processed_candle[ticker] = candle_time

        # SELL: H4 va D1 ham pasayishda (DOWN) bo'lishi kerak
        elif h1_sell and h4_trend == "DOWN" and d1_trend == "DOWN":
            sl_price = price + sl_distance
            tp_price = price - tp_distance

            w1_extra = ""
            if w1_trend == "DOWN":
                w1_extra = "\n🔥 *MAXSUS:* W1 (Haftalik) global trendi ham to'liq tasdiqlandi (Maksimal ishonch)!"

            msg = (
                f"🔴 *KUCHLI SIGNAL: SOTISH (SELL)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Kirish narxi:* `{price:.4f}`\n\n"
                f"🎯 *Take Profit (TP):* `{tp_price:.4f}`\n"
                f"🛑 *Stop Loss (SL):* `{sl_price:.4f}`\n"
                f"⚖️ *Risk/Reward:* 1:2 nisbatda\n\n"
                f"⚠️ *H1 holati:* RSI `{rsi:.1f}`, MACD pasayishga\n"
                f"🧭 *Trendlar:* H4 [🔴 DOWN] | D1 [🔴 DOWN]{w1_extra}"
            )
            send_telegram(msg)
            print(f"[{name}] H4+D1 tasdiqlangan SELL yuborildi.")
            last_processed_candle[ticker] = candle_time
        else:
            print(f"[{name}] H1 narx: {price:.2f} | H4: {h4_trend} | D1: {d1_trend} | W1: {w1_trend} | Kutilmoqda...")

    except Exception as e:
        print(f"Xatolik ({name}): {e}")

def daily_morning_report():
    msg = "☀️ *Xayrli tong!*\nBot Multi-Timeframe (H1, H4, D1, W1) rejimida faol.\n\n📊 *Bozor va Trendlar ko'rinishi:*\n"
    for asset in WATCHLIST:
        data = get_market_data(asset["ticker"])
        trends = get_higher_tf_trend(asset["ticker"])
        if data:
            msg += (
                f"▫️ *{asset['name']}:* `{data['price']:.2f}`\n"
                f"   Trend: H4 [{trends['H4']}] | D1 [{trends['D1']}] | W1 [{trends['W1']}]\n"
            )
    msg += "\n🔍 *Faqat global trend bo'yicha signallar kutilmoqda!*"
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
                                status_msg = "⚡ *Joriy bozor va Trendlar holati:*\n\n"
                                for asset in WATCHLIST:
                                    data = get_market_data(asset["ticker"])
                                    trends = get_higher_tf_trend(asset["ticker"])
                                    if data:
                                        status_msg += (
                                            f"📌 *{asset['name']}*\n"
                                            f"💵 Yopilish: `{data['price']:.4f}`\n"
                                            f"📊 RSI (H1): `{data['rsi']:.1f}` | MACD: `{data['macd']:.2f}`\n"
                                            f"🧭 Trend: H4 [{trends['H4']}] | D1 [{trends['D1']}] | W1 [{trends['W1']}]\n\n"
                                        )
                                status_msg += "✅ *Multi-TF filtri faol.*"
                                send_telegram(status_msg)
                            elif text in ["/start"]:
                                send_telegram("👋 Salom! Multi-TF (Oltin, Neft, GBP, EUR) savdo boti aloqada. Holatni bilish uchun **/status** deb yozing.")
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
    send_telegram("🏆 *Bot yangilandi: Oltin, Neft, GBP/USD, EUR/USD aktivlari o'rnatildi!*\nMulti-Timeframe (H1 + H4 + D1 + W1) filtrlari muvaffaqiyatli ishga tushdi.")

    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=listen_for_commands, daemon=True).start()

    main_job()
    while True:
        schedule.run_pending()
        time.sleep(1)
