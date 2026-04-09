"""
Autonomous Agentic Paper Trader — Fully Automated Trading Bot
Makes ~100 trades per day using real-time NSE prices.
Combines AI scoring (fundamentals + sentiment + technicals + options flow)
with momentum, mean-reversion, and news-catalyst strategies.

Separate portfolio from manual paper trading.
"""

import json
import os
import time
import threading
import random
import math
from datetime import datetime, timedelta
from collections import defaultdict

# Import project services
from nse_service import nse
from ai_advisor import advisor
from news_service import news_service

# ─── Configuration ─────────────────────────────────────────────────
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "auto_portfolio.json")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "auto_sessions.json")

# Capital Management
MAX_SINGLE_STOCK_PCT = 0.05       # Max 5% of capital per stock
MAX_SECTOR_PCT = 0.25             # Max 25% per sector
CASH_RESERVE_PCT = 0.10           # Keep 10% cash reserve
MIN_TRADE_VALUE = 500             # Minimum ₹500 per trade

# Risk Management
STOP_LOSS_PCT = 2.0               # -2% stop loss
TAKE_PROFIT_PCT = 3.0             # +3% take profit
TRAILING_STOP_PCT = 1.5           # 1.5% trailing stop from peak
SCORE_SELL_THRESHOLD = 30         # Sell if AI score drops below 30

# Bot Timing  — FAST
TRADE_INTERVAL_BASE = 5           # ~5 seconds between trade cycles
TRADE_INTERVAL_JITTER = 2         # ±2 seconds randomness
SCORE_REFRESH_INTERVAL = 30       # Refresh AI scores every 30 sec
QUICK_SCAN_BATCH = 5              # Score fewer stocks faster

# Scoring Thresholds for Buy — aggressive for paper trading
MOMENTUM_BUY_MIN_SCORE = 50
MOMENTUM_BUY_MIN_CHANGE = 0.5    # Min +0.5% intraday change
MEAN_REVERSION_MIN_SCORE = 45
MEAN_REVERSION_MAX_CHANGE = -1.0  # Must be down at least 1%
NEWS_CATALYST_MIN_SCORE = 50
NEWS_CATALYST_MIN_NEWS_SCORE = 65

# Sector map (from ai_advisor)
SECTOR_MAP = {
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "LTIM": "IT", "MPHASIS": "IT", "PERSISTENT": "IT", "NAUKRI": "IT",
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "KOTAKBANK": "Banking", "AXISBANK": "Banking", "INDUSINDBK": "Banking",
    "BANKBARODA": "Banking", "CANBK": "Banking", "PNB": "Banking",
    "IDFCFIRSTB": "Banking", "BANDHANBNK": "Banking",
    "BAJFINANCE": "Finance", "BAJAJFINSV": "Finance", "CHOLAFIN": "Finance",
    "MUTHOOTFIN": "Finance", "SBICARD": "Finance", "PFC": "Finance",
    "RECLTD": "Finance", "HDFCLIFE": "Finance", "SBILIFE": "Finance",
    "ICICIGI": "Finance", "ICICIPRULI": "Finance", "LICI": "Finance",
    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto",
    "BAJAJ-AUTO": "Auto", "EICHERMOT": "Auto", "HEROMOTOCO": "Auto",
    "MOTHERSON": "Auto",
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "APOLLOHOSP": "Pharma", "BIOCON": "Pharma",
    "AUROPHARMA": "Pharma", "LUPIN": "Pharma", "ALKEM": "Pharma",
    "ABBOTINDIA": "Pharma",
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "COALINDIA": "Energy", "NTPC": "Energy", "POWERGRID": "Energy",
    "ADANIGREEN": "Energy", "PETRONET": "Energy", "IGL": "Energy",
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals",
    "JINDALSTEL": "Metals",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG", "TATACONSUM": "FMCG", "DABUR": "FMCG",
    "COLPAL": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG",
    "MCDOWELL-N": "FMCG",
    "LT": "Infra", "ADANIENT": "Infra", "ADANIPORTS": "Infra",
    "ADANITRANS": "Infra", "GRASIM": "Infra", "ULTRACEMCO": "Infra",
    "AMBUJACEM": "Infra", "DLF": "Infra", "GODREJPROP": "Infra",
    "OBEROIRLTY": "Infra", "PIDILITIND": "Infra", "HAVELLS": "Infra",
    "POLYCAB": "Infra", "CUMMINSIND": "Infra",
    "TITAN": "Consumer", "ASIANPAINT": "Consumer", "BERGEPAINT": "Consumer",
    "PAGEIND": "Consumer", "JUBLFOOD": "Consumer", "DMART": "Consumer",
    "PEL": "Consumer",
    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "INDUSTOWER": "Telecom",
    "IRCTC": "Transport", "CONCOR": "Transport", "BOSCHLTD": "Transport",
    "UPL": "Agrochem",
}

