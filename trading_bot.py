import os
import time
import datetime
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
ESKIZ_EMAIL = "sardorbekegamnazarov788@gmail.com"       # Eskiz.uz emailingiz
ESKIZ_PASSWORD = "70487"   # Eskiz.uz parolingiz
PHONE_NUMBER = "998503032355"                 # Telefon raqamingiz
# ==========================================

# 7 ta asosiy aktiv
WATCHLIST = [
    {"name": "OLTIN (XAU/USD)", "ticker": "GC=F", "is_usd": True},
    {"name": "KUMUSH (XAG/USD)", "ticker": "SI=F", "is_usd": True},
    {"name": "NEFT (Crude Oil WTI)", "ticker": "CL=F", "is_usd": False},
    {"name": "GBP/USD", "ticker": "GBPUSD=X", "is_usd": True},
    {"name": "EUR/USD", "ticker": "EURUSD=X", "is_usd": True},
    {"name": "USD/JPY", "ticker": "USDJPY=X", "is_usd": True},
    {"name": "AUD/USD", "ticker": "AUDUSD=X", "is_usd": True}
]

last_processed_candle = {}
today_high_impact_news = []
news_warning_sent = False
last_usd_signal_time = None  # Korrelyatsiyani cheklash uchun

# Render portini ushlab turuvchi veb-server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Trading bot (Multi-TF + News + Sessions + Price Action) is running 24/7!")

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
    try:
        login_url = "https://notify.eskiz.uz/api/auth/login"
        login_data = {"email": ESKIZ_EMAIL, "password": ESKIZ_PASSWORD}
        resp = requests.post(login_url, data=login_data, timeout=10)
        if resp.status_code != 200:
            print("Eskiz login xatosi:", resp.text)
            return

        token = resp.json().get("data", {}).get("token")
        if not token:
            return

        sms_url = "https://notify.eskiz.uz/api/message/sms/send"
        headers = {"Authorization": f"Bearer {token}"}
        sms_payload = {
            "mobile_phone": PHONE_NUMBER,
            "message": text,
            "from": "4546"
        }
        res_sms = requests.post(sms_url, data=sms_payload, headers=headers, timeout=10)
        print("Eskiz SMS holati:", res_sms.status_code)
    except Exception as e:
        print(f"SMS xatoligi: {e}")

def is_active_trading_session():
    """1-FILTR: London va Nyu-York faol soatlari (Toshkent vaqti bilan 13:00 dan 22:30 gacha)"""
    # Toshkent UTC+5
    tashkent_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5)
    hour = tashkent_now.hour
    minute = tashkent_now.minute

    # 13:00 dan 22:30 gacha
    if 13 <= hour < 22:
        return True
    elif hour == 22 and minute <= 30:
        return True
    return False

def update_economic_calendar():
    """ForexFactory yangiliklar taqvimi"""
    global today_high_impact_news
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            events = resp.json()
            parsed_news = []
            for ev in events:
                impact = ev.get('impact', '')
                title = ev.get('title', '')
                date_str = ev.get('date', '')

                if impact == 'High' or 'Crude Oil Inventories' in title:
                    try:
                        dt = datetime.datetime.fromisoformat(date_str)
                        parsed_news.append({
                            "title": title,
                            "country": ev.get('country', ''),
                            "time": dt
                        })
                    except Exception:
                        continue
            today_high_impact_news = parsed_news
            print(f"Taqvim yangilandi: {len(today_high_impact_news)} ta muhim yangilik aniqlandi.")
    except Exception as e:
        print(f"Taqvim yuklash xatosi: {e}")

