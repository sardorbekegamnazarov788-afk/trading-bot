import time
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

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Telegramga jo'natishda xatolik: {e}")

def check_asset(asset: dict):
    name = asset["name"]
    ticker = asset["ticker"]
    try:
        df = yf.download(ticker, period="1mo", interval="1h", progress=False)
        if df.empty or len(df) < 200:
            return

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi()
        df['EMA_200'] = EMAIndicator(close=df['Close'], window=200).ema_indicator()
        df['EMA_50'] = EMAIndicator(close=df['Close'], window=50).ema_indicator()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        price = float(last['Close'])
        rsi = float(last['RSI'])
        prev_rsi = float(prev['RSI'])
        ema200 = float(last['EMA_200'])
        ema50 = float(last['EMA_50'])
        prev_ema50 = float(prev['EMA_50'])
        prev_ema200 = float(prev['EMA_200'])

        if price > ema200 and prev_rsi < 35 and rsi >= 35:
            msg = f"🟢 *SAVDOGA KIRISH (BUY)*\n\n📊 *Aktiv:* {name}\n💵 *Narx:* `{price:.2f}`\n📈 *RSI:* `{rsi:.1f}`"
            send_telegram(msg)
            print(f"[{name}] BUY signali yuborildi.")
        elif prev_ema50 <= prev_ema200 and ema50 > ema200:
            msg = f"🚀 *KUCHLI BUY (Golden Cross)*\n\n📊 *Aktiv:* {name}\n💵 *Narx:* `{price:.2f}`"
            send_telegram(msg)
            print(f"[{name}] Golden Cross yuborildi.")
        elif rsi > 70 and prev_rsi <= 70:
            msg = f"🔴 *FOYDANI OLISH / SOTISH (SELL)*\n\n📊 *Aktiv:* {name}\n💵 *Narx:* `{price:.2f}`\n⚠️ *RSI:* `{rsi:.1f}`"
            send_telegram(msg)
            print(f"[{name}] SELL signali yuborildi.")
        else:
            print(f"[{name}] Narx: {price:.2f} | RSI: {rsi:.1f} | Kutilmoqda...")
    except Exception as e:
        print(f"Xatolik ({name}): {e}")

def main_job():
    print(f"\n--- Bozor tekshiruvi: {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    for asset in WATCHLIST:
        check_asset(asset)

schedule.every(15).minutes.do(main_job)

if __name__ == "__main__":
    send_telegram("🤖 *Savdo signallari boti serverda ishga tushdi!*\nBozor monitoringi boshlandi.")
    main_job()
    while True:
        schedule.run_pending()
        time.sleep(1)
