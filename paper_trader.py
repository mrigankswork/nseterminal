"""
Paper Trading Engine — Simulated trading with real-time price tracking.
Persists portfolio state and trade history to a JSON file.
"""

import json
import os
import time
from datetime import datetime

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "paper_portfolio.json")
DEFAULT_CAPITAL = 1000000  # ₹10,00,000
BROKERAGE_PCT = 0.0003  # 0.03% per trade


class PaperTrader:
    def __init__(self):
        self._load()

    def _load(self):
        """Load portfolio from disk."""
        if os.path.exists(PORTFOLIO_FILE):
            try:
                with open(PORTFOLIO_FILE, "r") as f:
                    data = json.load(f)
                    self.cash = data.get("cash", DEFAULT_CAPITAL)
                    self.positions = data.get("positions", {})
                    self.trades = data.get("trades", [])
                    self.initial_capital = data.get("initial_capital", DEFAULT_CAPITAL)
                    return
            except Exception as e:
                print(f"Error loading portfolio: {e}")
        self._reset_state()

    def _reset_state(self):
        self.cash = DEFAULT_CAPITAL
        self.positions = {}  # {symbol: {qty, avgPrice, investedValue}}
        self.trades = []
        self.initial_capital = DEFAULT_CAPITAL

    def _save(self):
        """Persist portfolio to disk."""
        try:
            with open(PORTFOLIO_FILE, "w") as f:
                json.dump({
                    "cash": self.cash,
                    "positions": self.positions,
                    "trades": self.trades,
                    "initial_capital": self.initial_capital,
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving portfolio: {e}")

    def buy(self, symbol, qty, price):
        """Execute a paper buy order. Returns trade record or error."""
        symbol = symbol.upper()
        qty = int(qty)
        price = float(price)

        if qty <= 0:
            return {"error": "Quantity must be positive"}
        if price <= 0:
            return {"error": "Price must be positive"}

        cost = qty * price
        brokerage = round(cost * BROKERAGE_PCT, 2)
        total_cost = cost + brokerage

        if total_cost > self.cash:
            return {"error": f"Insufficient funds. Need ₹{total_cost:,.2f}, have ₹{self.cash:,.2f}"}

        # Update cash
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
        else:
            self.positions[symbol] = {
                "qty": qty,
                "avgPrice": round(price, 2),
                "investedValue": round(cost, 2),
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
            "timestamp": datetime.now().isoformat(),
            "cashAfter": self.cash,
        }
        self.trades.append(trade)
        self._save()
        return {"success": True, "trade": trade}

    def sell(self, symbol, qty, price):
        """Execute a paper sell order. Returns trade record or error."""
        symbol = symbol.upper()
        qty = int(qty)
        price = float(price)

        if qty <= 0:
            return {"error": "Quantity must be positive"}
        if price <= 0:
            return {"error": "Price must be positive"}

        if symbol not in self.positions or self.positions[symbol]["qty"] < qty:
            held = self.positions.get(symbol, {}).get("qty", 0)
            return {"error": f"Insufficient shares. Have {held}, trying to sell {qty}"}

        pos = self.positions[symbol]
        proceeds = qty * price
        brokerage = round(proceeds * BROKERAGE_PCT, 2)
        net_proceeds = proceeds - brokerage

        # Calculate P&L for this trade
        avg_cost = pos["avgPrice"] * qty
        pnl = round(net_proceeds - avg_cost, 2)

        # Update cash
        self.cash += net_proceeds
        self.cash = round(self.cash, 2)

        # Update position
        pos["qty"] -= qty
        pos["investedValue"] = round(pos["qty"] * pos["avgPrice"], 2)
        if pos["qty"] == 0:
            del self.positions[symbol]

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
            "timestamp": datetime.now().isoformat(),
            "cashAfter": self.cash,
        }
        self.trades.append(trade)
        self._save()
        return {"success": True, "trade": trade}

    def get_portfolio(self, live_prices=None):
        """Get current portfolio state with optional live P&L."""
        positions_list = []
        total_invested = 0
        total_current = 0

        for symbol, pos in self.positions.items():
            invested = pos["investedValue"]
            total_invested += invested

            current_price = (live_prices or {}).get(symbol, pos["avgPrice"])
            current_value = pos["qty"] * current_price
            total_current += current_value
            pnl = current_value - invested
            pnl_pct = (pnl / invested * 100) if invested > 0 else 0

            positions_list.append({
                "symbol": symbol,
                "qty": pos["qty"],
                "avgPrice": pos["avgPrice"],
                "investedValue": round(invested, 2),
                "currentPrice": round(current_price, 2),
                "currentValue": round(current_value, 2),
                "pnl": round(pnl, 2),
                "pnlPct": round(pnl_pct, 2),
            })

        total_value = self.cash + total_current
        overall_pnl = total_value - self.initial_capital

        return {
            "cash": round(self.cash, 2),
            "invested": round(total_invested, 2),
            "currentValue": round(total_current, 2),
            "totalValue": round(total_value, 2),
            "totalPnl": round(overall_pnl, 2),
            "totalPnlPct": round((overall_pnl / self.initial_capital * 100), 2) if self.initial_capital > 0 else 0,
            "positions": sorted(positions_list, key=lambda x: abs(x["pnl"]), reverse=True),
        }

    def get_trades(self, limit=50):
        """Get recent trade history."""
        return list(reversed(self.trades[-limit:]))

    def reset(self):
        """Reset portfolio to starting capital."""
        self._reset_state()
        self._save()
        return {"success": True, "message": "Portfolio reset to ₹10,00,000"}


# Singleton
paper_trader = PaperTrader()
