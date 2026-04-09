"""
NSE India Data Service
Fetches live stock quotes, options chain, and historical data from NSE endpoints.
Uses session-based requests with proper headers to avoid being blocked.
"""

import requests
import time
import json
from datetime import datetime, timedelta

class NSEService:
    BASE_URL = "https://www.nseindia.com"
    
    # Major NIFTY 50 stocks for scanning
    NIFTY50_STOCKS = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
        "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
        "SUNPHARMA", "BAJFINANCE", "WIPRO", "ULTRACEMCO", "HCLTECH",
        "NESTLEIND", "TATAMOTORS", "POWERGRID", "NTPC", "ONGC",
        "JSWSTEEL", "TATASTEEL", "ADANIENT", "ADANIPORTS", "TECHM",
        "INDUSINDBK", "BAJAJFINSV", "HINDALCO", "DIVISLAB", "DRREDDY",
        "CIPLA", "EICHERMOT", "BPCL", "COALINDIA", "GRASIM",
        "APOLLOHOSP", "HEROMOTOCO", "TATACONSUM", "BRITANNIA", "SBILIFE",
        "M&M", "BAJAJ-AUTO", "LTIM", "HDFCLIFE", "UPL"
    ]
    
    # NIFTY Next 50 stocks
    NIFTY_NEXT50_STOCKS = [
        "ABBOTINDIA", "ADANIGREEN", "ADANITRANS", "ALKEM",
        "AMBUJACEM", "AUROPHARMA", "BANDHANBNK", "BANKBARODA",
        "BERGEPAINT", "BIOCON", "BOSCHLTD", "CANBK",
        "CHOLAFIN", "COLPAL", "CONCOR", "CUMMINSIND",
        "DLF", "DABUR", "DMART", "GODREJCP",
        "GODREJPROP", "HAVELLS", "ICICIGI", "ICICIPRULI",
        "IDEA", "IDFCFIRSTB", "IGL", "INDUSTOWER",
        "IRCTC", "JINDALSTEL", "JUBLFOOD", "LICI",
        "LUPIN", "MARICO", "MCDOWELL-N", "MOTHERSON",
        "MPHASIS", "MUTHOOTFIN", "NAUKRI", "OBEROIRLTY",
        "PAGEIND", "PEL", "PERSISTENT", "PETRONET",
        "PFC", "PIDILITIND", "PNB", "POLYCAB",
        "RECLTD", "SBICARD"
    ]
    
    # Combined 100 stocks
    ALL_MAJOR_STOCKS = NIFTY50_STOCKS + NIFTY_NEXT50_STOCKS
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        self._cookies_set = False
        self._last_cookie_time = 0
    
    def _set_cookies(self, force=False):
        """Visit NSE homepage to get session cookies."""
        now = time.time()
        # Refresh cookies every 3 minutes, or immediately if forced
        if not force and self._cookies_set and (now - self._last_cookie_time) < 180:
            return
        try:
            # Reset session completely for fresh TLS handshake
            old_headers = dict(self.session.headers)
            self.session.close()
            self.session = requests.Session()
            self.session.headers.update(old_headers)
            
            self.session.get(self.BASE_URL, timeout=10)
            self._cookies_set = True
            self._last_cookie_time = now
            time.sleep(0.5)
            print(f"[NSE] Session cookies refreshed at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            self._cookies_set = False
            print(f"Warning: Could not set NSE cookies: {e}")
    
    def _get(self, url, params=None, retries=3):
        """Make a GET request with retry logic."""
        self._set_cookies()
        for attempt in range(retries):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=10,
                    headers={"Referer": self.BASE_URL}
                )
                if response.status_code == 200:
                    try:
                        return response.json()
                    except requests.exceptions.JSONDecodeError:
                        # NSE returned HTML instead of JSON — cookies are stale
                        print(f"[NSE] Got HTML instead of JSON for {url}, refreshing session...")
                        self._set_cookies(force=True)
                        continue
                elif response.status_code in (401, 403):
                    # Cookies expired or blocked, force refresh
                    print(f"[NSE] Got {response.status_code}, refreshing session...")
                    self._set_cookies(force=True)
                else:
                    print(f"NSE API returned {response.status_code} for {url}")
            except requests.exceptions.RequestException as e:
                print(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt == 0:
                    self._set_cookies(force=True)
            time.sleep(1 * (attempt + 1))
        return None
    
    def get_equity_quote(self, symbol):
        """Get live equity quote for a symbol."""
        url = f"{self.BASE_URL}/api/quote-equity?symbol={symbol}"
        data = self._get(url)
        if not data:
            return None
        
        try:
            price_info = data.get("priceInfo", {})
            info = data.get("info", {})
            metadata = data.get("metadata", {})
            
            return {
                "symbol": symbol,
                "companyName": info.get("companyName", symbol),
                "lastPrice": price_info.get("lastPrice", 0),
                "change": price_info.get("change", 0),
                "pChange": price_info.get("pChange", 0),
                "open": price_info.get("open", 0),
                "high": price_info.get("intraDayHighLow", {}).get("max", 0),
                "low": price_info.get("intraDayHighLow", {}).get("min", 0),
                "previousClose": price_info.get("previousClose", 0),
                "volume": metadata.get("totalTradedVolume", 0),
                "totalTradedValue": metadata.get("totalTradedValue", 0),
                "upperBand": price_info.get("upperCP", "N/A"),
                "lowerBand": price_info.get("lowerCP", "N/A"),
                "industry": metadata.get("industry", ""),
            }
        except Exception as e:
            print(f"Error parsing quote for {symbol}: {e}")
            return None
    
    def get_option_chain(self, symbol):
        """Get options chain data for a symbol."""
        url = f"{self.BASE_URL}/api/option-chain-equities?symbol={symbol}"
        data = self._get(url)
        if not data:
            return None
        
        try:
            records = data.get("records", {})
            filtered = data.get("filtered", {})
            
            expiry_dates = records.get("expiryDates", [])
            strikePrices = records.get("strikePrices", [])
            underlying_value = records.get("underlyingValue", 0)
            
            chain_data = []
            for item in filtered.get("data", []):
                entry = {
                    "strikePrice": item.get("strikePrice", 0),
                    "expiryDate": item.get("expiryDate", ""),
                }
                
                ce = item.get("CE", {})
                if ce:
                    entry["CE"] = {
                        "openInterest": ce.get("openInterest", 0),
                        "changeinOpenInterest": ce.get("changeinOpenInterest", 0),
                        "totalTradedVolume": ce.get("totalTradedVolume", 0),
                        "impliedVolatility": ce.get("impliedVolatility", 0),
                        "lastPrice": ce.get("lastPrice", 0),
                        "change": ce.get("change", 0),
                        "bidprice": ce.get("bidprice", 0),
                        "askPrice": ce.get("askPrice", 0),
                        "bidQty": ce.get("bidQty", 0),
                        "askQty": ce.get("askQty", 0),
                    }
                
                pe = item.get("PE", {})
                if pe:
                    entry["PE"] = {
                        "openInterest": pe.get("openInterest", 0),
                        "changeinOpenInterest": pe.get("changeinOpenInterest", 0),
                        "totalTradedVolume": pe.get("totalTradedVolume", 0),
                        "impliedVolatility": pe.get("impliedVolatility", 0),
                        "lastPrice": pe.get("lastPrice", 0),
                        "change": pe.get("change", 0),
                        "bidprice": pe.get("bidprice", 0),
                        "askPrice": pe.get("askPrice", 0),
                        "bidQty": pe.get("bidQty", 0),
                        "askQty": pe.get("askQty", 0),
                    }
                
                chain_data.append(entry)
            
            # CE/PE totals
            ce_totals = filtered.get("CE", {})
            pe_totals = filtered.get("PE", {})
            
            return {
                "symbol": symbol,
                "underlyingValue": underlying_value,
                "expiryDates": expiry_dates,
                "strikePrices": strikePrices,
                "data": chain_data,
                "ceTotals": {
                    "totalOI": ce_totals.get("totOI", 0),
                    "totalVol": ce_totals.get("totVol", 0),
                },
                "peTotals": {
                    "totalOI": pe_totals.get("totOI", 0),
                    "totalVol": pe_totals.get("totVol", 0),
                },
            }
        except Exception as e:
            print(f"Error parsing option chain for {symbol}: {e}")
            return None
    
    def get_historical_data(self, symbol, from_date=None, to_date=None):
        """Get historical OHLCV data for a symbol."""
        if not to_date:
            to_date = datetime.now().strftime("%d-%m-%Y")
        if not from_date:
            from_date = (datetime.now() - timedelta(days=365)).strftime("%d-%m-%Y")
        
        url = f"{self.BASE_URL}/api/historical/cm/equity"
        params = {
            "symbol": symbol,
            "series": '["EQ"]',
            "from": from_date,
            "to": to_date,
        }
        data = self._get(url, params=params)
        if not data:
            return None
        
        try:
            records = data.get("data", [])
            ohlcv = []
            for r in records:
                ohlcv.append({
                    "date": r.get("CH_TIMESTAMP", ""),
                    "open": r.get("CH_OPENING_PRICE", 0),
                    "high": r.get("CH_TRADE_HIGH_PRICE", 0),
                    "low": r.get("CH_TRADE_LOW_PRICE", 0),
                    "close": r.get("CH_CLOSING_PRICE", 0),
                    "volume": r.get("CH_TOT_TRADED_QTY", 0),
                    "value": r.get("CH_TOT_TRADED_VAL", 0),
                })
            # Sort by date ascending
            ohlcv.sort(key=lambda x: x["date"])
            return {
                "symbol": symbol,
                "data": ohlcv
            }
        except Exception as e:
            print(f"Error parsing historical data for {symbol}: {e}")
            return None
    
    def get_market_status(self):
        """Get current market status."""
        url = f"{self.BASE_URL}/api/marketStatus"
        return self._get(url)
    
    def get_top_gainers_losers(self):
        """Get NIFTY top gainers and losers."""
        url = f"{self.BASE_URL}/api/equity-stockIndices?index=NIFTY%2050"
        data = self._get(url)
        if not data:
            return None
        
        try:
            stocks = data.get("data", [])
            processed = []
            for s in stocks:
                if s.get("symbol") == "NIFTY 50":
                    continue
                processed.append({
                    "symbol": s.get("symbol", ""),
                    "lastPrice": s.get("lastPrice", 0),
                    "change": s.get("change", 0),
                    "pChange": s.get("pChange", 0),
                    "open": s.get("open", 0),
                    "dayHigh": s.get("dayHigh", 0),
                    "dayLow": s.get("dayLow", 0),
                    "previousClose": s.get("previousClose", 0),
                    "totalTradedVolume": s.get("totalTradedVolume", 0),
                    "totalTradedValue": s.get("totalTradedValue", 0),
                    "yearHigh": s.get("yearHigh", 0),
                    "yearLow": s.get("yearLow", 0),
                })
            
            # Sort by pChange for gainers/losers
            processed.sort(key=lambda x: x.get("pChange", 0), reverse=True)
            
            return {
                "gainers": processed[:10],
                "losers": processed[-10:][::-1],  # Reverse to show biggest losers first
                "all": processed,
            }
        except Exception as e:
            print(f"Error parsing market data: {e}")
            return None


# Singleton instance
nse = NSEService()
