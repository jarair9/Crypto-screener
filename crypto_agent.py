import streamlit as st
import pandas as pd
import requests
import ta
from concurrent.futures import ThreadPoolExecutor

st.set_page_config("Crypto Screener", layout="wide")
st.title("📉 Crypto Screener")

# === Filters ===
col1, col2, col3 = st.columns(3)
with col1:
    timeframe = st.selectbox("Timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"])
with col2:
    rsi_mode = st.selectbox("RSI Condition", ["Below", "Above"])
with col3:
    rsi_threshold = st.slider("RSI Threshold", 10, 90, 30 if rsi_mode == "Below" else 70)

# === Optional Toggles ===
top100_volume = st.checkbox("✅ Only Top 100 by 24h Volume (Binance)", value=False)
new_listings = st.checkbox("🆕 Only Newly Listed Coins (last 30 days)", value=False)
market_cap_filter = st.checkbox("💰 Use Market Cap Filter", value=False)

min_cap, max_cap = 0, 999_999_999_999
if market_cap_filter:
    min_cap, max_cap = st.slider("Market Cap Range ($)", 0, 10_000_000_000, (50_000_000, 500_000_000), step=10_000_000)

start = st.button("🚀 Start RSI Scan")

# === External Coin Data ===
@st.cache_data(show_spinner=False)
def get_coin_gecko_data():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 250,
        "page": 1,
        "sparkline": False
    }
    response = requests.get(url, params=params)
    data = response.json()
    df = pd.DataFrame(data)

    # Fix: Convert time & add symbol_uc
    df["last_updated"] = pd.to_datetime(df["last_updated"], errors="coerce", utc=True)
    df["symbol_uc"] = df["symbol"].str.upper() + "USDT"

    return df[["id", "symbol_uc", "market_cap", "total_volume", "name", "last_updated"]]


@st.cache_data(show_spinner=False)
def get_binance_symbols():
    try:
        url = "https://api.binance.com/api/v3/exchangeInfo"
        response = requests.get(url, timeout=10)
        data = response.json()

        # Handle unexpected response
        if "symbols" not in data:
            st.error("❌ Binance API response missing 'symbols' key.")
            st.write("Response content:", data)
            return []

        return [
            s["symbol"] for s in data["symbols"]
            if s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
            and not any(x in s["symbol"] for x in ["UP", "DOWN", "BULL", "BEAR"])
        ]
    except Exception as e:
        st.error(f"⚠️ Failed to fetch Binance symbols: {e}")
        return []


def fetch_ohlcv(symbol, interval="15m", limit=200):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        data = requests.get(url, timeout=5).json()
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume", "_", "_", "_", "_", "_", "_"
        ])
        df["close"] = pd.to_numeric(df["close"])
        return df
    except:
        return None

def analyze(symbol, rsi_mode, rsi_threshold):
    df = fetch_ohlcv(symbol, timeframe)
    if df is None or df.empty:
        return None

    try:
        rsi_val = ta.momentum.RSIIndicator(df["close"]).rsi().iloc[-1]
        price = df["close"].iloc[-1]
        if pd.isna(rsi_val): return None

        if (rsi_mode == "Below" and rsi_val >= rsi_threshold) or \
           (rsi_mode == "Above" and rsi_val <= rsi_threshold):
            return None

        return {
            "Symbol": symbol,
            "Price": round(price, 4),
            "RSI": round(rsi_val, 2)
        }

    except:
        return None

# === Run Screener ===
# === Run Screener ===
if start:
    st.info("🌀 Gathering data...")
    binance_symbols = get_binance_symbols()
    gecko_df = get_coin_gecko_data()

    # === Filter: Top 100 Volume
    if top100_volume:
        top100 = gecko_df.sort_values("total_volume", ascending=False).head(100)
        binance_symbols = [s for s in binance_symbols if s in top100["symbol_uc"].values]

    # === Filter: Newly listed
    if new_listings:
        recent = gecko_df[
            gecko_df["last_updated"] > pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
        ]
        binance_symbols = [s for s in binance_symbols if s in recent["symbol_uc"].values]

    # === Filter: Market Cap Range
    if market_cap_filter:
        cap_range = gecko_df[
            (gecko_df["market_cap"] >= min_cap) & 
            (gecko_df["market_cap"] <= max_cap)
        ]
        binance_symbols = [s for s in binance_symbols if s in cap_range["symbol_uc"].values]

    st.write(f"🔍 Scanning {len(binance_symbols)} filtered USDT pairs...")

    results = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        for result in executor.map(lambda s: analyze(s, rsi_mode, rsi_threshold), binance_symbols):
            if result:
                results.append(result)

    if results:
        df = pd.DataFrame(results)
        df = df.sort_values("RSI", ascending=(rsi_mode == "Below"))
        st.success(f"✅ Found {len(df)} matching coins.")
        st.dataframe(df)
    else:
        st.warning("❌ No matching coins found. Try relaxing filters.")