def is_news_time():
    """Yangiliklar vaqtini tekshirish"""
    global news_warning_sent
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    for item in today_high_impact_news:
        news_dt = item["time"]
        diff_minutes = (news_dt - now_utc).total_seconds() / 60.0

        if -30 <= diff_minutes <= 30:
            if not news_warning_sent and diff_minutes > 0:
                msg = (
                    f"⚠️ *IQTISODIY TAQVIM OGOHLANTIRISHI:*\n\n"
                    f"📢 *Yangilik:* {item['title']} ({item['country']})\n"
                    f"⏳ *Qolgan vaqt:* taxminan `{int(diff_minutes)}` daqiqa\n\n"
                    f"🛡 *Xavfsizlik chorasi:* Yangi signallar berish vaqtincha to'xtatildi!"
                )
                send_telegram(msg)
                news_warning_sent = True
            return True, item['title']

    if news_warning_sent:
        send_telegram("✅ *Muhim yangiliklar davri yakunlandi.* Bozor barqarorlashdi, oddiy tahlil rejimi qayta yoqildi.")
        news_warning_sent = False

    return False, None

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

    # 3-FILTR: Price Action (Sham shakllari hisobi)
    c_open = float(closed['Open'])
    c_close = float(closed['Close'])
    c_high = float(closed['High'])
    c_low = float(closed['Low'])
    body = abs(c_close - c_open)
    total_range = c_high - c_low if (c_high - c_low) > 0 else 0.0001
    lower_shadow = (c_open - c_low) if c_close >= c_open else (c_close - c_low)
    upper_shadow = (c_high - c_close) if c_close >= c_open else (c_high - c_open)

    # Oldingi shamcha ma'lumotlari
    p_open = float(prev_closed['Open'])
    p_close = float(prev_closed['Close'])

    # Bullish tasdiq: Bolg'acha (Hammer/Pin-bar) yoki Yutib yuborish (Bullish Engulfing)
    is_bullish_pa = (lower_shadow >= (body * 1.5) and lower_shadow >= (total_range * 0.4)) or \
                    (c_close > c_open and p_close < p_open and c_close >= p_open and c_open <= p_close)

    # Bearish tasdiq: Shooting Star yoki Yutib yuborish (Bearish Engulfing)
    is_bearish_pa = (upper_shadow >= (body * 1.5) and upper_shadow >= (total_range * 0.4)) or \
                    (c_close < c_open and p_close > p_open and c_open >= p_close and c_close <= p_open)

    return {
        "time": candle_time,
        "price": c_close,
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
        "is_bullish_pa": is_bullish_pa,
        "is_bearish_pa": is_bearish_pa
    }

def check_asset(asset: dict):
    global last_usd_signal_time

    # 1. Savdo soatlari tekshiruvi (London va Nyu-York)
    if not is_active_trading_session():
        return

    # 2. Yangiliklar vaqti tekshiruvi
    in_news, news_name = is_news_time()
    if in_news:
        return

    name = asset["name"]
    ticker = asset["ticker"]
    is_usd = asset.get("is_usd", False)

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
        is_bullish_pa = data["is_bullish_pa"]
        is_bearish_pa = data["is_bearish_pa"]

        # BUY shartlari (H1 indikatorlari + Price Action)
        h1_buy = (
            price > ema200 and
            price <= (bb_low * 1.01) and
            prev_rsi < 40 and rsi >= 40 and
            prev_macd <= prev_macd_signal and macd > macd_signal and
            is_bullish_pa
        )

        # SELL shartlari (H1 indikatorlari + Price Action)
        h1_sell = (
            price >= (bb_high * 0.99) and
            rsi > 70 and
            prev_macd >= prev_macd_signal and macd < macd_signal and
            is_bearish_pa
        )

        sl_distance = atr * 1.5
        tp_distance = atr * 3.0

        now_timestamp = time.time()

        # BUY signali
        if h1_buy and h4_trend == "UP" and d1_trend == "UP":
            # 2-FILTR: Dollar korrelyatsiyasi nazorati (Oxirgi 60 daqiqada USD signal bo'lmagan bo'lishi kerak)
            if is_usd and last_usd_signal_time and (now_timestamp - last_usd_signal_time < 3600):
                print(f"[{name}] Korrelyatsiya filtri: Yaqinda USD signali berilgan, o'tkazib yuborildi.")
                return

            sl_price = price - sl_distance
            tp_price = price + tp_distance

            w1_extra = ""
            if w1_trend == "UP":
                w1_extra = "\n🔥 *MAXSUS:* W1 (Haftalik) global trendi ham to'liq tasdiqlandi!"

            msg = (
                f"🟢 *KUCHLI SIGNAL: SAVDOGA KIRISH (BUY)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Kirish narxi:* `{price:.4f}`\n\n"
                f"🎯 *Take Profit (TP):* `{tp_price:.4f}`\n"
                f"🛑 *Stop Loss (SL):* `{sl_price:.4f}`\n"
                f"⚖️ *Risk/Reward:* 1:2 nisbatda\n\n"
                f"🕯 *Price Action:* Shamcha o'sishga tasdiq berdi (Pin-bar/Engulfing)\n"
                f"📈 *H1 holati:* RSI `{rsi:.1f}`, MACD yuqoriga\n"
                f"🧭 *Trendlar:* H4 [🟢 UP] | D1 [🟢 UP]{w1_extra}\n"
                f"🕒 *Sessiya:* Faol likvidlik soatlari (13:00 - 22:30)"
            )
            send_telegram(msg)
            send_sms_eskiz("Bu Eskizdan test")
            print(f"[{name}] KUCHLI BUY signali yuborildi.")
            last_processed_candle[ticker] = candle_time
            if is_usd:
                last_usd_signal_time = now_timestamp

        # SELL signali
        elif h1_sell and h4_trend == "DOWN" and d1_trend == "DOWN":
            if is_usd and last_usd_signal_time and (now_timestamp - last_usd_signal_time < 3600):
                print(f"[{name}] Korrelyatsiya filtri: Yaqinda USD signali berilgan, o'tkazib yuborildi.")
                return

            sl_price = price + sl_distance
            tp_price = price - tp_distance

            w1_extra = ""
            if w1_trend == "DOWN":
                w1_extra = "\n🔥 *MAXSUS:* W1 (Haftalik) global trendi ham to'liq tasdiqlandi!"

            msg = (
                f"🔴 *KUCHLI SIGNAL: SOTISH (SELL)*\n\n"
                f"📊 *Aktiv:* {name}\n"
                f"💵 *Kirish narxi:* `{price:.4f}`\n\n"
                f"🎯 *Take Profit (TP):* `{tp_price:.4f}`\n"
                f"🛑 *Stop Loss (SL):* `{sl_price:.4f}`\n"
                f"⚖️ *Risk/Reward:* 1:2 nisbatda\n\n"
                f"🕯 *Price Action:* Shamcha pasayishga tasdiq berdi (Shooting Star/Engulfing)\n"
                f"⚠️ *H1 holati:* RSI `{rsi:.1f}`, MACD pasayishga\n"
                f"🧭 *Trendlar:* H4 [🔴 DOWN] | D1 [🔴 DOWN]{w1_extra}\n"
                f"🕒 *Sessiya:* Faol likvidlik soatlari (13:00 - 22:30)"
            )
            send_telegram(msg)
            send_sms_eskiz("Bu Eskizdan test")
            print(f"[{name}] KUCHLI SELL signali yuborildi.")
            last_processed_candle[ticker] = candle_time
            if is_usd:
                last_usd_signal_time = now_timestamp
        else:
            print(f"[{name}] H1: {price:.2f} | H4: {h4_trend} | D1: {d1_trend} | Kutilmoqda...")

    except Exception as e:
        print(f"Xatolik ({name}): {e}")

