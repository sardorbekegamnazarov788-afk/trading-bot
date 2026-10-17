ESKIZ_EMAIL = "sizning_eskiz_pochtangiz@gmail.com"  # Eskiz.uz ga kirgan emailingiz
ESKIZ_PASSWORD = "sizning_eskiz_parolingiz"        # Eskiz.uz parolingiz
PHONE_NUMBER = "998503032355"                       # SMS borishi kerak bo'lgan shaxsiy raqamingizimport os
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

# Telegram sozlamalari
BOT_TOKEN = "8673591792:AAFSHOgBQerGUy8trOQpCgD_8casDTqn4uw"
CHAT_ID = "8355121174"

# ==========================================
# 📱 ESKIZ.UZ SMS SOZLAMALARI:
ESKIZ_EMAIL = "SIZNING_ESKIZ_EMAILINGIZ"       # Eskiz.uz ro'yxatdan o'tgan pochta
ESKIZ_PASSWORD = "SIZNING_ESKIZ_PAROLINGIZ"   # Eskiz.uz paroli
PHONE_NUMBER = "998901234567"                 # SMS borishi kerak bo'lgan raqam (998 bilan)
# ==========================================

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
        self.wfile.write(b"Trading bot (Multi-TF + Eskiz SMS) is running 24/7!")

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
        print(f"Telegram xatoligi: {e}")

def send_sms_eskiz(text: str):
    """Eskiz.uz orqali to'g'ridan-to'g'ri telefonga SMS yuborish"""
    try:
        # 1. Avtorizatsiya tokenini olish
        login_url = "https://notify.eskiz.uz/api/auth/login"
        login_data = {"email": ESKIZ_EMAIL, "password": ESKIZ_PASSWORD}
        resp = requests.post(login_url, data=login_data, timeout=10)
        if resp.status_code != 200:
            print("Eskiz.uz login xatosi:", resp.text)
            return

        token = resp.json().get("data", {}).get("token")
        if not token:
            return

        # 2. SMS yuborish
        sms_url = "https://notify.eskiz.uz/api/message/sms/send"
        headers = {"Authorization": f"Bearer {token}"}
        sms_payload = {
            "mobile_phone": PHONE_NUMBER,
            "message": text,
            "from": "4546"  # Eskizning standart bepul yuboruvchi raqami
        }
        res_sms = requests.post(sms_url, data=sms_payload, headers=headers, timeout=10)
        print("Eskiz SMS natijasi:", res_sms.status_code)
    except Exception as e:
        print(f"SMS yuborishda xatolik: {e}")

def get_higher_tf_trend(ticker: str):
    trends = {"H4": "NEUTRAL", "D1": "NEUTRAL", "W1": "NEUTRAL"}
    try:
        df_h4 = yf.download(ticker, period="3mo", interval="1h", progress=False)
        if isinstance(df_h4.columns, pd.MultiIndex):
            df_h4.columns = df_h4.columns.get_level_values(0)
        if not df_h4.empty and len(df_h4) >= 200:
            ema200_h4 = EMAIndicator(close=df_h4['Close'], window=200).ema_indicator().iloc[-1]
            trends["H4"] = "UP" if df_h4['Close'].iloc[-1] > ema200_h4 else "DOWN"

        df_d1 = yf.download(ticker, period="1y", interval="1d", progress=False)
        if isinstance(df_d1.columns, pd.MultiIndex):
            df_d1.columns = df_d1.columns.get_level_values(0)
        if not df_d1.empty and len(df_d1) >= 200:
            ema200_d1 = EMAIndicator(close=df_d1['Close'], window=200).ema_indicator().iloc[-1]
            trends["D1"] = "UP" if df_d1['Close'].iloc[-1] > ema200_d1 else "DOWN"

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

        sl_distance = atr * 1.5
        tp_distance = atr * 3.0

        if h1_buy and h4_trend == "UP" and d1_trend == "UP":
            sl_price = price - sl_distance
            tp_price = price + tp_distance

            w1_extra = ""
            if w1_trend == "UP":
                w1_extra = "\n🔥 *MAXSUS:* W1 global trendi ham tasdiqlandi!"

            # Telegram xabari
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

            # Telefonga qisqa SMS yuborish
            sms_text = f"SIGNAL: BUY {name}! Narx: {price:.2f}, TP: {tp_price:.2f}, SL: {sl_price:.2f}. Tafsilot Telegramda!"
            send_sms_eskiz(sms_text)

            print(f"[{name}] BUY signali Telegram va SMS orqali yuborildi.")
            last_processed_candle[ticker] = candle_time

        elif h1_sell and h4_trend == "DOWN" and d1_trend == "DOWN":
            sl_price = price + sl_distance
            tp_price = price - tp_distance

            w1_extra = ""
            if w1_trend == "DOWN":
                w1_extra = "\n🔥 *MAXSUS:* W1 global trendi ham tasdiqlandi!"

            # Telegram xabari
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

            # Telefonga qisqa SMS yuborish
            sms_text = f"SIGNAL: SELL {name}! Narx: {price:.2f}, TP: {tp_price:.2f}, SL: {sl_price:.2f}. Tafsilot Telegramda!"
            send_sms_eskiz(sms_text)

            print(f"[{name}] SELL signali Telegram va SMS orqali yuborildi.")
            last_processed_candle[ticker] = candle_time
        else:
            print(f"[{name}] H1: {price:.2f} | H4: {h4_trend} | D1: {d1_trend} | Kutilmoqda...")

    except Exception as e:
        print(f"Xatolik ({name}): {e}")

def daily_morning_report():
    msg = "☀️ *Xayrli tong!*\nBot Multi-Timeframe (SMS integratsiyasi bilan) faol ishlamoqda.\n\n📊 *Bozor holati:*\n"
    for asset in WATCHLIST:
        data = get_market_data(asset["ticker"])
        trends = get_higher_tf_trend(asset["ticker"])
        if data:
            msg += f"▫️ *{asset['name']}:* `{data['price']:.2f}` (H4: {trends['H4']} | D1: {trends['D1']})\n"
    msg += "\n🔍 *Signallar nazorat ostida!*"
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
                                status_msg += "✅ *SMS xizmati (Eskiz.uz) ulangan.*"
                                send_telegram(status_msg)
                            elif text in ["/start"]:
                                send_telegram("👋 Salom! SMS ulangan savdo boti aloqada. Holatni bilish uchun **/status** deb yozing.")
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
    send_telegram("📲 *Bot yangilandi: Eskiz.uz SMS tizimi qo'shildi!*\nEndi signallar ham Telegramga, ham telefoningizga SMS bo'lib boradi.")

    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=listen_for_commands, daemon=True).start()

    main_job()
    while True:
        schedule.run_pending()
        time.sleep(1)
