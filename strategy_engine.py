"""
Strategy Engine — Real-Time Portfolio-Aware Day Strategy Generator

Combines:
  - AI Advisor scores (market sentiment + news + technicals)
  - Paper portfolio state (positions, cash, P&L)
  - Real-time news sentiment digest
Into an actionable "Today's Strategy" with entry/exit recommendations.
"""

import time
import math
from datetime import datetime


def _safe_float(val, default=0):
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


# Sector map (duplicated here to avoid circular imports)
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


class StrategyEngine:
    """
    Generates a portfolio-aware day trading strategy.
    Integrates AI scores with paper portfolio state for smarter recommendations.
    """

    STOP_LOSS_PCT = {
        "conservative": 2.0,
        "moderate": 3.0,
        "aggressive": 5.0,
    }
    TARGET_PCT = {
        "conservative": 3.0,
        "moderate": 5.0,
        "aggressive": 8.0,
    }
    MAX_SECTOR_EXPOSURE = {
        "conservative": 0.25,
        "moderate": 0.30,
        "aggressive": 0.40,
    }
    MAX_SINGLE_STOCK = {
        "conservative": 0.15,
        "moderate": 0.20,
        "aggressive": 0.25,
    }

    def generate_strategy(self, budget, risk_level, paper_portfolio,
                          ai_scores, market_news):
        """
        Generate a complete day trading strategy.

        Returns a dict with:
          - marketPulse: overall market overview
          - portfolioHealth: assessment of current paper positions
          - recommendations: list of BUY/SELL/HOLD actions
          - newsDigest: key news driving the strategy
          - riskAlerts: warnings about concentration, drawdown, etc.
          - meta: timestamps, refresh info
        """
        risk_level = risk_level.lower()
        if risk_level not in ("conservative", "moderate", "aggressive"):
            risk_level = "moderate"

        # ── Market Pulse ──────────────────────────────────────────
        market_pulse = self._build_market_pulse(ai_scores, market_news)

        # ── Portfolio Health ──────────────────────────────────────
        portfolio_health = self._assess_portfolio(paper_portfolio, ai_scores)

        # ── Recommendations ───────────────────────────────────────
        recommendations = self._generate_recommendations(
            budget, risk_level, paper_portfolio, ai_scores, market_news
        )

        # ── News Digest ───────────────────────────────────────────
        news_digest = self._build_news_digest(market_news)

        # ── Risk Alerts ───────────────────────────────────────────
        risk_alerts = self._generate_risk_alerts(
            paper_portfolio, recommendations, risk_level
        )

        now = datetime.now()
        return {
            "marketPulse": market_pulse,
            "portfolioHealth": portfolio_health,
            "recommendations": recommendations,
            "newsDigest": news_digest,
            "riskAlerts": risk_alerts,
            "meta": {
                "budget": budget,
                "riskLevel": risk_level,
                "generatedAt": now.isoformat(),
                "generatedAtDisplay": now.strftime("%I:%M %p"),
                "nextRefresh": 300,  # 5 minutes in seconds
                "refreshCount": 0,
            },
        }

    # ═══════════════════════════════════════════════════════════
    # Market Pulse
    # ═══════════════════════════════════════════════════════════
    def _build_market_pulse(self, ai_scores, market_news):
        if not ai_scores:
            return {
                "outlook": "NEUTRAL",
                "outlookText": "No market data available for analysis.",
                "avgScore": 50,
                "strongBuyCount": 0,
                "buyCount": 0,
                "holdCount": 0,
                "sellCount": 0,
                "strongSellCount": 0,
                "topSectors": [],
                "bottomSectors": [],
            }

        avg_score = sum(s["combinedScore"] for s in ai_scores) / len(ai_scores)
        signal_counts = {"STRONG BUY": 0, "BUY": 0, "HOLD": 0,
                         "SELL": 0, "STRONG SELL": 0}
        for s in ai_scores:
            sig = s.get("signal", "HOLD")
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

        # Sector breakdown
        sector_scores = {}
        for s in ai_scores:
            sec = s.get("sector", "Other")
            sector_scores.setdefault(sec, []).append(s["combinedScore"])

        sector_avgs = []
        for sec, scores in sector_scores.items():
            avg = sum(scores) / len(scores)
            sector_avgs.append({"sector": sec, "avgScore": round(avg, 1),
                                "count": len(scores)})
        sector_avgs.sort(key=lambda x: x["avgScore"], reverse=True)

        # Determine outlook
        buy_pct = (signal_counts["STRONG BUY"] + signal_counts["BUY"]) / max(len(ai_scores), 1)
        sell_pct = (signal_counts["SELL"] + signal_counts["STRONG SELL"]) / max(len(ai_scores), 1)

        if avg_score >= 62 and buy_pct >= 0.4:
            outlook = "STRONGLY BULLISH"
            text = (f"Market sentiment is strongly bullish today. "
                    f"{signal_counts['STRONG BUY'] + signal_counts['BUY']} out of "
                    f"{len(ai_scores)} stocks show buy signals with an average AI score "
                    f"of {avg_score:.0f}/100. Favorable options flow and positive news "
                    f"sentiment support aggressive positioning.")
        elif avg_score >= 55:
            outlook = "BULLISH"
            text = (f"Market outlook is moderately bullish. Average AI score is "
                    f"{avg_score:.0f}/100 across {len(ai_scores)} stocks. "
                    f"Select opportunities are available in top-scoring sectors. "
                    f"Consider building positions in strong buy signals.")
        elif avg_score >= 45:
            outlook = "NEUTRAL"
            text = (f"Market sentiment is mixed today with an average AI score of "
                    f"{avg_score:.0f}/100. {signal_counts['HOLD']} stocks show HOLD signals. "
                    f"Be selective and wait for clearer directional cues before "
                    f"committing significant capital.")
        elif avg_score >= 35:
            outlook = "BEARISH"
            text = (f"Market conditions are bearish with an average score of "
                    f"{avg_score:.0f}/100. {signal_counts['SELL'] + signal_counts['STRONG SELL']} "
                    f"stocks show sell signals. Consider reducing exposure and "
                    f"tightening stop-losses on existing positions.")
        else:
            outlook = "STRONGLY BEARISH"
            text = (f"Market is under significant pressure. Average AI score "
                    f"dropped to {avg_score:.0f}/100 with {sell_pct*100:.0f}% of "
                    f"stocks in sell territory. Defensive positioning recommended. "
                    f"Consider exiting weak positions.")

        # Add news context to the text
        if market_news and len(market_news) > 0:
            top_headline = market_news[0].get("title", "")
            if top_headline:
                text += f" Top headline: \"{top_headline[:80]}...\""

        return {
            "outlook": outlook,
            "outlookText": text,
            "avgScore": round(avg_score, 1),
            "strongBuyCount": signal_counts["STRONG BUY"],
            "buyCount": signal_counts["BUY"],
            "holdCount": signal_counts["HOLD"],
            "sellCount": signal_counts["SELL"],
            "strongSellCount": signal_counts["STRONG SELL"],
            "stocksAnalyzed": len(ai_scores),
            "topSectors": sector_avgs[:3],
            "bottomSectors": sector_avgs[-3:] if len(sector_avgs) > 3 else [],
        }

    # ═══════════════════════════════════════════════════════════
    # Portfolio Health Assessment
    # ═══════════════════════════════════════════════════════════
    def _assess_portfolio(self, paper_portfolio, ai_scores):
        if not paper_portfolio:
            return {
                "hasPositions": False,
                "totalValue": 0,
                "cash": 1000000,
                "positions": [],
                "overallPnl": 0,
                "overallPnlPct": 0,
            }

        positions = paper_portfolio.get("positions", {})
        cash = paper_portfolio.get("cash", 0)
        initial = paper_portfolio.get("initial_capital", 1000000)

        if not positions:
            return {
                "hasPositions": False,
                "totalValue": cash,
                "cash": cash,
                "positions": [],
                "overallPnl": round(cash - initial, 2),
                "overallPnlPct": round((cash - initial) / max(initial, 1) * 100, 2),
            }

        # Build scores lookup
        score_map = {s["symbol"]: s for s in (ai_scores or [])}

        position_assessments = []
        total_invested = 0
        total_current = 0

        for symbol, pos in positions.items():
            qty = pos.get("qty", 0)
            avg_price = pos.get("avgPrice", 0)
            invested = pos.get("investedValue", qty * avg_price)
            total_invested += invested

            # Get current AI score
            score_data = score_map.get(symbol, {})
            current_score = score_data.get("combinedScore", 50)
            current_signal = score_data.get("signal", "HOLD")
            current_price = score_data.get("price", avg_price)

            current_value = qty * current_price
            total_current += current_value
            pnl = current_value - invested
            pnl_pct = (pnl / max(invested, 1)) * 100

            # Determine hold/sell recommendation
            if pnl_pct <= -3 or (current_score < 30 and pnl_pct < 0):
                action = "SELL"
                reason = (f"Stop loss: {pnl_pct:.1f}% loss"
                          if pnl_pct <= -3 else
                          f"Score dropped to {current_score}, negative P&L")
            elif pnl_pct >= 5 or (pnl_pct >= 3 and current_score < 45):
                action = "TAKE PROFIT"
                reason = (f"Target reached: +{pnl_pct:.1f}%"
                          if pnl_pct >= 5 else
                          f"Good gain +{pnl_pct:.1f}% but momentum fading")
            elif current_score >= 55 and pnl_pct >= 0:
                action = "HOLD"
                reason = f"Strong score ({current_score}), positive trend"
            else:
                action = "HOLD"
                reason = f"Score {current_score}, P&L {pnl_pct:+.1f}% — monitoring"

            position_assessments.append({
                "symbol": symbol,
                "qty": qty,
                "avgPrice": avg_price,
                "currentPrice": round(current_price, 2),
                "invested": round(invested, 2),
                "currentValue": round(current_value, 2),
                "pnl": round(pnl, 2),
                "pnlPct": round(pnl_pct, 2),
                "aiScore": current_score,
                "signal": current_signal,
                "action": action,
                "actionReason": reason,
                "sector": SECTOR_MAP.get(symbol, "Other"),
            })

        total_value = cash + total_current
        overall_pnl = total_value - initial

        return {
            "hasPositions": True,
            "totalValue": round(total_value, 2),
            "cash": round(cash, 2),
            "invested": round(total_invested, 2),
            "currentValue": round(total_current, 2),
            "positions": sorted(position_assessments,
                                key=lambda x: abs(x["pnl"]), reverse=True),
            "overallPnl": round(overall_pnl, 2),
            "overallPnlPct": round((overall_pnl / max(initial, 1)) * 100, 2),
            "positionCount": len(positions),
        }

    # ═══════════════════════════════════════════════════════════
    # Generate Recommendations (portfolio-aware)
    # ═══════════════════════════════════════════════════════════
    def _generate_recommendations(self, budget, risk_level, paper_portfolio,
                                   ai_scores, market_news):
        if not ai_scores:
            return []

        # Determine available cash for new buys
        portfolio = paper_portfolio or {}
        current_positions = set(portfolio.get("positions", {}).keys())
        available_cash = min(budget, portfolio.get("cash", budget))

        # Calculate sector exposure from existing positions
        sector_exposure = {}
        positions = portfolio.get("positions", {})
        total_invested = sum(p.get("investedValue", 0) for p in positions.values())
        for sym, pos in positions.items():
            sec = SECTOR_MAP.get(sym, "Other")
            sector_exposure[sec] = sector_exposure.get(sec, 0) + pos.get("investedValue", 0)

        # Risk config
        stop_loss = self.STOP_LOSS_PCT[risk_level]
        target = self.TARGET_PCT[risk_level]
        max_sector = self.MAX_SECTOR_EXPOSURE[risk_level]
        max_stock = self.MAX_SINGLE_STOCK[risk_level]

        min_score = {"conservative": 60, "moderate": 50, "aggressive": 40}[risk_level]
        max_picks = {"conservative": 5, "moderate": 8, "aggressive": 12}[risk_level]
        sector_limit = {"conservative": 2, "moderate": 3, "aggressive": 4}[risk_level]

        # Filter candidates
        valid_signals = {"conservative": ("STRONG BUY", "BUY"),
                         "moderate": ("STRONG BUY", "BUY", "HOLD"),
                         "aggressive": ("STRONG BUY", "BUY", "HOLD")}
        signals = valid_signals[risk_level]

        candidates = sorted(
            [s for s in ai_scores
             if s["combinedScore"] >= min_score
             and s["signal"] in signals
             and s["symbol"] not in current_positions],  # Skip already held
            key=lambda x: x["combinedScore"],
            reverse=True
        )

        # Diversify by sector
        sector_count = {}
        diversified = []
        for stock in candidates:
            sec = stock.get("sector", "Other")
            current_sec_exposure = sector_exposure.get(sec, 0)

            # Check if adding more to this sector would exceed limit
            if (current_sec_exposure / max(total_invested + available_cash, 1)) > max_sector:
                continue
            if sector_count.get(sec, 0) >= sector_limit:
                continue

            diversified.append(stock)
            sector_count[sec] = sector_count.get(sec, 0) + 1
            if len(diversified) >= max_picks:
                break

        if not diversified:
            return []

        # Allocate budget proportionally
        total_score = sum(s["combinedScore"] for s in diversified)
        max_alloc = available_cash * max_stock
        recommendations = []
        remaining = available_cash

        for stock in diversified:
            raw_alloc = (stock["combinedScore"] / max(total_score, 1)) * available_cash
            alloc = min(raw_alloc, max_alloc, remaining)
            qty = max(1, int(alloc / stock["price"]))
            actual_cost = qty * stock["price"]

            if actual_cost > remaining:
                qty = max(1, int(remaining / stock["price"]))
                actual_cost = qty * stock["price"]
            if actual_cost > remaining or qty == 0:
                continue

            remaining -= actual_cost

            # Compute entry, stop-loss, target
            entry_price = stock["price"]
            sl_price = round(entry_price * (1 - stop_loss / 100), 2)
            target_price = round(entry_price * (1 + target / 100), 2)

            # Greeks data
            greeks = stock.get("greeksDetail", {})
            alpha_val = greeks.get("alpha", 0)
            theta_val = greeks.get("thetaDecayRate", 0)
            iv_pct = greeks.get("ivPercentile", 50)
            max_pain_val = greeks.get("maxPain", 0)

            # Build action reasoning from AI score components
            reasoning_parts = []
            if stock.get("marketScore", 50) >= 60:
                reasoning_parts.append("Strong options flow support")
            if stock.get("greeksScore", 50) >= 60:
                reasoning_parts.append(f"Positive alpha ({alpha_val:+.1f}%)")
            if iv_pct < 35:
                reasoning_parts.append(f"Low IV ({iv_pct:.0f}%) — good entry point")
            if stock.get("newsScore", 50) >= 60:
                reasoning_parts.append("Positive news sentiment")
            elif stock.get("newsScore", 50) <= 30:
                reasoning_parts.append("⚠ Negative news — monitor closely")
            if stock.get("techScore", 50) >= 60:
                reasoning_parts.append("Bullish technical setup")
            if not reasoning_parts:
                reasoning_parts.append("Mixed signals but above threshold")

            recommendations.append({
                "action": "BUY",
                "symbol": stock["symbol"],
                "sector": stock.get("sector", "Other"),
                "price": entry_price,
                "qty": qty,
                "allocation": round(actual_cost, 2),
                "entryPrice": entry_price,
                "stopLoss": sl_price,
                "stopLossPct": stop_loss,
                "target": target_price,
                "targetPct": target,
                "aiScore": stock["combinedScore"],
                "signal": stock["signal"],
                "marketScore": stock.get("marketScore", 50),
                "newsScore": stock.get("newsScore", 50),
                "techScore": stock.get("techScore", 50),
                "greeksScore": stock.get("greeksScore", 50),
                "alpha": round(alpha_val, 2),
                "theta": round(theta_val, 3),
                "ivPercentile": round(iv_pct, 1),
                "maxPain": round(max_pain_val, 2),
                "reasoning": ". ".join(reasoning_parts),
                "narrative": stock.get("narrative", ""),
                "changePct": stock.get("changePct", 0),
                "fundamentals": stock.get("fundamentals", {}),
                "newsArticles": stock.get("newsArticles", []),
                "marketDetail": stock.get("marketDetail", {}),
                "newsDetail": stock.get("newsDetail", {}),
                "techDetail": stock.get("techDetail", {}),
                "greeksDetail": greeks,
            })

        return recommendations

    # ═══════════════════════════════════════════════════════════
    # News Digest
    # ═══════════════════════════════════════════════════════════
    def _build_news_digest(self, market_news):
        if not market_news:
            return []

        digest = []
        for n in market_news[:8]:
            title = n.get("title", "")
            tags = n.get("tags", [])
            impact = "neutral"
            if any(t in tags for t in ["alert", "rising"]):
                impact = "positive"
            elif "analyst" in tags:
                impact = "analyst"

            # Detect sentiment from title
            title_lower = title.lower()
            bullish_kw = ["rally", "surges", "gains", "jumps", "bullish",
                          "upgrade", "outperform", "buy", "positive", "growth"]
            bearish_kw = ["falls", "drops", "crashes", "bearish", "downgrade",
                          "sell", "negative", "decline", "loss"]

            bull_hits = sum(1 for kw in bullish_kw if kw in title_lower)
            bear_hits = sum(1 for kw in bearish_kw if kw in title_lower)

            if bull_hits > bear_hits:
                impact = "positive"
            elif bear_hits > bull_hits:
                impact = "negative"

            digest.append({
                "title": title,
                "source": n.get("source", "Unknown"),
                "timeAgo": n.get("timeAgo", ""),
                "tags": tags,
                "impact": impact,
                "link": n.get("link", "#"),
            })

        return digest

    # ═══════════════════════════════════════════════════════════
    # Risk Alerts
    # ═══════════════════════════════════════════════════════════
    def _generate_risk_alerts(self, paper_portfolio, recommendations, risk_level):
        alerts = []
        portfolio = paper_portfolio or {}
        positions = portfolio.get("positions", {})
        initial = portfolio.get("initial_capital", 1000000)
        cash = portfolio.get("cash", initial)

        # 1. Portfolio drawdown
        total_invested = sum(p.get("investedValue", 0) for p in positions.values())
        total_value = cash + total_invested
        drawdown_pct = ((initial - total_value) / max(initial, 1)) * 100
        if drawdown_pct > 5:
            alerts.append({
                "type": "warning",
                "title": "Portfolio Drawdown Alert",
                "message": f"Your portfolio is down {drawdown_pct:.1f}% from initial capital. "
                           f"Consider reducing position sizes.",
                "severity": "high" if drawdown_pct > 10 else "medium",
            })

        # 2. Sector concentration
        sector_values = {}
        for sym, pos in positions.items():
            sec = SECTOR_MAP.get(sym, "Other")
            sector_values[sec] = sector_values.get(sec, 0) + pos.get("investedValue", 0)

        for sec, val in sector_values.items():
            pct = (val / max(total_invested, 1)) * 100
            max_allowed = self.MAX_SECTOR_EXPOSURE[risk_level] * 100
            if pct > max_allowed:
                alerts.append({
                    "type": "warning",
                    "title": f"Sector Over-Exposure: {sec}",
                    "message": f"{pct:.0f}% of your invested capital is in {sec} "
                               f"(max recommended: {max_allowed:.0f}%). "
                               f"Consider diversifying.",
                    "severity": "medium",
                })

        # 3. Low cash
        if total_value > 0:
            cash_pct = (cash / total_value) * 100
            if cash_pct < 10:
                alerts.append({
                    "type": "info",
                    "title": "Low Cash Reserve",
                    "message": f"Only {cash_pct:.0f}% cash remaining. "
                               f"Consider booking profits to maintain flexibility.",
                    "severity": "low",
                })

        # 4. No new recommendations found
        if not recommendations:
            alerts.append({
                "type": "info",
                "title": "No Strong Opportunities",
                "message": "No stocks meet the criteria for new positions at your "
                           "risk level. Market may be in a consolidation phase.",
                "severity": "low",
            })

        # 5. Market closed notice
        now = datetime.now()
        weekday = now.weekday()
        hour = now.hour
        minute = now.minute
        market_open = (
            weekday < 5
            and ((hour == 9 and minute >= 15) or
                 (hour > 9 and hour < 15) or
                 (hour == 15 and minute <= 30))
        )
        if not market_open:
            alerts.append({
                "type": "info",
                "title": "Market Closed",
                "message": "NSE market is currently closed. "
                           "Strategy is based on last available data. "
                           "Prices will update when market opens.",
                "severity": "low",
            })

        return alerts


# Singleton
strategy_engine = StrategyEngine()
