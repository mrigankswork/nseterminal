"""
Backtesting Engine
Supports multiple strategies: SMA crossover, RSI, MACD, Bollinger Bands.
Returns PnL curve, win rate, max drawdown, and other performance metrics.
"""

import numpy as np
from datetime import datetime


def calculate_sma(prices, period):
    """Simple Moving Average."""
    if len(prices) < period:
        return np.full(len(prices), np.nan)
    sma = np.convolve(prices, np.ones(period) / period, mode='valid')
    return np.concatenate([np.full(period - 1, np.nan), sma])


def calculate_ema(prices, period):
    """Exponential Moving Average."""
    ema = np.zeros(len(prices))
    ema[0] = prices[0]
    multiplier = 2 / (period + 1)
    for i in range(1, len(prices)):
        ema[i] = prices[i] * multiplier + ema[i - 1] * (1 - multiplier)
    return ema


def calculate_rsi(prices, period=14):
    """Relative Strength Index."""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.zeros(len(prices))
    avg_loss = np.zeros(len(prices))
    
    if len(gains) < period:
        return np.full(len(prices), 50)
    
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])
    
    for i in range(period + 1, len(prices)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    
    rs = np.where(avg_loss != 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))
    rsi[:period] = np.nan
    return rsi


def calculate_macd(prices, fast=12, slow=26, signal=9):
    """MACD indicator."""
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger(prices, period=20, std_dev=2):
    """Bollinger Bands."""
    sma = calculate_sma(prices, period)
    rolling_std = np.full(len(prices), np.nan)
    for i in range(period - 1, len(prices)):
        rolling_std[i] = np.std(prices[i - period + 1:i + 1])
    upper = sma + std_dev * rolling_std
    lower = sma - std_dev * rolling_std
    return upper, sma, lower


