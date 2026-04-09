"""
AI Advisor — Smart Recommendation Engine
Combines market sentiment, news sentiment, and technical analysis
to generate budget-aware stock picks.

Scoring weights:
  Market Sentiment: 40%  (PCR, IV skew, OI change, volume ratio)
  News Sentiment:   30%  (bullish/bearish keyword analysis)
  Technical:        30%  (52wk position, momentum, delivery %)
"""

import time
import re
import math
from datetime import datetime

# ─── Sentiment keyword lists ───────────────────────────────────────
BULLISH_KEYWORDS = [
    "rally", "surges", "gains", "jumps", "soars", "climbs", "breakout",
    "52-week high", "all-time high", "bullish", "strong buying", "upgrade",
    "outperform", "buy", "positive", "beat estimates", "record revenue",
    "expansion", "growth", "partnership", "dividend", "bonus", "share buyback",
    "block deal", "strong results", "robust", "upbeat", "boom", "recovery",
]
BEARISH_KEYWORDS = [
    "falls", "drops", "slides", "slumps", "plunges", "crashes", "selloff",
    "52-week low", "bearish", "weak", "downgrade", "underperform", "sell",
    "negative", "miss estimates", "decline", "probe", "fraud", "sebi order",
    "debt", "loss", "risk", "concern", "warning", "penalty", "delayed",
    "cut", "layoff", "default", "ban", "suspension", "impairment",
]

# Sector classification for diversification
SECTOR_MAP = {
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "LTIM": "IT", "MPHASIS": "IT", "PERSISTENT": "IT", "NAUKRI": "IT",
    # Banks
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "KOTAKBANK": "Banking", "AXISBANK": "Banking", "INDUSINDBK": "Banking",
    "BANKBARODA": "Banking", "CANBK": "Banking", "PNB": "Banking",
    "IDFCFIRSTB": "Banking", "BANDHANBNK": "Banking",
    # NBFC / Finance
    "BAJFINANCE": "Finance", "BAJAJFINSV": "Finance", "CHOLAFIN": "Finance",
    "MUTHOOTFIN": "Finance", "SBICARD": "Finance", "PFC": "Finance",
    "RECLTD": "Finance", "HDFCLIFE": "Finance", "SBILIFE": "Finance",
    "ICICIGI": "Finance", "ICICIPRULI": "Finance", "LICI": "Finance",
    # Auto
    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto",
    "BAJAJ-AUTO": "Auto", "EICHERMOT": "Auto", "HEROMOTOCO": "Auto",
    "MOTHERSON": "Auto",
    # Pharma
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "APOLLOHOSP": "Pharma", "BIOCON": "Pharma",
    "AUROPHARMA": "Pharma", "LUPIN": "Pharma", "ALKEM": "Pharma",
    "ABBOTINDIA": "Pharma",
    # Energy / Oil & Gas
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "COALINDIA": "Energy", "NTPC": "Energy", "POWERGRID": "Energy",
    "ADANIGREEN": "Energy", "PETRONET": "Energy", "IGL": "Energy",
    # Metals
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals",
    "JINDALSTEL": "Metals",
    # FMCG
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG", "TATACONSUM": "FMCG", "DABUR": "FMCG",
    "COLPAL": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG",
    "MCDOWELL-N": "FMCG",
    # Infra / Capital Goods
    "LT": "Infra", "ADANIENT": "Infra", "ADANIPORTS": "Infra",
    "ADANITRANS": "Infra", "GRASIM": "Infra", "ULTRACEMCO": "Infra",
    "AMBUJACEM": "Infra", "DLF": "Infra", "GODREJPROP": "Infra",
    "OBEROIRLTY": "Infra", "PIDILITIND": "Infra", "HAVELLS": "Infra",
    "POLYCAB": "Infra", "CUMMINSIND": "Infra",
    # Consumer / Retail
    "TITAN": "Consumer", "ASIANPAINT": "Consumer", "BERGEPAINT": "Consumer",
    "PAGEIND": "Consumer", "JUBLFOOD": "Consumer", "DMART": "Consumer",
    "PEL": "Consumer",
    # Telecom
    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "INDUSTOWER": "Telecom",
    # Transport / Logistics
    "IRCTC": "Transport", "CONCOR": "Transport", "BOSCHLTD": "Transport",
    # Misc
    "UPL": "Agrochem",
}


def _safe_float(val, default=0):
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


