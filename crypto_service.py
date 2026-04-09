"""
Crypto Service — Fetches live price data for top 10 cryptocurrencies via yfinance.
Optimized for 24/7 fast polling (returns cached data if polled too rapidly to avoid bans).
"""

import yfinance as yf
import time
import threading

# Top 10 Cryptos (excluding stablecoins for active trading)
CRYPTO_SYMBOLS = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "TRX-USD", "DOT-USD"
]

class CryptoService:
    def __init__(self):
        self._cache = {}
        self._cache_time = 0
        self._lock = threading.Lock()
        self.CACHE_TTL = 10  # 10 seconds cache to prevent spamming yfinance

    def get_live_quotes(self):
        """Fetch live quotes for all top 10 cryptos."""
        with self._lock:
            if time.time() - self._cache_time < self.CACHE_TTL and self._cache:
                return self._cache

        quotes = {}
        # We can use yf.download for batch, but history on individual is sometimes more reliable
        # Let's use yf.download to grab all 10 at once for speed
        try:
            # interval = 1m gives the most recent price
            data = yf.download(CRYPTO_SYMBOLS, period="1d", interval="1m", progress=False)
            
            # Download returns a multi-index DataFrame
            if not data.empty:
                close_df = data['Close'].ffill().bfill()
                close_prices = close_df.iloc[-1]
                prev_close = close_df.iloc[0]
                
                if 'Volume' in data:
                    vol_df = data['Volume'].ffill().bfill()
                    volumes = vol_df.iloc[-1]
                else:
                    volumes = None
                
                for sym in CRYPTO_SYMBOLS:
                    try:
                        price = float(close_prices[sym])
                        if price > 0: # filter out NaNs
                            open_p = float(prev_close[sym])
                            change = price - open_p
                            pChange = (change / open_p) * 100 if open_p > 0 else 0
                            
                            vol = float(volumes[sym]) if volumes is not None else 0
                            
                            quotes[sym] = {
                                "symbol": sym,
                                "lastPrice": price,
                                "change": change,
                                "pChange": pChange,
                                "volume": vol
                            }
                    except Exception as e:
                        pass
        except Exception as e:
            print(f"[CryptoService] Error fetching quotes: {e}")
            
        with self._lock:
            if quotes:
                self._cache = quotes
                self._cache_time = time.time()
            return self._cache

crypto_service = CryptoService()