class Backtester:
    """Run backtests on historical data with various strategies."""
    
    STRATEGIES = {
        "sma_crossover": "SMA Crossover (9/21)",
        "rsi": "RSI Overbought/Oversold",
        "macd": "MACD Signal Crossover",
        "bollinger": "Bollinger Band Breakout",
    }
    
    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
    
    def run(self, historical_data, strategy="sma_crossover", params=None):
        """
        Run a backtest on given historical data.
        
        Args:
            historical_data: list of {date, open, high, low, close, volume}
            strategy: one of the supported strategy names
            params: optional dict of strategy-specific parameters
        
        Returns:
            dict with results: trades, pnl_curve, metrics
        """
        if not historical_data or len(historical_data) < 30:
            return {"error": "Insufficient data for backtesting (need at least 30 data points)"}
        
        prices = np.array([d["close"] for d in historical_data], dtype=float)
        dates = [d["date"] for d in historical_data]
        
        params = params or {}
        
        if strategy == "sma_crossover":
            signals = self._sma_crossover_signals(prices, params)
        elif strategy == "rsi":
            signals = self._rsi_signals(prices, params)
        elif strategy == "macd":
            signals = self._macd_signals(prices, params)
        elif strategy == "bollinger":
            signals = self._bollinger_signals(prices, params)
        else:
            return {"error": f"Unknown strategy: {strategy}"}
        
        return self._simulate(prices, dates, signals, historical_data)
    
    def _sma_crossover_signals(self, prices, params):
        """Generate signals for SMA crossover strategy."""
        fast = params.get("fast_period", 9)
        slow = params.get("slow_period", 21)
        
        sma_fast = calculate_sma(prices, fast)
        sma_slow = calculate_sma(prices, slow)
        
        signals = np.zeros(len(prices))
        for i in range(1, len(prices)):
            if np.isnan(sma_fast[i]) or np.isnan(sma_slow[i]):
                continue
            if sma_fast[i] > sma_slow[i] and sma_fast[i - 1] <= sma_slow[i - 1]:
                signals[i] = 1  # Buy
            elif sma_fast[i] < sma_slow[i] and sma_fast[i - 1] >= sma_slow[i - 1]:
                signals[i] = -1  # Sell
        return signals
    
    def _rsi_signals(self, prices, params):
        """Generate signals for RSI strategy."""
        period = params.get("period", 14)
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)
        
        rsi = calculate_rsi(prices, period)
        
        signals = np.zeros(len(prices))
        for i in range(1, len(prices)):
            if np.isnan(rsi[i]):
                continue
            if rsi[i] < oversold and rsi[i - 1] >= oversold:
                signals[i] = 1  # Buy (oversold bounce)
            elif rsi[i] > overbought and rsi[i - 1] <= overbought:
                signals[i] = -1  # Sell (overbought reversal)
        return signals
    
    def _macd_signals(self, prices, params):
        """Generate signals for MACD strategy."""
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal_period = params.get("signal", 9)
        
        macd_line, signal_line, _ = calculate_macd(prices, fast, slow, signal_period)
        
        signals = np.zeros(len(prices))
        for i in range(1, len(prices)):
            if macd_line[i] > signal_line[i] and macd_line[i - 1] <= signal_line[i - 1]:
                signals[i] = 1  # Buy
            elif macd_line[i] < signal_line[i] and macd_line[i - 1] >= signal_line[i - 1]:
                signals[i] = -1  # Sell
        return signals
    
    def _bollinger_signals(self, prices, params):
        """Generate signals for Bollinger Band strategy."""
        period = params.get("period", 20)
        std_dev = params.get("std_dev", 2)
        
        upper, middle, lower = calculate_bollinger(prices, period, std_dev)
        
        signals = np.zeros(len(prices))
        for i in range(1, len(prices)):
            if np.isnan(lower[i]):
                continue
            if prices[i] < lower[i] and prices[i - 1] >= lower[i - 1]:
                signals[i] = 1  # Buy (price touches lower band)
            elif prices[i] > upper[i] and prices[i - 1] <= upper[i - 1]:
                signals[i] = -1  # Sell (price touches upper band)
        return signals
    
    def _simulate(self, prices, dates, signals, historical_data):
        """Simulate trading based on signals."""
        capital = self.initial_capital
        position = 0  # Number of shares
        entry_price = 0
        trades = []
        pnl_curve = []
        equity_curve = []
        
        for i in range(len(prices)):
            price = prices[i]
            portfolio_value = capital + position * price
            equity_curve.append({
                "date": dates[i],
                "value": round(portfolio_value, 2),
                "price": round(price, 2),
            })
            
            if signals[i] == 1 and position == 0:
                # Buy signal — go long
                shares = int(capital * 0.95 / price)  # Use 95% of capital
                if shares > 0:
                    position = shares
                    entry_price = price
                    capital -= shares * price
                    trades.append({
                        "type": "BUY",
                        "date": dates[i],
                        "price": round(price, 2),
                        "shares": shares,
                    })
            
            elif signals[i] == -1 and position > 0:
                # Sell signal — close position
                capital += position * price
                pnl = (price - entry_price) * position
                pnl_pct = ((price - entry_price) / entry_price) * 100
                trades.append({
                    "type": "SELL",
                    "date": dates[i],
                    "price": round(price, 2),
                    "shares": position,
                    "pnl": round(pnl, 2),
                    "pnlPct": round(pnl_pct, 2),
                })
                pnl_curve.append(round(pnl, 2))
                position = 0
                entry_price = 0
        
        # Close any open position at last price
        if position > 0:
            final_price = prices[-1]
            capital += position * final_price
            pnl = (final_price - entry_price) * position
            pnl_pct = ((final_price - entry_price) / entry_price) * 100
            trades.append({
                "type": "SELL (CLOSE)",
                "date": dates[-1],
                "price": round(final_price, 2),
                "shares": position,
                "pnl": round(pnl, 2),
                "pnlPct": round(pnl_pct, 2),
            })
            pnl_curve.append(round(pnl, 2))
        
        # Calculate metrics
        total_pnl = capital - self.initial_capital
        winning_trades = [p for p in pnl_curve if p > 0]
        losing_trades = [p for p in pnl_curve if p <= 0]
        
        equity_values = [e["value"] for e in equity_curve]
        max_drawdown = 0
        peak = equity_values[0]
        for v in equity_values:
            if v > peak:
                peak = v
            drawdown = (peak - v) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Sharpe ratio (annualized, assuming 252 trading days)
        if len(equity_values) > 1:
            returns = np.diff(equity_values) / equity_values[:-1]
            sharpe = (np.mean(returns) / (np.std(returns) + 1e-10)) * np.sqrt(252)
        else:
            sharpe = 0
        
        metrics = {
            "initialCapital": self.initial_capital,
            "finalCapital": round(capital, 2),
            "totalPnL": round(total_pnl, 2),
            "totalReturnPct": round((total_pnl / self.initial_capital) * 100, 2),
            "totalTrades": len(trades),
            "winningTrades": len(winning_trades),
            "losingTrades": len(losing_trades),
            "winRate": round(len(winning_trades) / max(len(pnl_curve), 1) * 100, 2),
            "avgWin": round(np.mean(winning_trades), 2) if winning_trades else 0,
            "avgLoss": round(np.mean(losing_trades), 2) if losing_trades else 0,
            "maxDrawdownPct": round(max_drawdown, 2),
            "sharpeRatio": round(sharpe, 2),
        }
        
        return {
            "trades": trades,
            "equityCurve": equity_curve,
            "pnlCurve": pnl_curve,
            "metrics": metrics,
        }