def daily_morning_report():
    msg = "☀️ *Xayrli tong!*\nBot to'liq himoyalangan (Multi-TF + News + Sessiya + Price Action) rejimida faol.\n\n📊 *Bozor holati:*\n"
    for asset in WATCHLIST:
        data = get_market_data(asset["ticker"])
        trends = get_higher_tf_trend(asset["ticker"])
        if data:
            msg += f"▫️ *{asset['name']}:* `{data['price']:.4f}` (H4: {trends['H4']} | D1: {trends['D1']})\n"
    msg += "\n🕒 *Faol savdo soatlari:* Toshkent vaqti bilan 13:00 da boshlanadi!"
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
                                in_news, news_name = is_news_time()
                                session_ok = is_active_trading_session()
                                session_status = "🟢 Faol (London/NY)" if session_ok else "🌙 Passiv soat (Kutilmoqda)"
                                news_status = f"⚠️ Xavfli yangilik: {news_name}" if in_news else "🟢 Tinch"

                                status_msg = (
                                    f"⚡ *Bozor va Tizim holati:*\n"
                                    f"🕒 *Sessiya holati:* {session_status}\n"
                                    f"📰 *Yangiliklar:* {news_status}\n\n"
                                )
                                for asset in WATCHLIST:
                                    data = get_market_data(asset["ticker"])
                                    trends = get_higher_tf_trend(asset["ticker"])
                                    if data:
                                        status_msg += (
                                            f"📌 *{asset['name']}*\n"
                                            f"💵 Narx: `{data['price']:.4f}`\n"
                                            f"📊 RSI: `{data['rsi']:.1f}` | MACD: `{data['macd']:.2f}`\n"
                                            f"🧭 Trend: H4 [{trends['H4']}] | D1 [{trends['D1']}] | W1 [{trends['W1']}]\n\n"
                                        )
                                status_msg += "✅ *Price Action va Korrelyatsiya nazorati faol.*"
                                send_telegram(status_msg)
                            elif text in ["/start"]:
                                send_telegram("👋 Salom! Mukammallashtirilgan savdo boti aloqada. Holat uchun **/status** deb yozing.")
        except Exception:
            time.sleep(2)
        time.sleep(1)

def main_job():
    print(f"\n--- Bozor tekshiruvi: {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    for asset in WATCHLIST:
        check_asset(asset)

# Taqvim har 4 soatda yangilanadi, tekshiruv har 15 daqiqada
schedule.every(4).hours.do(update_economic_calendar)
schedule.every(15).minutes.do(main_job)
schedule.every().day.at("08:00").do(daily_morning_report)

if __name__ == "__main__":
    send_telegram("💎 *Bot eng yuqori darajaga yetkazildi!*\nQo'shildi: Savdo soatlari filtri (13:00 - 22:30), Dollar korrelyatsiyasi nazorati va Price Action (Pin-bar/Engulfing) tasdig'i.")

    update_economic_calendar()

    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=listen_for_commands, daemon=True).start()

    main_job()
    while True:
        schedule.run_pending()
        time.sleep(1)