class AIAdvisor:
    """
    Combined AI scoring engine.
    Generates budget-aware stock picks using market, news, and technical signals.
    """

    # ─── Score a single stock ──────────────────────────────────────
    def score_stock(self, symbol, quote, option_chain, news_articles, rsi=None):
        """
        Compute a combined AI score (0–100) for a stock.
        Uses 4 signals: market sentiment (options/greeks), news,
        technical analysis, and alpha/theta analytics.
        Returns dict with total score and per-signal breakdowns.
        """
        if not quote:
            return None

        price = _safe_float(quote.get("lastPrice"))
        change_pct = _safe_float(quote.get("pChange"))
        if price == 0:
            return None

        # 1) Market Sentiment Score (0–100) — weight 30%
        market_score, market_detail = self._market_sentiment(quote, option_chain)

        # 2) News Sentiment Score (0–100) — weight 20%
        news_score, news_detail = self._news_sentiment(news_articles)

        # 3) Technical Score (0–100) — weight 25%
        tech_score, tech_detail = self._technical_score(quote, rsi)

        # 4) Alpha/Theta/Greeks Score (0–100) — weight 25%
        greeks_score, greeks_detail = self._greeks_alpha_score(quote, option_chain)

        # Combined weighted score
        combined = (
            market_score * 0.30 +
            news_score * 0.20 +
            tech_score * 0.25 +
            greeks_score * 0.25
        )
        combined = min(round(combined, 1), 100)

        # Determine signal
        if combined >= 70:
            signal = "STRONG BUY"
        elif combined >= 55:
            signal = "BUY"
        elif combined >= 45:
            signal = "HOLD"
        elif combined >= 30:
            signal = "SELL"
        else:
            signal = "STRONG SELL"

        # Generate reasoning (short)
        reasons = []
        if market_score >= 60:
            reasons.append(market_detail.get("topReason", "Favorable options flow"))
        if greeks_score >= 60:
            reasons.append(greeks_detail.get("topReason", "Strong alpha signal"))
        if news_score >= 60:
            reasons.append("Positive news sentiment")
        elif news_score <= 30:
            reasons.append("Negative news sentiment")
        if tech_score >= 60:
            reasons.append(tech_detail.get("topReason", "Strong technicals"))
        elif tech_score <= 30:
            reasons.append(tech_detail.get("topReason", "Weak technicals"))

        if not reasons:
            reasons.append("Mixed signals — neutral outlook")

        # Extract fundamentals from quote
        high52 = _safe_float(quote.get("high52"))
        low52 = _safe_float(quote.get("low52"))
        fundamentals = {
            "companyName": quote.get("companyName", symbol),
            "industry": quote.get("industry", "N/A"),
            "open": _safe_float(quote.get("open")),
            "dayHigh": _safe_float(quote.get("dayHigh", quote.get("high"))),
            "dayLow": _safe_float(quote.get("dayLow", quote.get("low"))),
            "previousClose": _safe_float(quote.get("previousClose")),
            "high52": high52,
            "low52": low52,
            "upperBand": quote.get("upperBand", "—"),
            "lowerBand": quote.get("lowerBand", "—"),
            "volume": _safe_float(quote.get("volume", quote.get("totalTradedVolume"))),
            "change": _safe_float(quote.get("change")),
        }

        # News articles (top 5 with links for detail panel)
        news_for_detail = []
        if news_articles:
            for a in news_articles[:5]:
                news_for_detail.append({
                    "title": a.get("title", ""),
                    "link": a.get("link", ""),
                    "source": a.get("source", ""),
                    "timeAgo": a.get("timeAgo", ""),
                    "description": a.get("description", ""),
                    "tags": a.get("tags", []),
                })

        # Generate detailed narrative for the detail panel
        narrative = self._generate_narrative(
            symbol, signal, combined, market_score, news_score,
            tech_score, market_detail, news_detail, tech_detail,
            fundamentals, greeks_score, greeks_detail
        )

        return {
            "symbol": symbol,
            "price": price,
            "changePct": round(change_pct, 2),
            "sector": SECTOR_MAP.get(symbol, "Other"),
            "combinedScore": combined,
            "signal": signal,
            "marketScore": round(market_score, 1),
            "newsScore": round(news_score, 1),
            "techScore": round(tech_score, 1),
            "greeksScore": round(greeks_score, 1),
            "reasoning": ". ".join(reasons),
            "narrative": narrative,
            "marketDetail": market_detail,
            "newsDetail": news_detail,
            "techDetail": tech_detail,
            "greeksDetail": greeks_detail,
            "fundamentals": fundamentals,
            "newsArticles": news_for_detail,
        }

    # ─── Generate Detailed Narrative ──────────────────────────────
    def _generate_narrative(self, symbol, signal, combined, market_score,
                            news_score, tech_score, market_detail,
                            news_detail, tech_detail, fundamentals,
                            greeks_score=50, greeks_detail=None):
        """Build a human-readable analysis narrative for the detail panel."""
        greeks_detail = greeks_detail or {}
        parts = []

        # Overall verdict
        company = fundamentals.get("companyName", symbol)
        industry = fundamentals.get("industry", "N/A")
        parts.append(
            f"{company} ({symbol}) in the {industry} space receives an AI score "
            f"of {combined}/100, resulting in a {signal} signal."
        )

        # Market sentiment section
        if market_score >= 60:
            pcr = market_detail.get("pcrOI", 0)
            parts.append(
                f"Options market analysis is bullish (score: {market_score}/100). "
                f"Put-Call Ratio stands at {pcr}, indicating strong put support. "
                f"{market_detail.get('topReason', '')}."
            )
        elif market_score <= 40:
            parts.append(
                f"Options flow is bearish (score: {market_score}/100). "
                f"{market_detail.get('topReason', 'Weak options support')}."
            )
        else:
            parts.append(
                f"Options market sentiment is neutral (score: {market_score}/100). "
                f"{market_detail.get('topReason', 'No significant bias in derivatives')}."
            )

        # Alpha / Theta / Greeks section
        alpha = greeks_detail.get("alpha", 0)
        theta_rate = greeks_detail.get("thetaDecayRate", 0)
        iv_pct = greeks_detail.get("ivPercentile", 50)
        max_pain = greeks_detail.get("maxPain", 0)
        price = _safe_float(fundamentals.get("previousClose"))

        if greeks_score >= 60:
            alpha_str = f"+{alpha:.1f}%" if alpha > 0 else f"{alpha:.1f}%"
            parts.append(
                f"Greeks & Alpha analysis is favorable (score: {greeks_score}/100). "
                f"Alpha signal at {alpha_str} vs benchmark. "
                f"IV percentile is {iv_pct:.0f}% (" +
                ("options are cheap — good entry" if iv_pct < 40 else
                 "elevated IV — premium selling opportunity" if iv_pct > 70 else
                 "IV is at fair value") + "). " +
                (f"Max pain at ₹{max_pain:,.0f}" if max_pain > 0 else "") + ". " +
                f"{greeks_detail.get('topReason', '')}."
            )
        elif greeks_score <= 40:
            parts.append(
                f"Greeks & Alpha signal is weak (score: {greeks_score}/100). "
                f"Negative alpha of {alpha:.1f}% suggests underperformance vs peers. "
                f"{greeks_detail.get('topReason', '')}."
            )
        else:
            parts.append(
                f"Greeks & Alpha analysis is neutral (score: {greeks_score}/100). "
                f"Alpha at {alpha:.1f}%, IV percentile {iv_pct:.0f}%. "
                f"{greeks_detail.get('topReason', 'No significant greeks bias')}."
            )

        # Technical section
        pos52 = tech_detail.get("pos52wk", 50)
        change = tech_detail.get("changePct", 0)
        high52 = fundamentals.get("high52", 0)
        low52 = fundamentals.get("low52", 0)
        prev = fundamentals.get("previousClose", 0)
        rsi_val = tech_detail.get("rsi", None)

        tech_parts = []
        if high52 > 0 and low52 > 0:
            tech_parts.append(
                f"52-week range: ₹{low52:,.1f} — ₹{high52:,.1f} "
                f"(currently at {pos52:.0f}% of range)"
            )
        if prev > 0:
            tech_parts.append(f"Previous close: ₹{prev:,.2f}")
        if change != 0:
            direction = "up" if change > 0 else "down"
            tech_parts.append(f"Today: {direction} {abs(change):.2f}%")
        
        if rsi_val is not None:
            if rsi_val < 30:
                tech_parts.append(f"RSI is {rsi_val:.1f} (Oversold - Potential Reversal)")
            elif rsi_val > 70:
                tech_parts.append(f"RSI is {rsi_val:.1f} (Overbought - High Risk)")
            else:
                tech_parts.append(f"RSI is {rsi_val:.1f} (Neutral)")

        parts.append(
            f"Technical analysis scores {tech_score}/100. "
            + ". ".join(tech_parts) + ". "
            + tech_detail.get("topReason", "")
        )

        # News section
        bull = news_detail.get("bullish", 0)
        bear = news_detail.get("bearish", 0)
        total_news = bull + bear + news_detail.get("neutral", 0)
        if total_news > 0:
            parts.append(
                f"News sentiment scores {news_score}/100 based on {total_news} "
                f"recent articles ({bull} bullish, {bear} bearish). "
                f"Top headline: \"{news_detail.get('topHeadline', 'N/A')}\"."
            )
        else:
            parts.append(
                f"No recent news articles found for sentiment analysis "
                f"(score defaults to {news_score}/100)."
            )

        return " ".join(parts)

    # ─── Market Sentiment (options-based) ──────────────────────────
    def _market_sentiment(self, quote, option_chain):
        score = 50  # Neutral default
        detail = {"topReason": "No options data"}

        if not option_chain:
            return score, detail

        chain_data = option_chain.get("data", [])
        if not chain_data:
            return score, detail

        underlying = _safe_float(option_chain.get("underlyingValue",
                                                   quote.get("lastPrice", 0)))

        total_ce_oi = sum(_safe_float(d.get("CE", {}).get("openInterest")) for d in chain_data)
        total_pe_oi = sum(_safe_float(d.get("PE", {}).get("openInterest")) for d in chain_data)
        total_ce_vol = sum(_safe_float(d.get("CE", {}).get("totalTradedVolume")) for d in chain_data)
        total_pe_vol = sum(_safe_float(d.get("PE", {}).get("totalTradedVolume")) for d in chain_data)

        pcr_oi = total_pe_oi / max(total_ce_oi, 1)
        vol_ratio = total_ce_vol / max(total_pe_vol, 1)

        # ATM IV
        atm_strike = min(
            (d["strikePrice"] for d in chain_data),
            key=lambda x: abs(x - underlying), default=underlying
        )
        atm_entries = [d for d in chain_data
                       if abs(d["strikePrice"] - atm_strike) < atm_strike * 0.05]

        ce_ivs = [_safe_float(d.get("CE", {}).get("impliedVolatility"))
                  for d in atm_entries if _safe_float(d.get("CE", {}).get("impliedVolatility")) > 0]
        pe_ivs = [_safe_float(d.get("PE", {}).get("impliedVolatility"))
                  for d in atm_entries if _safe_float(d.get("PE", {}).get("impliedVolatility")) > 0]
        avg_ce_iv = sum(ce_ivs) / len(ce_ivs) if ce_ivs else 0
        avg_pe_iv = sum(pe_ivs) / len(pe_ivs) if pe_ivs else 0

        # OI change
        ce_oi_change = sum(_safe_float(d.get("CE", {}).get("changeinOpenInterest"))
                          for d in atm_entries)
        pe_oi_change = sum(_safe_float(d.get("PE", {}).get("changeinOpenInterest"))
                          for d in atm_entries)

        # Scoring
        score = 50
        reason_parts = []

        # PCR (>1 = bullish support via put writing)
        if pcr_oi > 1.3:
            score += 20
            reason_parts.append(f"PCR {pcr_oi:.2f} (strong put support)")
        elif pcr_oi > 1.0:
            score += 10
            reason_parts.append(f"PCR {pcr_oi:.2f} (mild put support)")
        elif pcr_oi < 0.6:
            score -= 20
            reason_parts.append(f"PCR {pcr_oi:.2f} (bearish)")
        elif pcr_oi < 0.8:
            score -= 10

        # Volume ratio
        if vol_ratio > 1.5:
            score += 10
            reason_parts.append("High call volume")
        elif vol_ratio < 0.6:
            score -= 10

        # IV skew
        if avg_ce_iv > 0 and avg_pe_iv > 0:
            iv_skew = avg_pe_iv / avg_ce_iv
            if iv_skew > 1.3:
                score += 10
                reason_parts.append("High put IV (contrarian bullish)")
            elif iv_skew < 0.7:
                score -= 10

        # OI change
        if pe_oi_change > ce_oi_change * 1.5 and pe_oi_change > 0:
            score += 10
            reason_parts.append("Put writing buildup")
        elif ce_oi_change > pe_oi_change * 1.5 and ce_oi_change > 0:
            score -= 10

        score = max(0, min(100, score))
        detail = {
            "pcrOI": round(pcr_oi, 2),
            "avgCeIV": round(avg_ce_iv, 2),
            "avgPeIV": round(avg_pe_iv, 2),
            "ceOIChange": ce_oi_change,
            "peOIChange": pe_oi_change,
            "topReason": reason_parts[0] if reason_parts else "Neutral options flow",
        }
        return score, detail

    # ─── News Sentiment ────────────────────────────────────────────
    def _news_sentiment(self, articles):
        if not articles:
            return 50, {"bullish": 0, "bearish": 0, "neutral": 0,
                        "topHeadline": "No recent news"}

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        top_headline = articles[0].get("title", "") if articles else ""

        for article in articles:
            title = article.get("title", "").lower()
            b_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in title)
            s_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in title)

            if b_hits > s_hits:
                bullish_count += 1
            elif s_hits > b_hits:
                bearish_count += 1
            else:
                neutral_count += 1

        total = bullish_count + bearish_count + neutral_count
        if total == 0:
            return 50, {"bullish": 0, "bearish": 0, "neutral": 0,
                        "topHeadline": top_headline}

        # Score: 100 = all bullish, 0 = all bearish, 50 = balanced
        bull_ratio = bullish_count / total
        bear_ratio = bearish_count / total
        score = 50 + (bull_ratio - bear_ratio) * 50
        score = max(0, min(100, round(score)))

        detail = {
            "bullish": bullish_count,
            "bearish": bearish_count,
            "neutral": neutral_count,
            "topHeadline": top_headline,
        }
        return score, detail

    # ─── Technical Analysis ────────────────────────────────────────
    def _technical_score(self, quote, rsi=None):
        score = 50
        reasons = []

        price = _safe_float(quote.get("lastPrice"))
        change_pct = _safe_float(quote.get("pChange"))
        high52 = _safe_float(quote.get("high52"))
        low52 = _safe_float(quote.get("low52"))
        day_high = _safe_float(quote.get("dayHigh"))
        day_low = _safe_float(quote.get("dayLow"))
        prev_close = _safe_float(quote.get("previousClose"))
        volume = _safe_float(quote.get("totalTradedVolume", quote.get("volume")))

        # 52-week position: trading near high = bullish momentum
        pos_52wk = 0.5
        if high52 > 0 and low52 > 0 and high52 != low52:
            pos_52wk = (price - low52) / (high52 - low52)  # 0 = at low, 1 = at high
            if pos_52wk > 0.85:
                score += 15
                reasons.append("Near 52-week high (strong momentum)")
            elif pos_52wk > 0.6:
                score += 8
                reasons.append("Above mid-range of 52-week band")
            elif pos_52wk < 0.2:
                score -= 15
                reasons.append("Near 52-week low (weak)")
            elif pos_52wk < 0.4:
                score -= 5

        # Intraday momentum
        if change_pct > 3:
            score += 15
            reasons.append(f"Strong rally (+{change_pct:.1f}%)")
        elif change_pct > 1:
            score += 8
            reasons.append(f"Positive momentum (+{change_pct:.1f}%)")
        elif change_pct < -3:
            score -= 15
            reasons.append(f"Sharp decline ({change_pct:.1f}%)")
        elif change_pct < -1:
            score -= 8
            reasons.append(f"Negative momentum ({change_pct:.1f}%)")

        # Day range position (trading near day high = bullish)
        day_pos = 0.5
        if day_high > day_low > 0:
            day_pos = (price - day_low) / (day_high - day_low) if day_high != day_low else 0.5
            if day_pos > 0.8:
                score += 10
                reasons.append("Trading near day high")
            elif day_pos < 0.2:
                score -= 10
                reasons.append("Trading near day low")

        # Volatility — day range as % of price
        day_range_pct = 0
        if price > 0 and day_high > 0 and day_low > 0:
            day_range_pct = ((day_high - day_low) / price) * 100

        # RSI Evaluation
        if rsi is not None:
            if rsi < 30:
                score += 15
                reasons.insert(0, f"RSI Oversold ({rsi:.1f}) -> Bullish Reversal")
            elif rsi > 70:
                score -= 15
                reasons.insert(0, f"RSI Overbought ({rsi:.1f}) -> Bearish Reversal Risk")
            elif 40 <= rsi <= 60:
                score += 5
                reasons.append(f"Neutral RSI ({rsi:.1f}) -> Trend intact")

        score = max(0, min(100, score))
        detail = {
            "pos52wk": round(pos_52wk * 100, 1),
            "changePct": round(change_pct, 2),
            "dayPos": round(day_pos * 100, 1),
            "dayRangePct": round(day_range_pct, 2),
            "rsi": round(rsi, 2) if rsi is not None else None,
            "topReason": reasons[0] if reasons else "Within normal range",
        }
        return score, detail

    # ─── Alpha / Theta / Greeks Analysis ───────────────────────────
    def _greeks_alpha_score(self, quote, option_chain):
        """
        Compute alpha, theta decay, IV percentile, and max pain proximity.
        Alpha: risk-adjusted return vs sector peers (using 52wk data as proxy).
        Theta: options time decay analysis from ATM options.
        IV Percentile: current IV vs recent range.
        Max Pain: strike with maximum OI concentration.
        """
        score = 50
        reasons = []

        price = _safe_float(quote.get("lastPrice"))
        change_pct = _safe_float(quote.get("pChange"))
        prev_close = _safe_float(quote.get("previousClose"))
        high52 = _safe_float(quote.get("high52"))
        low52 = _safe_float(quote.get("low52"))

        # ── Alpha calculation (relative strength vs benchmark) ──
        # Proxy: how well is this stock performing relative to its own
        # 52-week trajectory — stocks outperforming their range = positive alpha
        alpha = 0
        if high52 > 0 and low52 > 0 and high52 != low52:
            # Annualized return proxy from 52wk range
            midpoint = (high52 + low52) / 2
            alpha = ((price - midpoint) / midpoint) * 100  # % above/below midpoint

            # Momentum alpha: daily change > sector avg implies alpha generation
            if change_pct > 2:
                alpha += change_pct * 0.5
            elif change_pct < -2:
                alpha -= abs(change_pct) * 0.5

            if alpha > 10:
                score += 15
                reasons.append(f"Strong positive alpha ({alpha:+.1f}%)")
            elif alpha > 3:
                score += 8
                reasons.append(f"Positive alpha ({alpha:+.1f}%)")
            elif alpha < -10:
                score -= 15
                reasons.append(f"Negative alpha ({alpha:+.1f}%)")
            elif alpha < -3:
                score -= 8
                reasons.append(f"Weak alpha ({alpha:+.1f}%)")

        # ── Greeks from options chain ──
        theta_decay_rate = 0
        iv_percentile = 50
        max_pain = 0
        atm_theta = 0
        atm_gamma = 0
        atm_delta = 0
        atm_vega = 0

        if option_chain:
            chain_data = option_chain.get("data", [])
            underlying = _safe_float(option_chain.get("underlyingValue",
                                                      quote.get("lastPrice", 0)))

            if chain_data and underlying > 0:
                # Find ATM strike
                atm_strike = min(
                    (d["strikePrice"] for d in chain_data),
                    key=lambda x: abs(x - underlying), default=underlying
                )
                atm_entries = [d for d in chain_data
                               if abs(d["strikePrice"] - atm_strike) < atm_strike * 0.03]

                # ── Theta: ATM options time decay rate ──
                ce_thetas = []
                pe_thetas = []
                all_ivs = []
                for d in atm_entries:
                    ce = d.get("CE", {})
                    pe = d.get("PE", {})
                    ce_iv = _safe_float(ce.get("impliedVolatility"))
                    pe_iv = _safe_float(pe.get("impliedVolatility"))
                    ce_ltp = _safe_float(ce.get("lastPrice"))
                    pe_ltp = _safe_float(pe.get("lastPrice"))
                    ce_oi = _safe_float(ce.get("openInterest"))
                    pe_oi = _safe_float(pe.get("openInterest"))

                    if ce_iv > 0:
                        all_ivs.append(ce_iv)
                    if pe_iv > 0:
                        all_ivs.append(pe_iv)

                    # Theta proxy: premium / sqrt(DTE)
                    # For monthly options, DTE ~ 20 trading days
                    dte_proxy = 20
                    if ce_ltp > 0 and underlying > 0:
                        theta_pct = (ce_ltp / underlying) * 100 / math.sqrt(max(dte_proxy, 1))
                        ce_thetas.append(theta_pct)
                    if pe_ltp > 0 and underlying > 0:
                        theta_pct = (pe_ltp / underlying) * 100 / math.sqrt(max(dte_proxy, 1))
                        pe_thetas.append(theta_pct)

                if ce_thetas:
                    theta_decay_rate = sum(ce_thetas) / len(ce_thetas)

                # ── IV Percentile ──
                # Compare current ATM IV to OTM IVs to estimate percentile rank
                all_chain_ivs = []
                for d in chain_data:
                    for opt_type in ("CE", "PE"):
                        iv = _safe_float(d.get(opt_type, {}).get("impliedVolatility"))
                        if iv > 0:
                            all_chain_ivs.append(iv)

                if all_chain_ivs and all_ivs:
                    median_atm_iv = sum(all_ivs) / len(all_ivs)
                    sorted_ivs = sorted(all_chain_ivs)
                    # Percentile = % of IVs below current ATM IV
                    below_count = sum(1 for iv in sorted_ivs if iv <= median_atm_iv)
                    iv_percentile = (below_count / len(sorted_ivs)) * 100

                    # Low IV = options cheap = good time to buy
                    if iv_percentile < 25:
                        score += 12
                        reasons.append(f"IV percentile low ({iv_percentile:.0f}%) — cheap options")
                    elif iv_percentile < 40:
                        score += 5
                    elif iv_percentile > 80:
                        score -= 8
                        reasons.append(f"IV percentile high ({iv_percentile:.0f}%) — options expensive")
                    elif iv_percentile > 65:
                        score -= 3

                # ── Max Pain ──
                # Strike where total option buyers lose the most
                pain_map = {}
                for d in chain_data:
                    strike = d["strikePrice"]
                    ce_oi = _safe_float(d.get("CE", {}).get("openInterest"))
                    pe_oi = _safe_float(d.get("PE", {}).get("openInterest"))
                    pain = 0
                    for d2 in chain_data:
                        s2 = d2["strikePrice"]
                        # CE pain: CE buyers lose if price < strike
                        ce_oi2 = _safe_float(d2.get("CE", {}).get("openInterest"))
                        if strike < s2:
                            pain += (s2 - strike) * ce_oi2
                        # PE pain: PE buyers lose if price > strike
                        pe_oi2 = _safe_float(d2.get("PE", {}).get("openInterest"))
                        if strike > s2:
                            pain += (strike - s2) * pe_oi2
                    pain_map[strike] = pain

                if pain_map:
                    max_pain = min(pain_map, key=pain_map.get)
                    pain_distance = ((price - max_pain) / max(max_pain, 1)) * 100

                    # Price near max pain = neutral to mild gravity pull toward it
                    if abs(pain_distance) < 2:
                        score += 5
                        reasons.append(f"Near max pain ₹{max_pain:,.0f} (price magnet)")
                    elif pain_distance > 5:
                        # Price above max pain
                        score += 3
                        reasons.append(f"Trading above max pain ₹{max_pain:,.0f} (bullish)")
                    elif pain_distance < -5:
                        score -= 5
                        reasons.append(f"Below max pain ₹{max_pain:,.0f} (bearish pressure)")

                # ── Theta edge: High theta stocks = better for selling ──
                if theta_decay_rate > 0.5:
                    score += 5
                    reasons.append(f"High theta decay ({theta_decay_rate:.2f}%/day)")
                elif theta_decay_rate > 0.3:
                    score += 2

        score = max(0, min(100, score))

        detail = {
            "alpha": round(alpha, 2),
            "thetaDecayRate": round(theta_decay_rate, 3),
            "ivPercentile": round(iv_percentile, 1),
            "maxPain": round(max_pain, 2),
            "topReason": reasons[0] if reasons else "Neutral alpha/greeks",
        }
        return score, detail

    # ─── Budget-Aware Allocation ───────────────────────────────────
    def generate_picks(self, budget, risk_level, all_scores):
        """
        Given a budget in ₹, risk level, and scored stocks,
        return a list of picks with ₹ allocation per stock.
        """
        if not all_scores:
            return {"picks": [], "summary": {}}

        # Filter by signal strength based on risk level
        risk_config = {
            "conservative": {"min_score": 55, "max_stocks": 5, "max_per_stock": 0.30},
            "moderate":     {"min_score": 45, "max_stocks": 10, "max_per_stock": 0.20},
            "aggressive":   {"min_score": 35, "max_stocks": 15, "max_per_stock": 0.15},
        }
        config = risk_config.get(risk_level, risk_config["moderate"])

        # Sort by combined score descending
        # Conservative: only BUY/STRONG BUY; Moderate/Aggressive: include HOLD
        if risk_level == "conservative":
            valid_signals = ("STRONG BUY", "BUY")
        else:
            valid_signals = ("STRONG BUY", "BUY", "HOLD")

        candidates = sorted(
            [s for s in all_scores if s["combinedScore"] >= config["min_score"]
             and s["signal"] in valid_signals],
            key=lambda x: x["combinedScore"],
            reverse=True
        )

        # Sector diversification: max 2 stocks from same sector (conservative),
        # 3 for moderate, 4 for aggressive
        sector_limit = {"conservative": 2, "moderate": 3, "aggressive": 4}.get(risk_level, 3)
        sector_count = {}
        diversified = []
        for stock in candidates:
            sec = stock.get("sector", "Other")
            if sector_count.get(sec, 0) < sector_limit:
                diversified.append(stock)
                sector_count[sec] = sector_count.get(sec, 0) + 1
            if len(diversified) >= config["max_stocks"]:
                break

        if not diversified:
            return {"picks": [], "summary": {"message": "No strong picks found for this risk level"}}

        # Allocate budget proportionally to scores
        total_score = sum(s["combinedScore"] for s in diversified)
        max_alloc = budget * config["max_per_stock"]
        picks = []

        remaining = budget
        for stock in diversified:
            raw_alloc = (stock["combinedScore"] / total_score) * budget
            alloc = min(raw_alloc, max_alloc, remaining)
            qty = max(1, int(alloc / stock["price"]))
            actual_cost = qty * stock["price"]

            if actual_cost > remaining:
                qty = max(1, int(remaining / stock["price"]))
                actual_cost = qty * stock["price"]

            if actual_cost > remaining or qty == 0:
                continue

            remaining -= actual_cost
            picks.append({
                "symbol": stock["symbol"],
                "price": stock["price"],
                "changePct": stock.get("changePct", 0),
                "sector": stock["sector"],
                "combinedScore": stock["combinedScore"],
                "signal": stock["signal"],
                "marketScore": stock["marketScore"],
                "newsScore": stock["newsScore"],
                "techScore": stock["techScore"],
                "reasoning": stock["reasoning"],
                "narrative": stock.get("narrative", ""),
                "fundamentals": stock.get("fundamentals", {}),
                "newsArticles": stock.get("newsArticles", []),
                "marketDetail": stock.get("marketDetail", {}),
                "newsDetail": stock.get("newsDetail", {}),
                "techDetail": stock.get("techDetail", {}),
                "qty": qty,
                "allocation": round(actual_cost, 2),
            })

        total_invested = sum(p["allocation"] for p in picks)
        summary = {
            "totalBudget": budget,
            "totalInvested": round(total_invested, 2),
            "cashRemaining": round(budget - total_invested, 2),
            "numPicks": len(picks),
            "riskLevel": risk_level,
            "avgScore": round(sum(p["combinedScore"] for p in picks) / max(len(picks), 1), 1),
            "sectors": list(set(p["sector"] for p in picks)),
        }

        return {"picks": picks, "summary": summary}

    # ─── Pre-Market Brief ──────────────────────────────────────────
    def generate_premarket_brief(self, all_scores, market_news):
        """
        Generate a pre-market analysis brief.
        Works before market opens using previous day data + news.
        """
        if not all_scores:
            return {
                "marketOutlook": "NEUTRAL",
                "summary": "No data available for analysis.",
                "topPicks": [],
                "sectorView": {},
                "newsDigest": [],
                "generatedAt": datetime.now().isoformat(),
            }

        avg_score = sum(s["combinedScore"] for s in all_scores) / len(all_scores)

        if avg_score >= 60:
            outlook = "BULLISH"
            outlook_text = "Overall market sentiment is bullish. Multiple stocks showing strong buy signals with positive options flow and favorable news."
        elif avg_score >= 45:
            outlook = "NEUTRAL"
            outlook_text = "Market sentiment is mixed. Selective opportunities exist but caution is advised."
        else:
            outlook = "BEARISH"
            outlook_text = "Market sentiment is bearish. Consider reducing exposure or hedging positions."

        # Sector rotation analysis
        sector_scores = {}
        for s in all_scores:
            sec = s.get("sector", "Other")
            if sec not in sector_scores:
                sector_scores[sec] = []
            sector_scores[sec].append(s["combinedScore"])

        sector_view = {}
        for sec, scores in sector_scores.items():
            avg = sum(scores) / len(scores)
            sector_view[sec] = {
                "avgScore": round(avg, 1),
                "stockCount": len(scores),
                "sentiment": "Bullish" if avg >= 60 else ("Bearish" if avg < 40 else "Neutral"),
            }

        # Sort sectors by score
        sector_view = dict(sorted(sector_view.items(), key=lambda x: x[1]["avgScore"], reverse=True))

        # Top 10 picks
        top_picks = sorted(all_scores, key=lambda x: x["combinedScore"], reverse=True)[:10]

        # News digest (top 10 headlines)
        news_digest = []
        if market_news:
            for n in market_news[:10]:
                news_digest.append({
                    "title": n.get("title", ""),
                    "source": n.get("source", ""),
                    "timeAgo": n.get("timeAgo", ""),
                    "category": n.get("category", "general"),
                })

        return {
            "marketOutlook": outlook,
            "summary": outlook_text,
            "avgScore": round(avg_score, 1),
            "topPicks": [{
                "symbol": p["symbol"],
                "price": p["price"],
                "sector": p["sector"],
                "combinedScore": p["combinedScore"],
                "signal": p["signal"],
                "reasoning": p["reasoning"],
            } for p in top_picks],
            "sectorView": sector_view,
            "newsDigest": news_digest,
            "generatedAt": datetime.now().isoformat(),
            "stocksAnalyzed": len(all_scores),
        }


# Singleton
advisor = AIAdvisor()
