"""
Yahoo Finance Service — Provides 5-year historical OHLCV data for NSE stocks.
Uses yfinance library with disk caching to avoid repeated downloads.
"""

import yfinance as yf
import json
import os
import time
from datetime import datetime, timedelta

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".history_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Cache TTL: refresh if data is older than 6 hours
CACHE_TTL = 6 * 3600


def get_historical_data(symbol, period="5y"):
    """
    Fetch historical daily OHLCV data for an NSE stock.
    Returns list of {date, open, high, low, close, volume} dicts sorted by date ascending.
    Data is cached to disk and refreshed every 6 hours.
    """
    cache_file = os.path.join(CACHE_DIR, f"{symbol.upper()}_{period}.json")

    # Check cache
    if os.path.exists(cache_file):
        mtime = os.path.getmtime(cache_file)
        if time.time() - mtime < CACHE_TTL:
            try:
                with open(cache_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass  # corrupted cache, re-fetch

    # Fetch from Yahoo Finance (NSE stocks use .NS suffix)
    ticker = f"{symbol.upper()}.NS"
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval="1d")

        if df.empty:
            print(f"yfinance: No data for {ticker}")
            return _try_cache_fallback(cache_file)

        records = []
        for idx, row in df.iterrows():
            records.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })

        result = {"symbol": symbol.upper(), "data": records}

        # Write cache
        try:
            with open(cache_file, "w") as f:
                json.dump(result, f)
        except Exception as e:
            print(f"Cache write error for {symbol}: {e}")

        print(f"yfinance: Fetched {len(records)} records for {symbol} ({period})")
        return result

    except Exception as e:
        print(f"yfinance error for {ticker}: {e}")
        return _try_cache_fallback(cache_file)


def _try_cache_fallback(cache_file):
    """Return stale cache data if available, otherwise None."""
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
                print("Using stale cache as fallback")
                return data
        except Exception:
            pass
    return None
