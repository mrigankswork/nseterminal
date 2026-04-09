"""
Options Strategy Analyzer
Analyzes options chain data to generate recommendations:
- Top 5 Buy (bullish directional)
- Top 5 Sell (bearish directional)
- Bull Call Spread
- Bear Call Spread
- Bull Put Spread
- Bear Put Spread
"""

import math


def _safe_float(val, default=0):
    """Safely convert to float."""
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _find_atm_strike(chain_data, underlying):
    """Find the At-The-Money strike price."""
    if not chain_data:
        return underlying
    strikes = [d["strikePrice"] for d in chain_data]
    return min(strikes, key=lambda x: abs(x - underlying))


def _get_nearby_strikes(chain_data, atm_strike, count=5):
    """Get strikes near ATM."""
    strikes = sorted(set(d["strikePrice"] for d in chain_data))
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_strike))
    start = max(0, atm_idx - count)
    end = min(len(strikes), atm_idx + count + 1)
    return strikes[start:end]


class StrategyAnalyzer:
    """Analyze options chain data and generate trading recommendations."""
    
    def analyze_stock(self, quote, option_chain):
        """
        Analyze a single stock for directional and spread opportunities.
        
        Returns a score dict with buy/sell scores and spread recommendations.
        """
        if not quote or not option_chain:
            return None
        
        symbol = quote["symbol"]
        price = _safe_float(quote["lastPrice"])
        change_pct = _safe_float(quote["pChange"])
        
        if price == 0:
            return None
        
        chain_data = option_chain.get("data", [])
        underlying = _safe_float(option_chain.get("underlyingValue", price))
        
        if not chain_data:
            return None
        
        atm_strike = _find_atm_strike(chain_data, underlying)
        
        # Calculate aggregate metrics
        total_ce_oi = sum(_safe_float(d.get("CE", {}).get("openInterest")) for d in chain_data)
        total_pe_oi = sum(_safe_float(d.get("PE", {}).get("openInterest")) for d in chain_data)
        total_ce_vol = sum(_safe_float(d.get("CE", {}).get("totalTradedVolume")) for d in chain_data)
        total_pe_vol = sum(_safe_float(d.get("PE", {}).get("totalTradedVolume")) for d in chain_data)
        
        # PCR (Put-Call Ratio) - higher PCR = bullish, lower = bearish
        pcr_oi = total_pe_oi / max(total_ce_oi, 1)
        pcr_vol = total_pe_vol / max(total_ce_vol, 1)
        
        # Average IV near ATM
        atm_entries = [d for d in chain_data if abs(d["strikePrice"] - atm_strike) < atm_strike * 0.05]
        avg_ce_iv = 0
        avg_pe_iv = 0
        if atm_entries:
            ce_ivs = [_safe_float(d.get("CE", {}).get("impliedVolatility")) for d in atm_entries]
            pe_ivs = [_safe_float(d.get("PE", {}).get("impliedVolatility")) for d in atm_entries]
            ce_ivs = [iv for iv in ce_ivs if iv > 0]
            pe_ivs = [iv for iv in pe_ivs if iv > 0]
            avg_ce_iv = sum(ce_ivs) / len(ce_ivs) if ce_ivs else 0
            avg_pe_iv = sum(pe_ivs) / len(pe_ivs) if pe_ivs else 0
        
        # --- Scoring ---
        # Buy score: higher = more bullish
        buy_score = 0
        sell_score = 0
        
        # PCR factor: PCR > 1 is bullish (more puts being written = support)
        if pcr_oi > 1.2:
            buy_score += 25
        elif pcr_oi > 1.0:
            buy_score += 15
        elif pcr_oi < 0.7:
            sell_score += 25
        elif pcr_oi < 0.9:
            sell_score += 15
        
        # Momentum factor
        if change_pct > 2:
            buy_score += 20
        elif change_pct > 0.5:
            buy_score += 10
        elif change_pct < -2:
            sell_score += 20
        elif change_pct < -0.5:
            sell_score += 10
        
        # Volume factor (high volume confirms direction)
        vol_ratio = total_ce_vol / max(total_pe_vol, 1)
        if vol_ratio > 1.5:
            buy_score += 15  # More call activity = bullish
        elif vol_ratio < 0.7:
            sell_score += 15  # More put activity = bearish
        
        # IV Skew factor
        if avg_ce_iv > 0 and avg_pe_iv > 0:
            iv_skew = avg_pe_iv / avg_ce_iv
            if iv_skew > 1.2:
                buy_score += 10  # High put IV = fear = contrarian buy
            elif iv_skew < 0.8:
                sell_score += 10
        
        # OI change analysis (near ATM)
        ce_oi_change = sum(_safe_float(d.get("CE", {}).get("changeinOpenInterest")) for d in atm_entries)
        pe_oi_change = sum(_safe_float(d.get("PE", {}).get("changeinOpenInterest")) for d in atm_entries)
        
        if pe_oi_change > ce_oi_change * 1.5:
            buy_score += 15  # Put writing = bullish
        elif ce_oi_change > pe_oi_change * 1.5:
            sell_score += 15  # Call writing = bearish
        
        # Normalize scores
        buy_score = min(buy_score, 100)
        sell_score = min(sell_score, 100)
        
        # Generate spread recommendations
        spreads = self._generate_spreads(chain_data, atm_strike, underlying)
        
        return {
            "symbol": symbol,
            "price": price,
            "changePct": round(change_pct, 2),
            "buyScore": buy_score,
            "sellScore": sell_score,
            "pcrOI": round(pcr_oi, 2),
            "pcrVol": round(pcr_vol, 2),
            "avgCeIV": round(avg_ce_iv, 2),
            "avgPeIV": round(avg_pe_iv, 2),
            "totalCeOI": total_ce_oi,
            "totalPeOI": total_pe_oi,
            "atmStrike": atm_strike,
            "spreads": spreads,
        }
    
    def _generate_spreads(self, chain_data, atm_strike, underlying):
        """Generate all four spread strategy recommendations."""
        # Get strikes sorted
        strikes = sorted(set(d["strikePrice"] for d in chain_data))
        strike_map = {}
        for d in chain_data:
            sp = d["strikePrice"]
            if sp not in strike_map:
                strike_map[sp] = d
        
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_strike))
        
        result = {}
        
        # Bull Call Spread: Buy lower strike call, Sell higher strike call
        if atm_idx < len(strikes) - 1:
            long_strike = strikes[atm_idx]
            short_strike = strikes[min(atm_idx + 2, len(strikes) - 1)]
            long_ce = strike_map.get(long_strike, {}).get("CE", {})
            short_ce = strike_map.get(short_strike, {}).get("CE", {})
            
            if long_ce and short_ce:
                long_prem = _safe_float(long_ce.get("lastPrice"))
                short_prem = _safe_float(short_ce.get("lastPrice"))
                net_debit = long_prem - short_prem
                max_profit = (short_strike - long_strike) - net_debit
                max_loss = net_debit
                breakeven = long_strike + net_debit
                
                result["bullCallSpread"] = {
                    "strategy": "Bull Call Spread",
                    "outlook": "Moderately Bullish",
                    "longStrike": long_strike,
                    "shortStrike": short_strike,
                    "longPremium": round(long_prem, 2),
                    "shortPremium": round(short_prem, 2),
                    "netDebit": round(net_debit, 2),
                    "maxProfit": round(max_profit, 2),
                    "maxLoss": round(max_loss, 2),
                    "breakeven": round(breakeven, 2),
                    "riskReward": round(max_profit / max(max_loss, 0.01), 2),
                    "longIV": _safe_float(long_ce.get("impliedVolatility")),
                    "shortIV": _safe_float(short_ce.get("impliedVolatility")),
                }
        
        # Bear Call Spread: Sell lower strike call, Buy higher strike call
        if atm_idx < len(strikes) - 1:
            short_strike = strikes[atm_idx]
            long_strike = strikes[min(atm_idx + 2, len(strikes) - 1)]
            short_ce = strike_map.get(short_strike, {}).get("CE", {})
            long_ce = strike_map.get(long_strike, {}).get("CE", {})
            
            if short_ce and long_ce:
                short_prem = _safe_float(short_ce.get("lastPrice"))
                long_prem = _safe_float(long_ce.get("lastPrice"))
                net_credit = short_prem - long_prem
                max_profit = net_credit
                max_loss = (long_strike - short_strike) - net_credit
                breakeven = short_strike + net_credit
                
                result["bearCallSpread"] = {
                    "strategy": "Bear Call Spread",
                    "outlook": "Moderately Bearish",
                    "shortStrike": short_strike,
                    "longStrike": long_strike,
                    "shortPremium": round(short_prem, 2),
                    "longPremium": round(long_prem, 2),
                    "netCredit": round(net_credit, 2),
                    "maxProfit": round(max_profit, 2),
                    "maxLoss": round(max_loss, 2),
                    "breakeven": round(breakeven, 2),
                    "riskReward": round(max_profit / max(max_loss, 0.01), 2),
                    "shortIV": _safe_float(short_ce.get("impliedVolatility")),
                    "longIV": _safe_float(long_ce.get("impliedVolatility")),
                }
        
        # Bull Put Spread: Sell higher strike put, Buy lower strike put
        if atm_idx > 0:
            short_strike = strikes[atm_idx]
            long_strike = strikes[max(atm_idx - 2, 0)]
            short_pe = strike_map.get(short_strike, {}).get("PE", {})
            long_pe = strike_map.get(long_strike, {}).get("PE", {})
            
            if short_pe and long_pe:
                short_prem = _safe_float(short_pe.get("lastPrice"))
                long_prem = _safe_float(long_pe.get("lastPrice"))
                net_credit = short_prem - long_prem
                max_profit = net_credit
                max_loss = (short_strike - long_strike) - net_credit
                breakeven = short_strike - net_credit
                
                result["bullPutSpread"] = {
                    "strategy": "Bull Put Spread",
                    "outlook": "Moderately Bullish",
                    "shortStrike": short_strike,
                    "longStrike": long_strike,
                    "shortPremium": round(short_prem, 2),
                    "longPremium": round(long_prem, 2),
                    "netCredit": round(net_credit, 2),
                    "maxProfit": round(max_profit, 2),
                    "maxLoss": round(max_loss, 2),
                    "breakeven": round(breakeven, 2),
                    "riskReward": round(max_profit / max(max_loss, 0.01), 2),
                    "shortIV": _safe_float(short_pe.get("impliedVolatility")),
                    "longIV": _safe_float(long_pe.get("impliedVolatility")),
                }
        
        # Bear Put Spread: Buy higher strike put, Sell lower strike put
        if atm_idx > 0:
            long_strike = strikes[atm_idx]
            short_strike = strikes[max(atm_idx - 2, 0)]
            long_pe = strike_map.get(long_strike, {}).get("PE", {})
            short_pe = strike_map.get(short_strike, {}).get("PE", {})
            
            if long_pe and short_pe:
                long_prem = _safe_float(long_pe.get("lastPrice"))
                short_prem = _safe_float(short_pe.get("lastPrice"))
                net_debit = long_prem - short_prem
                max_profit = (long_strike - short_strike) - net_debit
                max_loss = net_debit
                breakeven = long_strike - net_debit
                
                result["bearPutSpread"] = {
                    "strategy": "Bear Put Spread",
                    "outlook": "Moderately Bearish",
                    "longStrike": long_strike,
                    "shortStrike": short_strike,
                    "longPremium": round(long_prem, 2),
                    "shortPremium": round(short_prem, 2),
                    "netDebit": round(net_debit, 2),
                    "maxProfit": round(max_profit, 2),
                    "maxLoss": round(max_loss, 2),
                    "breakeven": round(breakeven, 2),
                    "riskReward": round(max_profit / max(max_loss, 0.01), 2),
                    "longIV": _safe_float(long_pe.get("impliedVolatility")),
                    "shortIV": _safe_float(short_pe.get("impliedVolatility")),
                }
        
        return result
    
    def get_top_recommendations(self, analyses):
        """
        Given a list of stock analyses, return top 5 buy, top 5 sell, 
        and best spread for each category.
        """
        if not analyses:
            return {
                "topBuy": [],
                "topSell": [],
                "bestBullCallSpread": [],
                "bestBearCallSpread": [],
                "bestBullPutSpread": [],
                "bestBearPutSpread": [],
            }
        
        # Top 5 Buy (highest buy score)
        by_buy = sorted(analyses, key=lambda x: x["buyScore"], reverse=True)
        top_buy = by_buy[:5]
        
        # Top 5 Sell (highest sell score)
        by_sell = sorted(analyses, key=lambda x: x["sellScore"], reverse=True)
        top_sell = by_sell[:5]
        
        # Best spreads (by risk/reward ratio)
        def get_spread_rr(analysis, spread_key):
            spread = analysis.get("spreads", {}).get(spread_key, {})
            return spread.get("riskReward", 0)
        
        best_bull_call = sorted(analyses, key=lambda x: get_spread_rr(x, "bullCallSpread"), reverse=True)
        best_bear_call = sorted(analyses, key=lambda x: get_spread_rr(x, "bearCallSpread"), reverse=True)
        best_bull_put = sorted(analyses, key=lambda x: get_spread_rr(x, "bullPutSpread"), reverse=True)
        best_bear_put = sorted(analyses, key=lambda x: get_spread_rr(x, "bearPutSpread"), reverse=True)
        
        return {
            "topBuy": top_buy[:5],
            "topSell": top_sell[:5],
            "bestBullCallSpread": [a for a in best_bull_call[:5] if a.get("spreads", {}).get("bullCallSpread")],
            "bestBearCallSpread": [a for a in best_bear_call[:5] if a.get("spreads", {}).get("bearCallSpread")],
            "bestBullPutSpread": [a for a in best_bull_put[:5] if a.get("spreads", {}).get("bullPutSpread")],
            "bestBearPutSpread": [a for a in best_bear_put[:5] if a.get("spreads", {}).get("bearPutSpread")],
        }