BROKERAGE_PCT = 0.0003  # 0.03% per trade


class AutonomousTrader:
    """
    Fully autonomous paper trading agent.
    Manages its own portfolio and executes ~100 trades/day during market hours.
    """

    def __init__(self):
        self.running = False
        self.capital = 0
        self.cash = 0
        self.positions = {}       # {symbol: {qty, avgPrice, investedValue, peakPrice, entryTime, entryScore, strategy}}
        self.trades = []
        self.initial_capital = 0

        # Runtime state
        self._thread = None
        self._lock = threading.Lock()
        self._ai_scores = {}      # {symbol: score_dict}
        self._scores_updated = 0
        self._last_trade_time = 0
        self._trade_count_today = 0
        self._session_start = None
        self._daily_pnl = 0
        self._winning_trades = 0
        self._losing_trades = 0
        self._best_trade = None
        self._worst_trade = None
        self._recent_trades = []  # Last 50 trades for live feed
        self._status_message = "Idle"
        self._sessions = []

        # Load saved state
        self._load()
        self._load_sessions()
        
        # Auto-resume if active portfolio exists (protects against dev server reloads)
        if self.initial_capital > 0:
            self.start(0)

    # ═══════════════════════════════════════════════════════════════
    # Persistence
    # ═══════════════════════════════════════════════════════════════
    def _load(self):
        """Load portfolio from disk."""
        if os.path.exists(PORTFOLIO_FILE):
            try:
                with open(PORTFOLIO_FILE, "r") as f:
                    data = json.load(f)
                    self.capital = data.get("capital", 0)
                    self.cash = data.get("cash", 0)
                    self.positions = data.get("positions", {})
                    self.trades = data.get("trades", [])
                    self.initial_capital = data.get("initial_capital", 0)
                    self._trade_count_today = data.get("trade_count_today", 0)
                    self._daily_pnl = data.get("daily_pnl", 0)
                    self._winning_trades = data.get("winning_trades", 0)
                    self._losing_trades = data.get("losing_trades", 0)
                    self._recent_trades = data.get("recent_trades", [])
                    self._best_trade = data.get("best_trade")
                    self._worst_trade = data.get("worst_trade")
            except Exception as e:
                print(f"[AutoTrader] Error loading portfolio: {e}")

    def _save(self):
        """Persist portfolio to disk."""
        try:
            with open(PORTFOLIO_FILE, "w") as f:
                json.dump({
                    "capital": self.capital,
                    "cash": round(self.cash, 2),
                    "positions": self.positions,
                    "trades": self.trades[-500:],  # Keep last 500 trades
                    "initial_capital": self.initial_capital,
                    "trade_count_today": self._trade_count_today,
                    "daily_pnl": round(self._daily_pnl, 2),
                    "winning_trades": self._winning_trades,
                    "losing_trades": self._losing_trades,
                    "recent_trades": self._recent_trades[-50:],
                    "best_trade": self._best_trade,
                    "worst_trade": self._worst_trade,
                }, f, indent=2)
        except Exception as e:
            print(f"[AutoTrader] Error saving portfolio: {e}")

    def _load_sessions(self):
        """Load session history."""
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r") as f:
                    self._sessions = json.load(f)
            except Exception:
                self._sessions = []

    def _save_sessions(self):
        """Save session history."""
        try:
            with open(SESSION_FILE, "w") as f:
                json.dump(self._sessions[-30:], f, indent=2)  # Keep last 30 days
        except Exception as e:
            print(f"[AutoTrader] Error saving sessions: {e}")

    # ═══════════════════════════════════════════════════════════════
    # Start / Stop
    # ═══════════════════════════════════════════════════════════════
    def start(self, investment_amount):
        """Start the autonomous trader with a given investment amount."""
        with self._lock:
            if self.running:
                return {"error": "Bot is already running"}

            investment_amount = float(investment_amount)
            if investment_amount > 0 and investment_amount < 10000:
                return {"error": "Minimum investment is ₹10,000"}
            
            # Resume: amount=0 means just restart with existing capital
            if investment_amount == 0 and self.initial_capital == 0:
                return {"error": "No existing capital. Please enter an investment amount."}

            # If no existing portfolio, initialize fresh
            if self.initial_capital == 0 and investment_amount > 0:
                self.initial_capital = investment_amount
                self.capital = investment_amount
                self.cash = investment_amount
                self.positions = {}
                self.trades = []
                self._recent_trades = []
            elif investment_amount > 0:
                # Add more capital to existing portfolio
                self.capital += investment_amount
                self.cash += investment_amount
                self.initial_capital += investment_amount
            # else: amount=0 means resume — keep existing state

            self.running = True
            self._session_start = datetime.now()
            self._trade_count_today = 0
            self._daily_pnl = 0
            self._winning_trades = 0
            self._losing_trades = 0
            self._best_trade = None
            self._worst_trade = None
            self._status_message = "Initializing AI engine..."
            self._save()

        # Start trading thread
        self._thread = threading.Thread(target=self._trade_loop, daemon=True)
        self._thread.start()

        msg = f"Autonomous trader resumed" if investment_amount == 0 else f"Autonomous trader started with ₹{investment_amount:,.0f}"
        return {
            "success": True,
            "message": msg,
            "totalCapital": self.capital,
            "cash": self.cash,
        }

    def stop(self):
        """Stop the autonomous trader."""
        with self._lock:
            if not self.running:
                return {"error": "Bot is not running"}

            self.running = False
            self._status_message = "Stopped by user"

            # Save session summary
            self._end_session()
            self._save()

        return {
            "success": True,
            "message": "Autonomous trader stopped",
            "sessionPnl": round(self._daily_pnl, 2),
            "tradeCount": self._trade_count_today,
        }

    def reset(self):
        """Reset the autonomous trader completely."""
        with self._lock:
            self.running = False
            self.capital = 0
            self.cash = 0
            self.positions = {}
            self.trades = []
            self.initial_capital = 0
            self._trade_count_today = 0
            self._daily_pnl = 0
            self._winning_trades = 0
            self._losing_trades = 0
            self._best_trade = None
            self._worst_trade = None
            self._recent_trades = []
            self._ai_scores = {}
            self._status_message = "Reset"
            self._save()

        # Delete portfolio file
        if os.path.exists(PORTFOLIO_FILE):
            os.remove(PORTFOLIO_FILE)

        return {"success": True, "message": "Autonomous trader reset"}

    # ═══════════════════════════════════════════════════════════════
    # Main Trade Loop
    # ═══════════════════════════════════════════════════════════════
    def _trade_loop(self):
        """Main autonomous trading loop — runs in background thread."""
        print("[AutoTrader] 🤖 Trade loop started")

        # Phase 1: Fast initial scan — use gainers/losers for instant data
        self._status_message = "Fast-scanning top movers..."
        self._fast_initial_scan()

        # Phase 2: Quick-score a batch of stocks
        if len(self._ai_scores) < 5:
            self._status_message = "Quick-scoring stocks..."
            self._refresh_scores_batch()

        cycle = 0
        while self.running:
            try:
                # Check if market is open
                if not self._is_market_open():
                    self._status_message = "Market closed — waiting for 9:00 AM IST"
                    time.sleep(60)
                    continue

                # The bot should not stop — daily target limit removed

                cycle += 1

                # Refresh AI scores every few cycles
                if time.time() - self._scores_updated > SCORE_REFRESH_INTERVAL:
                    self._status_message = "Refreshing scores..."
                    self._refresh_scores_batch()

                # Execute one trade cycle
                self._status_message = f"Cycle #{cycle} | Analyzing {len(self._ai_scores)} stocks..."
                self._execute_trade_cycle()

                # Wait before next trade (with jitter)
                interval = TRADE_INTERVAL_BASE + random.randint(
                    -TRADE_INTERVAL_JITTER, TRADE_INTERVAL_JITTER
                )
                self._status_message = f"Next cycle in {interval}s | {self._trade_count_today} trades | P&L: ₹{self._daily_pnl:,.2f}"

                # Sleep in small intervals so we can stop quickly
                for _ in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                print(f"[AutoTrader] Error in trade loop: {e}")
                import traceback
                traceback.print_exc()
                self._status_message = f"Error: {str(e)[:50]} — retrying..."
                time.sleep(10)

        print("[AutoTrader] 🛑 Trade loop stopped")

    def _execute_trade_cycle(self):
        """Execute one complete trade cycle: check sells, then look for buys."""
        trades_this_cycle = 0

        # PHASE 1: Check existing positions for sell signals
        sells = self._evaluate_sells()
        for sell in sells:
            result = self._execute_sell(
                sell["symbol"], sell["qty"], sell["price"],
                sell["strategy"], sell["reason"]
            )
            if result and result.get("success"):
                trades_this_cycle += 1
                if trades_this_cycle >= 3:  # Max 3 trades per cycle
                    break

        # PHASE 2: Look for buy opportunities
        if trades_this_cycle < 3:
            buys = self._evaluate_buys()
            for buy in buys:
                if trades_this_cycle >= 3:
                    break
                result = self._execute_buy(
                    buy["symbol"], buy["qty"], buy["price"],
                    buy["strategy"], buy["reason"], buy["score"]
                )
                if result and result.get("success"):
                    trades_this_cycle += 1

        if trades_this_cycle > 0:
            self._save()

    # ═══════════════════════════════════════════════════════════════
    # Sell Decision Engine
    # ═══════════════════════════════════════════════════════════════
    def _evaluate_sells(self):
        """Evaluate all positions for sell signals. Returns list of sell orders."""
        sell_orders = []

        for symbol, pos in list(self.positions.items()):
            try:
                quote = nse.get_equity_quote(symbol)
                if not quote or not quote.get("lastPrice"):
                    continue

                current_price = float(quote["lastPrice"])
                avg_price = pos["avgPrice"]
                pnl_pct = ((current_price - avg_price) / avg_price) * 100

                # Update peak price for trailing stop
                peak = pos.get("peakPrice", avg_price)
                if current_price > peak:
                    pos["peakPrice"] = current_price
                    peak = current_price

                # Get current AI score
                score_data = self._ai_scores.get(symbol, {})
                current_score = score_data.get("combinedScore", 50)

                # ── STOP LOSS: Cut losses early ──
                if pnl_pct <= -STOP_LOSS_PCT:
                    sell_orders.append({
                        "symbol": symbol,
                        "qty": pos["qty"],
                        "price": current_price,
                        "strategy": "STOP_LOSS",
                        "reason": f"Stop loss triggered at {pnl_pct:+.1f}%",
                    })
                    continue

                # ── TRAILING STOP: Protect profits ──
                if peak > avg_price:
                    retrace_from_peak = ((peak - current_price) / peak) * 100
                    if retrace_from_peak >= TRAILING_STOP_PCT and pnl_pct > 0:
                        sell_orders.append({
                            "symbol": symbol,
                            "qty": pos["qty"],
                            "price": current_price,
                            "strategy": "TRAILING_STOP",
                            "reason": f"Retraced {retrace_from_peak:.1f}% from peak ₹{peak:,.1f} (P&L: {pnl_pct:+.1f}%)",
                        })
                        continue

                # ── TAKE PROFIT: Book partial gains ──
                if pnl_pct >= TAKE_PROFIT_PCT:
                    # Sell half the position to book profits, let rest ride
                    sell_qty = max(1, pos["qty"] // 2)
                    sell_orders.append({
                        "symbol": symbol,
                        "qty": sell_qty,
                        "price": current_price,
                        "strategy": "TAKE_PROFIT",
                        "reason": f"Booking profits at {pnl_pct:+.1f}% (partial: {sell_qty}/{pos['qty']} shares)",
                    })
                    continue

                # ── SCORE DEGRADATION: Sell when fundamentals worsen ──
                entry_score = pos.get("entryScore", 50)
                if current_score < SCORE_SELL_THRESHOLD and pnl_pct < 0:
                    sell_orders.append({
                        "symbol": symbol,
                        "qty": pos["qty"],
                        "price": current_price,
                        "strategy": "SCORE_DEGRADATION",
                        "reason": f"AI score dropped to {current_score} (was {entry_score} at entry), P&L: {pnl_pct:+.1f}%",
                    })
                    continue

                # ── REBALANCE: Reduce oversized positions ──
                total_value = self._get_total_value()
                pos_value = pos["qty"] * current_price
                if total_value > 0 and (pos_value / total_value) > MAX_SINGLE_STOCK_PCT * 1.5:
                    # Position grown too large — trim it
                    excess_pct = (pos_value / total_value) - MAX_SINGLE_STOCK_PCT
                    trim_qty = max(1, int(pos["qty"] * (excess_pct / (pos_value / total_value))))
                    if trim_qty > 0 and trim_qty < pos["qty"]:
                        sell_orders.append({
                            "symbol": symbol,
                            "qty": trim_qty,
                            "price": current_price,
                            "strategy": "REBALANCE",
                            "reason": f"Trimming oversized position ({pos_value/total_value*100:.1f}% of portfolio, max {MAX_SINGLE_STOCK_PCT*100:.0f}%)",
                        })

                time.sleep(0.15)  # Rate limit NSE calls

            except Exception as e:
                print(f"[AutoTrader] Error evaluating sell for {symbol}: {e}")
                continue

        return sell_orders

    # ═══════════════════════════════════════════════════════════════
    # Buy Decision Engine
    # ═══════════════════════════════════════════════════════════════
    def _evaluate_buys(self):
        """Evaluate stocks for buy opportunities. Returns list of buy orders."""
        if not self._ai_scores:
            return []

        buy_orders = []
        total_value = self._get_total_value()
        available_cash = self.cash - (total_value * CASH_RESERVE_PCT)

        if available_cash < MIN_TRADE_VALUE:
            return []

        # Get sector exposure
        sector_exposure = self._get_sector_exposure()

        # Sort all scored stocks
        scored_stocks = sorted(
            self._ai_scores.values(),
            key=lambda x: x.get("combinedScore", 0),
            reverse=True
        )

        # Current held symbols
        held_symbols = set(self.positions.keys())

        for stock in scored_stocks:
            if len(buy_orders) >= 3:  # Max 3 buy orders per cycle
                break

            symbol = stock.get("symbol", "")
            score = stock.get("combinedScore", 0)
            price = stock.get("price", 0)
            change_pct = stock.get("changePct", 0)
            news_score = stock.get("newsScore", 50)
            tech_score = stock.get("techScore", 50)
            market_score = stock.get("marketScore", 50)
            sector = SECTOR_MAP.get(symbol, "Other")

            if price <= 0:
                continue

            # Skip if already holding max position
            if symbol in held_symbols:
                pos = self.positions[symbol]
                pos_value = pos["qty"] * price
                if total_value > 0 and (pos_value / total_value) >= MAX_SINGLE_STOCK_PCT:
                    continue

            # Skip if sector is over-exposed
            if total_value > 0:
                sec_val = sector_exposure.get(sector, 0)
                if (sec_val / total_value) >= MAX_SECTOR_PCT:
                    continue

            # Determine buy strategy
            strategy = None
            reason = ""

            # Strategy 1: MOMENTUM BUY — strong upward momentum + high score
            if (score >= MOMENTUM_BUY_MIN_SCORE and
                    change_pct >= MOMENTUM_BUY_MIN_CHANGE and
                    tech_score >= 55):
                strategy = "MOMENTUM_BUY"
                reason = (f"Momentum: AI {score}/100, +{change_pct:.1f}% today, "
                          f"Tech {tech_score}/100")

            # Strategy 2: MEAN REVERSION — buy oversold stocks with good fundamentals
            elif (score >= MEAN_REVERSION_MIN_SCORE and
                  change_pct <= MEAN_REVERSION_MAX_CHANGE and
                  market_score >= 50):
                strategy = "MEAN_REVERSION_BUY"
                reason = (f"Mean Reversion: AI {score}/100, {change_pct:.1f}% dip, "
                          f"Market {market_score}/100 (strong fundamentals despite drop)")

            # Strategy 3: NEWS CATALYST — buy on strong positive news
            elif (score >= NEWS_CATALYST_MIN_SCORE and
                  news_score >= NEWS_CATALYST_MIN_NEWS_SCORE):
                strategy = "NEWS_CATALYST_BUY"
                reason = (f"News Catalyst: AI {score}/100, News {news_score}/100, "
                          f"strong positive sentiment")

            # Strategy 4: VALUE BUY — high combined score, good all-around
            elif score >= 60:
                strategy = "VALUE_BUY"
                reason = (f"Value: AI {score}/100 (Market {market_score}, "
                          f"Tech {tech_score}, News {news_score})")

            if not strategy:
                continue

            # Position sizing based on score confidence
            # Higher score = larger position
            confidence = min((score - 40) / 60, 1.0)  # 0.0–1.0
            max_position_value = total_value * MAX_SINGLE_STOCK_PCT
            target_value = max_position_value * confidence
            target_value = min(target_value, available_cash * 0.3)  # Max 30% of available cash per trade
            target_value = max(target_value, MIN_TRADE_VALUE)

            if target_value > available_cash:
                continue

            qty = max(1, int(target_value / price))
            actual_cost = qty * price

            if actual_cost > available_cash:
                qty = max(1, int(available_cash / price))
                actual_cost = qty * price

            if actual_cost > available_cash or actual_cost < MIN_TRADE_VALUE:
                continue

            buy_orders.append({
                "symbol": symbol,
                "qty": qty,
                "price": price,
                "strategy": strategy,
                "reason": reason,
                "score": score,
            })

            available_cash -= actual_cost

        return buy_orders

    # ═══════════════════════════════════════════════════════════════
    # Trade Execution
    # ═══════════════════════════════════════════════════════════════
    def _execute_buy(self, symbol, qty, price, strategy, reason, score):
        """Execute a paper buy order."""
        with self._lock:
            # Re-verify current price
            try:
                quote = nse.get_equity_quote(symbol)
                if quote and quote.get("lastPrice"):
                    price = float(quote["lastPrice"])
            except Exception:
                pass  # Use the price we already have

            cost = qty * price
            brokerage = round(cost * BROKERAGE_PCT, 2)
            total_cost = cost + brokerage

            if total_cost > self.cash:
                return {"error": "Insufficient funds"}

            # Deduct cash
            self.cash -= total_cost
            self.cash = round(self.cash, 2)

            # Update position
            if symbol in self.positions:
                pos = self.positions[symbol]
                old_value = pos["qty"] * pos["avgPrice"]
                new_value = old_value + cost
                pos["qty"] += qty
                pos["avgPrice"] = round(new_value / pos["qty"], 2)
                pos["investedValue"] = round(new_value, 2)
                pos["peakPrice"] = max(pos.get("peakPrice", price), price)
            else:
                self.positions[symbol] = {
                    "qty": qty,
                    "avgPrice": round(price, 2),
                    "investedValue": round(cost, 2),
                    "peakPrice": price,
                    "entryTime": datetime.now().isoformat(),
                    "entryScore": score,
                    "strategy": strategy,
                }

            # Record trade
            trade = {
                "id": len(self.trades) + 1,
                "type": "BUY",
                "symbol": symbol,
                "qty": qty,
                "price": round(price, 2),
                "cost": round(cost, 2),
                "brokerage": brokerage,
                "total": round(total_cost, 2),
                "strategy": strategy,
                "reason": reason,
                "score": score,
                "timestamp": datetime.now().isoformat(),
                "cashAfter": self.cash,
                "sector": SECTOR_MAP.get(symbol, "Other"),
            }
            self.trades.append(trade)
            self._recent_trades.append(trade)
            self._recent_trades = self._recent_trades[-50:]
            self._trade_count_today += 1
            self._last_trade_time = time.time()

            print(f"[AutoTrader] 📈 BUY {qty}x {symbol} @ ₹{price:,.2f} [{strategy}] {reason}")
            return {"success": True, "trade": trade}

    def _execute_sell(self, symbol, qty, price, strategy, reason):
        """Execute a paper sell order."""
        with self._lock:
            if symbol not in self.positions:
                return {"error": f"No position in {symbol}"}

            pos = self.positions[symbol]
            if pos["qty"] < qty:
                qty = pos["qty"]  # Sell what we have

            # Re-verify current price
            try:
                quote = nse.get_equity_quote(symbol)
                if quote and quote.get("lastPrice"):
                    price = float(quote["lastPrice"])
            except Exception:
                pass

            proceeds = qty * price
            brokerage = round(proceeds * BROKERAGE_PCT, 2)
            net_proceeds = proceeds - brokerage

            # Calculate P&L
            avg_cost = pos["avgPrice"] * qty
            pnl = round(net_proceeds - avg_cost, 2)

            # Update cash
            self.cash += net_proceeds
            self.cash = round(self.cash, 2)

            # Update position
            pos["qty"] -= qty
            pos["investedValue"] = round(pos["qty"] * pos["avgPrice"], 2)
            if pos["qty"] <= 0:
                del self.positions[symbol]

            # Track P&L
            self._daily_pnl += pnl
            if pnl > 0:
                self._winning_trades += 1
            else:
                self._losing_trades += 1

            if self._best_trade is None or pnl > self._best_trade.get("pnl", 0):
                self._best_trade = {"symbol": symbol, "pnl": pnl, "strategy": strategy}
            if self._worst_trade is None or pnl < self._worst_trade.get("pnl", 0):
                self._worst_trade = {"symbol": symbol, "pnl": pnl, "strategy": strategy}

            # Record trade
            trade = {
                "id": len(self.trades) + 1,
                "type": "SELL",
                "symbol": symbol,
                "qty": qty,
                "price": round(price, 2),
                "proceeds": round(proceeds, 2),
                "brokerage": brokerage,
                "net": round(net_proceeds, 2),
                "pnl": pnl,
                "pnlPct": round((pnl / avg_cost) * 100, 2) if avg_cost > 0 else 0,
                "strategy": strategy,
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
                "cashAfter": self.cash,
                "sector": SECTOR_MAP.get(symbol, "Other"),
            }
            self.trades.append(trade)
            self._recent_trades.append(trade)
            self._recent_trades = self._recent_trades[-50:]
            self._trade_count_today += 1
            self._last_trade_time = time.time()

            emoji = "💰" if pnl > 0 else "💸"
            print(f"[AutoTrader] {emoji} SELL {qty}x {symbol} @ ₹{price:,.2f} P&L: ₹{pnl:+,.2f} [{strategy}] {reason}")
            return {"success": True, "trade": trade}

    # ═══════════════════════════════════════════════════════════════
    # AI Score Refresh — Fast, Batched Approach
    # ═══════════════════════════════════════════════════════════════
    def inject_scores(self, scores_list):
        """Inject pre-computed scores from server cache. Called externally."""
        if not scores_list:
            return
        for score in scores_list:
            sym = score.get("symbol", "")
            if sym:
                self._ai_scores[sym] = score
        self._scores_updated = time.time()
        print(f"[AutoTrader] 💉 Injected {len(scores_list)} scores from server cache")

    def _fast_initial_scan(self):
        """Use NIFTY gainers/losers API for instant stock data — no per-stock calls needed."""
        try:
            data = nse.get_top_gainers_losers()
            if not data:
                print("[AutoTrader] ⚠️ Could not fetch market data for fast scan")
                return

            all_stocks = data.get("all", []) or []
            gainers = data.get("gainers", []) or []
            losers = data.get("losers", []) or []

            scanned = 0
            for stock_data in all_stocks[:50]:  # Use top 50 from market data
                if not self.running:
                    break
                try:
                    symbol = stock_data.get("symbol", "")
                    price = stock_data.get("lastPrice", 0)
                    change_pct = stock_data.get("pChange", 0)

                    if not symbol or price <= 0:
                        continue

                    # Build a lightweight score from market data alone
                    # This is fast — no API calls needed
                    tech_score = 50  # Neutral default
                    if change_pct > 2:
                        tech_score = 70 + min(change_pct * 2, 20)
                    elif change_pct > 0.5:
                        tech_score = 55 + change_pct * 5
                    elif change_pct < -2:
                        tech_score = 30 + max(change_pct, -10)  # Mean reversion candidate
                    elif change_pct < -0.5:
                        tech_score = 40

                    combined = int(min(95, max(20, tech_score)))
                    sector = SECTOR_MAP.get(symbol, "Other")

                    self._ai_scores[symbol] = {
                        "symbol": symbol,
                        "price": float(price),
                        "changePct": round(float(change_pct), 2),
                        "combinedScore": combined,
                        "techScore": int(tech_score),
                        "marketScore": 50,
                        "newsScore": 50,
                        "sector": sector,
                        "signal": "BUY" if combined >= 55 else ("HOLD" if combined >= 40 else "SELL"),
                        "reasoning": f"Fast scan: {change_pct:+.1f}% today",
                    }
                    scanned += 1
                except Exception:
                    continue

            if scanned > 0:
                self._scores_updated = time.time()
                print(f"[AutoTrader] ⚡ Fast-scanned {scanned} stocks from market data")

        except Exception as e:
            print(f"[AutoTrader] Error in fast scan: {e}")

    def _refresh_scores_batch(self):
        """Score a batch of stocks with quote data (no option chains for speed)."""
        # Pick a random batch from all stocks, mixing scored and unscored
        all_stocks = list(nse.ALL_MAJOR_STOCKS)
        random.shuffle(all_stocks)
        batch = all_stocks[:QUICK_SCAN_BATCH]

        # Also add held positions (always rescore those)
        for sym in self.positions:
            if sym not in batch:
                batch.append(sym)

        scanned = 0
        failures = 0
        for symbol in batch:
            if not self.running:
                break
            try:
                quote = nse.get_equity_quote(symbol)
                if not quote:
                    failures += 1
                    if failures >= 3 and scanned == 0:
                        print("[AutoTrader] ⚠️ NSE unreachable, using existing scores")
                        break
                    continue

                failures = 0
                # Skip option chain — too slow. Just use quote + news
                try:
                    news = news_service.get_news(symbol, max_articles=2)
                except Exception:
                    news = []

                result = advisor.score_stock(symbol, quote, None, news)
                if result:
                    self._ai_scores[symbol] = result
                    scanned += 1

                time.sleep(0.15)  # Light rate limiting

            except Exception as e:
                print(f"[AutoTrader] Error scoring {symbol}: {e}")
                continue

        if scanned > 0:
            self._scores_updated = time.time()
            print(f"[AutoTrader] 🔄 Refreshed {scanned}/{len(batch)} scores (total: {len(self._ai_scores)})")

    # ═══════════════════════════════════════════════════════════════
    # Helper Methods
    # ═══════════════════════════════════════════════════════════════
    def _is_market_open(self):
        """Check if NSE market is currently open."""
        now = datetime.now()
        weekday = now.weekday()
        hour = now.hour
        return (
            weekday < 5
            and (hour >= 9 and hour < 17)
        )

    def _get_total_value(self):
        """Get total portfolio value (cash + positions at avg price)."""
        pos_value = sum(
            pos["qty"] * pos["avgPrice"]
            for pos in self.positions.values()
        )
        return self.cash + pos_value

    def _get_sector_exposure(self):
        """Get sector-wise exposure in absolute values."""
        exposure = {}
        for symbol, pos in self.positions.items():
            sector = SECTOR_MAP.get(symbol, "Other")
            exposure[sector] = exposure.get(sector, 0) + pos["investedValue"]
        return exposure

    def _end_session(self):
        """Save the current session summary."""
        if self._session_start:
            session = {
                "date": self._session_start.strftime("%Y-%m-%d"),
                "startTime": self._session_start.isoformat(),
                "endTime": datetime.now().isoformat(),
                "trades": self._trade_count_today,
                "pnl": round(self._daily_pnl, 2),
                "winningTrades": self._winning_trades,
                "losingTrades": self._losing_trades,
                "winRate": round(
                    self._winning_trades / max(self._winning_trades + self._losing_trades, 1) * 100, 1
                ),
                "bestTrade": self._best_trade,
                "worstTrade": self._worst_trade,
                "portfolioValue": round(self._get_total_value(), 2),
                "positionCount": len(self.positions),
            }
            self._sessions.append(session)
            self._save_sessions()

    # ═══════════════════════════════════════════════════════════════
    # Status / API Methods
    # ═══════════════════════════════════════════════════════════════
    def get_status(self):
        """Get current bot status for the API."""
        total_value = self._get_total_value()

        # Calculate live P&L using current prices
        live_positions = []
        total_unrealized_pnl = 0

        for symbol, pos in self.positions.items():
            score_data = self._ai_scores.get(symbol, {})
            current_price = score_data.get("price", pos["avgPrice"])
            invested = pos["investedValue"]
            current_value = pos["qty"] * current_price
            unrealized = current_value - invested
            total_unrealized_pnl += unrealized

            live_positions.append({
                "symbol": symbol,
                "qty": pos["qty"],
                "avgPrice": pos["avgPrice"],
                "currentPrice": round(current_price, 2),
                "invested": round(invested, 2),
                "currentValue": round(current_value, 2),
                "pnl": round(unrealized, 2),
                "pnlPct": round((unrealized / invested) * 100, 2) if invested > 0 else 0,
                "strategy": pos.get("strategy", "MANUAL"),
                "entryTime": pos.get("entryTime", ""),
                "entryScore": pos.get("entryScore", 50),
                "currentScore": score_data.get("combinedScore", 50),
                "sector": SECTOR_MAP.get(symbol, "Other"),
            })

        # Sort by absolute P&L
        live_positions.sort(key=lambda x: abs(x["pnl"]), reverse=True)

        overall_pnl = (self.cash + sum(
            p["currentValue"] for p in live_positions
        )) - self.initial_capital if self.initial_capital > 0 else 0

        win_rate = round(
            self._winning_trades / max(self._winning_trades + self._losing_trades, 1) * 100, 1
        )

        # Sector breakdown
        sectors = {}
        for p in live_positions:
            sec = p["sector"]
            if sec not in sectors:
                sectors[sec] = {"value": 0, "count": 0, "pnl": 0}
            sectors[sec]["value"] += p["currentValue"]
            sectors[sec]["count"] += 1
            sectors[sec]["pnl"] += p["pnl"]

        # Strategy breakdown
        strategy_stats = {}
        for trade in self._recent_trades:
            strat = trade.get("strategy", "UNKNOWN")
            if strat not in strategy_stats:
                strategy_stats[strat] = {"count": 0, "pnl": 0}
            strategy_stats[strat]["count"] += 1
            if trade.get("type") == "SELL":
                strategy_stats[strat]["pnl"] += trade.get("pnl", 0)

        return {
            "running": self.running,
            "statusMessage": self._status_message,
            "initialCapital": self.initial_capital,
            "cash": round(self.cash, 2),
            "totalValue": round(self.cash + sum(p["currentValue"] for p in live_positions), 2),
            "overallPnl": round(overall_pnl, 2),
            "overallPnlPct": round(
                (overall_pnl / self.initial_capital) * 100, 2
            ) if self.initial_capital > 0 else 0,
            "dailyPnl": round(self._daily_pnl, 2),
            "unrealizedPnl": round(total_unrealized_pnl, 2),
            "tradeCountToday": self._trade_count_today,
            "winRate": win_rate,
            "winningTrades": self._winning_trades,
            "losingTrades": self._losing_trades,
            "bestTrade": self._best_trade,
            "worstTrade": self._worst_trade,
            "positionCount": len(self.positions),
            "positions": live_positions,
            "sectors": sectors,
            "strategyStats": strategy_stats,
            "scoresLoaded": len(self._ai_scores),
            "lastScoreRefresh": self._scores_updated,
            "marketOpen": self._is_market_open(),
            "timestamp": datetime.now().isoformat(),
        }

    def get_trades(self, limit=50):
        """Get recent trades."""
        return list(reversed(self._recent_trades[-limit:]))

    def get_sessions(self):
        """Get past session summaries."""
        return list(reversed(self._sessions))


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════
auto_trader = AutonomousTrader()
