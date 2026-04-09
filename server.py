"""
Flask API Server for NSE Trading Bot
Serves live data, backtesting results, and strategy recommendations.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from nse_service import nse
from backtester import Backtester
from strategy_analyzer import StrategyAnalyzer
from news_service import news_service
from paper_trader import paper_trader
from ai_advisor import advisor
from strategy_engine import strategy_engine
from auto_trader import auto_trader
from crypto_trader import crypto_trader
import yfinance_service
import threading
import time
import json
import os
from datetime import datetime

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)


@app.route("/")
def serve_index():
    return app.send_static_file("index.html")

backtester = Backtester()
analyzer = StrategyAnalyzer()

# Cache for recommendations (expensive to compute)
_cache = {
    "recommendations": None,
    "last_updated": 0,
    "market_data": None,
}
_advisor_cache = {
    "scores": [],
    "last_updated": 0,
}
_strategy_cache = {
    "strategy": None,
    "last_updated": 0,
    "budget": 0,
    "risk_level": "moderate",
    "refresh_count": 0,
    "active": False,  # Only auto-refresh after first generation
}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 5 minutes
_strategy_refresh_timer = None

# Stocks to analyze (top 100 F&O stocks — NIFTY 50 + Next 50)
SCAN_STOCKS = nse.ALL_MAJOR_STOCKS


def _fetch_recommendations():
    """Background task to fetch and analyze all stocks + AI advisor scores."""
    analyses = []
    ai_scores = []
    failures = 0
    
    for symbol in SCAN_STOCKS:
        try:
            quote = nse.get_equity_quote(symbol)
            if not quote:
                failures += 1
                if failures >= 3 and len(analyses) == 0:
                    print("NSE appears unreachable, using demo data")
                    return []
                continue
            failures = 0
            
            option_chain = nse.get_option_chain(symbol)
            
            # Options-based analysis (only if chain available)
            if option_chain:
                result = analyzer.analyze_stock(quote, option_chain)
                if result:
                    analyses.append(result)
            
            # AI Advisor scoring (works even without options)
            try:
                news = news_service.get_news(symbol, max_articles=5)
            except Exception:
                news = []
            ai_result = advisor.score_stock(symbol, quote, option_chain, news)
            if ai_result:
                ai_scores.append(ai_result)
            
            time.sleep(0.3)  # Rate limiting
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")
            failures += 1
            if failures >= 3 and len(analyses) == 0:
                print("NSE appears unreachable, using demo data")
                return []
            continue
    
    with _cache_lock:
        if analyses:
            recs = analyzer.get_top_recommendations(analyses)
            _cache["recommendations"] = recs
            _cache["last_updated"] = time.time()
        if ai_scores:
            _advisor_cache["scores"] = ai_scores
            _advisor_cache["last_updated"] = time.time()
    
    # Inject scores into the auto trader if it's running
    if ai_scores and auto_trader.running:
        auto_trader.inject_scores(ai_scores)
    
    print(f"Updated: {len(analyses)} options analyses, {len(ai_scores)} AI scores")
    return analyses


def _generate_quick_scores():
    """Quick-score top 20 stocks for instant strategy (no options chain, just quotes + news).
    Used as fallback when full scan hasn't completed yet."""
    quick_stocks = SCAN_STOCKS[:20]
    scores = []
    for symbol in quick_stocks:
        try:
            quote = nse.get_equity_quote(symbol)
            if not quote:
                continue
            try:
                news = news_service.get_news(symbol, max_articles=3)
            except Exception:
                news = []
            result = advisor.score_stock(symbol, quote, None, news)
            if result:
                scores.append(result)
            time.sleep(0.2)
        except Exception as e:
            print(f"[QuickScore] Error on {symbol}: {e}")
            continue
    print(f"[QuickScore] Generated {len(scores)} quick scores")
    return scores


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": time.time()})


@app.route("/api/stocks/top")
def top_stocks():
    """Get NIFTY 50 top gainers and losers."""
    data = nse.get_top_gainers_losers()
    if not data:
        return jsonify({"error": "Could not fetch market data"}), 503
    return jsonify(data)


@app.route("/api/stock/<symbol>/quote")
def stock_quote(symbol):
    """Get live quote for a symbol."""
    quote = nse.get_equity_quote(symbol.upper())
    if not quote:
        return jsonify({"error": f"Could not fetch quote for {symbol}"}), 503
    return jsonify(quote)


@app.route("/api/stock/<symbol>/history")
def stock_history(symbol):
    """Get historical OHLCV data — 5 years via yfinance."""
    period = request.args.get("period", "5y")
    data = yfinance_service.get_historical_data(symbol.upper(), period=period)
    if not data:
        return jsonify({"error": f"Could not fetch history for {symbol}"}), 503
    return jsonify(data)


@app.route("/api/stock/<symbol>/live")
def stock_live(symbol):
    """Get real-time quote for live polling."""
    quote = nse.get_equity_quote(symbol.upper())
    if not quote:
        return jsonify({"error": "Could not fetch live quote"}), 503
    quote["timestamp"] = datetime.now().isoformat()
    return jsonify(quote)


@app.route("/api/market/status")
def market_status():
    """Get market open/closed status."""
    now = datetime.now()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    hour = now.hour
    is_weekday = weekday < 5
    # NSE market hours: 9:00 AM to 5:00 PM IST
    market_open = (
        is_weekday
        and (hour >= 9 and hour < 17)
    )
    return jsonify({
        "isOpen": market_open,
        "timestamp": now.isoformat(),
        "message": "Market is OPEN" if market_open else "Market is CLOSED",
    })


@app.route("/api/stock/<symbol>/options")
def stock_options(symbol):
    """Get options chain for a symbol."""
    chain = nse.get_option_chain(symbol.upper())
    if not chain:
        return jsonify({"error": f"Could not fetch options for {symbol}"}), 503
    return jsonify(chain)


@app.route("/api/stock/<symbol>/news")
def stock_news(symbol):
    """Get news articles for a stock symbol."""
    articles = news_service.get_news(symbol.upper())
    if not articles:
        # Return demo news
        articles = _get_demo_news(symbol.upper())
    return jsonify({"symbol": symbol.upper(), "articles": articles})


@app.route("/api/market/news")
def market_news():
    """Get broad market news feed for dashboard ticker."""
    articles = news_service.get_market_news()
    if not articles:
        articles = _get_demo_market_news()
    return jsonify({"articles": articles, "timestamp": time.time()})



def _get_demo_news(symbol):
    """Generate demo news when RSS is unavailable."""
    import random
    headlines = [
        f"{symbol} shares rally on strong quarterly earnings beat",
        f"Analysts upgrade {symbol} target price citing robust growth outlook",
        f"{symbol} announces expansion plans in emerging markets",
        f"FII stake in {symbol} increases in latest quarterly filing",
        f"{symbol} board approves dividend payout; stock gains momentum",
        f"Technical analysis: {symbol} forms bullish breakout pattern",
        f"Sector rotation favors {symbol} as market sentiment improves",
        f"{symbol} management guidance exceeds Street expectations",
    ]
    sources = ["ET Markets", "Moneycontrol", "LiveMint", "Business Standard", "NDTV Profit", "Zee Business"]
    times = ["15m ago", "1h ago", "2h ago", "4h ago", "6h ago", "1d ago", "2d ago", "3d ago"]
    
    return [
        {
            "title": h,
            "link": "#",
            "source": random.choice(sources),
            "description": f"Read more about {symbol}'s latest market developments and analyst commentary.",
            "timeAgo": times[i],
            "pubDate": "",
            "tags": [],
        }
        for i, h in enumerate(headlines)
    ]


def _get_demo_market_news():
    """Generate demo market news when RSS is unavailable."""
    import random
    headlines = [
        {"title": "RELIANCE: Morgan Stanley maintains OVERWEIGHT with target price of Rs 2,800", "tags": ["analyst"]},
        {"title": "Markets rally as FII inflows hit Rs 5,000 crore in single session", "tags": ["alert"]},
        {"title": "TCS surges 3% on strong deal wins in Q4; analysts see further upside", "tags": ["rising", "analyst"]},
        {"title": "HDFC Bank reports 18% growth in net profit; exceeds Street estimates", "tags": []},
        {"title": "Goldman Sachs upgrades INFY to BUY from HOLD; raises target to Rs 1,900", "tags": ["analyst"]},
        {"title": "Nifty 50 breaks above 22,500 resistance; technical analysts see bullish breakout", "tags": ["rising"]},
        {"title": "SEBI tightens F&O margin rules; impact on retail traders expected", "tags": ["alert"]},
        {"title": "BAJFINANCE hits upper circuit after strong quarterly numbers", "tags": ["rising", "alert"]},
        {"title": "Jefferies initiates coverage on SBIN with BUY rating and Rs 850 target", "tags": ["analyst"]},
        {"title": "Auto sector outlook positive: TATAMOTORS, MARUTI expected to outperform", "tags": ["analyst"]},
        {"title": "RBI holds repo rate steady; banking stocks react positively", "tags": []},
        {"title": "WIPRO sees highest delivery volume in 6 months amid restructuring hopes", "tags": ["rising"]},
    ]
    sources = ["ET Markets", "Moneycontrol", "LiveMint", "Business Standard", "NDTV Profit", "Reuters"]
    times = ["5m ago", "15m ago", "32m ago", "1h ago", "2h ago", "3h ago", "4h ago", "5h ago", "6h ago", "8h ago", "1d ago", "1d ago"]

    return [
        {
            "title": h["title"],
            "link": "#",
            "source": random.choice(sources),
            "description": "",
            "timeAgo": times[i % len(times)],
            "pubDate": "",
            "tags": h["tags"],
        }
        for i, h in enumerate(headlines)
    ]


# ============================================================
# Paper Trading Endpoints
# ============================================================

@app.route("/api/paper/portfolio")
def paper_portfolio():
    """Get paper trading portfolio with live P&L and breaking news."""
    # Try to fetch live prices and news for all positions
    live_prices = {}
    news_alerts = {}
    
    for symbol in paper_trader.positions:
        quote = nse.get_equity_quote(symbol)
        if quote and quote.get("lastPrice"):
            live_prices[symbol] = quote["lastPrice"]
        
        # Real-time news check for active positions
        try:
            articles = news_service.get_news(symbol, max_articles=3)
            # Filter for breaking news or analyst alerts
            alerts = [a for a in articles if "alert" in a.get("tags", []) or "analyst" in a.get("tags", [])]
            if alerts:
                news_alerts[symbol] = alerts
        except Exception as e:
            print(f"Error fetching live news for {symbol}: {e}")

    portfolio = paper_trader.get_portfolio(live_prices)
    
    # Inject live news into portfolio positions
    for pos in portfolio.get("positions", []):
        sym = pos["symbol"]
        if sym in news_alerts:
            pos["latestNews"] = news_alerts[sym]
            
    return jsonify(portfolio)


@app.route("/api/paper/buy", methods=["POST"])
def paper_buy():
    """Place a paper buy order."""
    data = request.json or {}
    symbol = data.get("symbol", "").upper()
    qty = data.get("qty", 0)

    if not symbol or not qty:
        return jsonify({"error": "symbol and qty are required"}), 400

    # Get current market price
    price = data.get("price", 0)
    if not price:
        quote = nse.get_equity_quote(symbol)
        if quote and quote.get("lastPrice"):
            price = quote["lastPrice"]
        else:
            return jsonify({"error": f"Cannot get live price for {symbol}. Market may be closed."}), 503

    result = paper_trader.buy(symbol, qty, price)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/paper/sell", methods=["POST"])
def paper_sell():
    """Place a paper sell order."""
    data = request.json or {}
    symbol = data.get("symbol", "").upper()
    qty = data.get("qty", 0)

    if not symbol or not qty:
        return jsonify({"error": "symbol and qty are required"}), 400

    price = data.get("price", 0)
    if not price:
        quote = nse.get_equity_quote(symbol)
        if quote and quote.get("lastPrice"):
            price = quote["lastPrice"]
        else:
            return jsonify({"error": f"Cannot get live price for {symbol}. Market may be closed."}), 503

    result = paper_trader.sell(symbol, qty, price)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/paper/trades")
def paper_trades():
    """Get paper trading history."""
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"trades": paper_trader.get_trades(limit)})


@app.route("/api/paper/reset", methods=["POST"])
def paper_reset():
    """Reset paper trading portfolio."""
    result = paper_trader.reset()
    return jsonify(result)


# ============================================================
# AI Advisor Endpoints
# ============================================================

@app.route("/api/advisor/picks", methods=["POST"])
def advisor_picks():
    """Generate budget-aware AI stock picks."""
    data = request.json or {}
    budget = data.get("budget", 100000)
    risk_level = data.get("riskLevel", "moderate").lower()

    if risk_level not in ("conservative", "moderate", "aggressive"):
        return jsonify({"error": "Invalid risk level"}), 400
    if budget < 1000:
        return jsonify({"error": "Minimum budget is ₹1,000"}), 400

    # Use cached scores or compute fresh
    with _cache_lock:
        scores = _advisor_cache.get("scores", [])
        last_updated = _advisor_cache.get("last_updated", 0)

    if not scores or (time.time() - last_updated) > CACHE_TTL * 2:
        # Trigger background refresh
        threading.Thread(target=_fetch_recommendations, daemon=True).start()
        if not scores:
            return jsonify({"picks": [], "summary": {"message": "Analysis in progress, try again in 30 seconds"}}), 202

    result = advisor.generate_picks(budget, risk_level, scores)
    result["lastUpdated"] = last_updated
    return jsonify(result)


@app.route("/api/advisor/premarket")
def advisor_premarket():
    """Get pre-market analysis brief."""
    with _cache_lock:
        scores = _advisor_cache.get("scores", [])
        last_updated = _advisor_cache.get("last_updated", 0)

    if not scores or (time.time() - last_updated) > CACHE_TTL * 2:
        threading.Thread(target=_fetch_recommendations, daemon=True).start()
        if not scores:
            return jsonify({
                "marketOutlook": "LOADING",
                "summary": "Analysis in progress... Scanning 100 stocks. Please wait 30–60 seconds.",
                "topPicks": [],
                "sectorView": {},
                "newsDigest": [],
                "stocksAnalyzed": 0,
            }), 202

    try:
        market_news = news_service.get_market_news(max_articles=15)
    except Exception:
        market_news = []

    brief = advisor.generate_premarket_brief(scores, market_news)
    brief["lastUpdated"] = last_updated
    return jsonify(brief)


@app.route("/api/advisor/scores")
def advisor_all_scores():
    """Get all AI scores for the full stock universe."""
    with _cache_lock:
        scores = _advisor_cache.get("scores", [])

    # Sort by combined score descending
    sorted_scores = sorted(scores, key=lambda x: x["combinedScore"], reverse=True)
    return jsonify({
        "stocks": sorted_scores,
        "count": len(sorted_scores),
        "lastUpdated": _advisor_cache.get("last_updated", 0),
    })


# ============================================================
# Strategy Engine Endpoints
# ============================================================

@app.route("/api/strategy/generate", methods=["POST"])
def strategy_generate():
    """Generate a portfolio-aware day trading strategy."""
    data = request.json or {}
    budget = data.get("budget", 100000)
    risk_level = data.get("riskLevel", "moderate").lower()

    if risk_level not in ("conservative", "moderate", "aggressive"):
        return jsonify({"error": "Invalid risk level"}), 400
    if budget < 1000:
        return jsonify({"error": "Minimum budget is ₹1,000"}), 400

    # Get current AI scores
    with _cache_lock:
        scores = _advisor_cache.get("scores", [])
        scores_updated = _advisor_cache.get("last_updated", 0)

    # If no scores, try to generate them quickly
    if not scores:
        # Trigger background scan
        scan_thread = threading.Thread(target=_fetch_recommendations, daemon=True)
        scan_thread.start()

        # Wait up to 5 seconds for scan to produce some scores
        for _ in range(10):
            time.sleep(0.5)
            with _cache_lock:
                scores = _advisor_cache.get("scores", [])
            if scores:
                break

        # Still no scores — build minimal scores from direct quote fetching
        if not scores:
            quick_scores = _generate_quick_scores()
            if quick_scores:
                scores = quick_scores
                with _cache_lock:
                    _advisor_cache["scores"] = scores
                    _advisor_cache["last_updated"] = time.time()

    elif (time.time() - scores_updated) > CACHE_TTL * 2:
        # Stale scores — refresh in background, use what we have
        threading.Thread(target=_fetch_recommendations, daemon=True).start()

    if not scores:
        return jsonify({
            "status": "loading",
            "message": "AI engine is scanning stocks. Please retry in 30 seconds.",
        }), 202

    # Get paper portfolio state
    portfolio_data = {
        "cash": paper_trader.cash,
        "positions": paper_trader.positions,
        "initial_capital": paper_trader.initial_capital,
        "trades": paper_trader.trades[-10:],  # Last 10 trades
    }

    # Get market news
    try:
        market_news = news_service.get_market_news(max_articles=15)
    except Exception:
        market_news = []

    # Generate strategy
    strategy = strategy_engine.generate_strategy(
        budget, risk_level, portfolio_data, scores, market_news
    )

    # Cache it
    with _cache_lock:
        _strategy_cache["strategy"] = strategy
        _strategy_cache["last_updated"] = time.time()
        _strategy_cache["budget"] = budget
        _strategy_cache["risk_level"] = risk_level
        _strategy_cache["refresh_count"] = 0
        _strategy_cache["active"] = True

    # Start auto-refresh background thread
    _start_strategy_refresh()

    return jsonify({"strategy": strategy})


@app.route("/api/strategy/live")
def strategy_live():
    """Get the latest cached strategy with freshness info."""
    with _cache_lock:
        strategy = _strategy_cache.get("strategy")
        last_updated = _strategy_cache.get("last_updated", 0)
        refresh_count = _strategy_cache.get("refresh_count", 0)

    if not strategy:
        return jsonify({"status": "not_generated"}), 404

    age = time.time() - last_updated
    strategy["meta"]["ageSeconds"] = round(age)
    strategy["meta"]["refreshCount"] = refresh_count
    strategy["meta"]["lastUpdated"] = last_updated

    return jsonify(strategy)


def _start_strategy_refresh():
    """Start the background auto-refresh loop for strategy (every 5 min)."""
    global _strategy_refresh_timer
    if _strategy_refresh_timer:
        _strategy_refresh_timer.cancel()

    def refresh_loop():
        global _strategy_refresh_timer
        with _cache_lock:
            active = _strategy_cache.get("active", False)
            budget = _strategy_cache.get("budget", 100000)
            risk_level = _strategy_cache.get("risk_level", "moderate")
            count = _strategy_cache.get("refresh_count", 0)

        if not active:
            return

        print(f"[Strategy] Auto-refresh #{count + 1} starting...")

        # Refresh AI scores first
        _fetch_recommendations()

        # Re-generate strategy with fresh data
        with _cache_lock:
            scores = _advisor_cache.get("scores", [])

        portfolio_data = {
            "cash": paper_trader.cash,
            "positions": paper_trader.positions,
            "initial_capital": paper_trader.initial_capital,
            "trades": paper_trader.trades[-10:],
        }

        try:
            market_news = news_service.get_market_news(max_articles=15)
        except Exception:
            market_news = []

        strategy = strategy_engine.generate_strategy(
            budget, risk_level, portfolio_data, scores, market_news
        )

        with _cache_lock:
            _strategy_cache["strategy"] = strategy
            _strategy_cache["last_updated"] = time.time()
            _strategy_cache["refresh_count"] = count + 1

        print(f"[Strategy] Auto-refresh #{count + 1} complete")

        # Schedule next refresh
        _strategy_refresh_timer = threading.Timer(300, refresh_loop)  # 5 min
        _strategy_refresh_timer.daemon = True
        _strategy_refresh_timer.start()

    # Schedule first auto-refresh in 5 minutes
    _strategy_refresh_timer = threading.Timer(300, refresh_loop)
    _strategy_refresh_timer.daemon = True
    _strategy_refresh_timer.start()
    print("[Strategy] Auto-refresh scheduled (every 5 min)")


@app.route("/api/advisor/monitor", methods=["POST"])
def advisor_monitor():
    """Monitor active picks — returns live prices, P&L, and sell/hold signals."""
    data = request.json or {}
    picks = data.get("picks", [])

    if not picks:
        return jsonify({"error": "No picks to monitor"}), 400

    # Get cached AI scores for score-based signals
    with _cache_lock:
        ai_scores = {s["symbol"]: s for s in _advisor_cache.get("scores", [])}

    results = []
    for pick in picks:
        symbol = pick.get("symbol", "")
        entry_price = pick.get("entryPrice", 0)
        entry_score = pick.get("entryScore", 50)

        if not symbol or not entry_price:
            continue

        # Fetch live quote
        try:
            quote = nse.get_equity_quote(symbol)
        except Exception:
            quote = None

        if not quote or not quote.get("lastPrice"):
            results.append({
                "symbol": symbol,
                "status": "unavailable",
                "signal": "HOLD",
                "signalReason": "Live quote unavailable",
                "currentPrice": entry_price,
                "pnl": 0,
                "pnlPct": 0,
            })
            continue

        current_price = quote["lastPrice"]
        pnl = current_price - entry_price
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Get current AI score
        current_score_data = ai_scores.get(symbol, {})
        current_score = current_score_data.get("combinedScore", entry_score)
        score_change = current_score - entry_score

        # REAL-TIME NEWS OVERRIDE: Fetch live news immediately (bypassing 5-min cache)
        live_news_alert = None
        try:
            live_news = news_service.get_news(symbol, max_articles=3)
            ns_score, ns_detail = advisor._news_sentiment(live_news)
            if ns_score <= 30:
                live_news_alert = {"signal": "STRONG SELL", "reason": f"BREAKING: Sharp negative news detected ({ns_detail.get('bearish')} bearish articles)", "confidence": "high"}
            elif "alert" in ns_detail.get("tags", []):
                live_news_alert = {"signal": "SELL", "reason": "Market alert / regulatory news detected", "confidence": "high"}
            elif ns_score >= 80:
                live_news_alert = {"signal": "STRONG BUY", "reason": f"BREAKING: Highly positive momentum news", "confidence": "low"}
        except Exception:
            pass

        # Determine signal (with live news taking precedence for sell alerts)
        signal = "HOLD"
        signal_reason = "Position looks stable"
        confidence = "medium"

        if live_news_alert and live_news_alert["signal"] in ["SELL", "STRONG SELL"]:
            signal = live_news_alert["signal"]
            signal_reason = live_news_alert["reason"]
            confidence = live_news_alert["confidence"]
        # Standard SELL signals
        elif pnl_pct <= -3:
            signal = "SELL"
            signal_reason = f"Stop loss triggered: {pnl_pct:.1f}% loss from entry"
            confidence = "high"
        elif pnl_pct <= -2 and score_change < -10:
            signal = "SELL"
            signal_reason = f"Deteriorating: {pnl_pct:.1f}% loss + AI score dropped by {abs(score_change):.0f}"
            confidence = "high"
        elif current_score < 30 and pnl_pct < 0:
            signal = "SELL"
            signal_reason = f"AI score critically low ({current_score}) with negative P&L"
            confidence = "medium"
        # TAKE PROFIT signals
        elif pnl_pct >= 5:
            signal = "TAKE PROFIT"
            signal_reason = f"Target reached: +{pnl_pct:.1f}% gain — consider booking profits"
            confidence = "high"
        elif pnl_pct >= 3 and score_change < -5:
            signal = "TAKE PROFIT"
            signal_reason = f"Good gain +{pnl_pct:.1f}% but momentum fading (score -{abs(score_change):.0f})"
            confidence = "medium"
        # HOLD signals
        elif pnl_pct >= 0 and current_score >= 50:
            signal = "HOLD"
            signal_reason = f"Positive trend: +{pnl_pct:.1f}% gain, AI score {current_score}"
            confidence = "high"
        elif abs(pnl_pct) < 1:
            signal = "HOLD"
            signal_reason = f"Near entry price, monitoring"
            confidence = "medium"
        else:
            signal = "HOLD"
            signal_reason = f"P&L {pnl_pct:+.1f}%, score {current_score} — no clear exit signal"
            confidence = "low"

        results.append({
            "symbol": symbol,
            "status": "live",
            "signal": signal,
            "signalReason": signal_reason,
            "confidence": confidence,
            "currentPrice": current_price,
            "entryPrice": entry_price,
            "pnl": round(pnl, 2),
            "pnlPct": round(pnl_pct, 2),
            "currentScore": current_score,
            "scoreChange": round(score_change, 1),
            "dayChange": quote.get("pChange", 0),
            "dayHigh": quote.get("dayHigh", 0),
            "dayLow": quote.get("dayLow", 0),
            "volume": quote.get("totalTradedVolume", 0),
        })

        time.sleep(0.15)  # Rate limiting

    return jsonify({
        "picks": results,
        "timestamp": datetime.now().isoformat(),
        "marketOpen": _is_market_open(),
    })


def _is_market_open():
    """Check if NSE market is currently open."""
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    return (
        weekday < 5
        and (hour >= 9 and hour < 17)
    )


@app.route("/api/recommendations")
def recommendations():
    """Get top recommendations (cached, refreshes every 5 min)."""
    force = request.args.get("force", "false").lower() == "true"
    
    with _cache_lock:
        cached = _cache["recommendations"]
        last_updated = _cache["last_updated"]
    
    if cached and not force and (time.time() - last_updated) < CACHE_TTL:
        return jsonify({
            "data": cached,
            "lastUpdated": last_updated,
            "cached": True,
        })
    
    # If we have stale cache, return it immediately and refresh in background
    if cached and not force:
        threading.Thread(target=_fetch_recommendations, daemon=True).start()
        return jsonify({
            "data": cached,
            "lastUpdated": last_updated,
            "cached": True,
            "refreshing": True,
        })
    
    # No cache at all — try to build from AI scores (fast) instead of blocking
    with _cache_lock:
        scores = _advisor_cache.get("scores", [])
    
    if scores:
        # Build signals from AI scores (instant, no NSE API calls)
        recs = _build_signals_from_scores(scores)
        # Trigger background options refresh for next time
        threading.Thread(target=_fetch_recommendations, daemon=True).start()
        return jsonify({
            "data": recs,
            "lastUpdated": time.time(),
            "cached": False,
            "source": "ai_scores",
        })
    
    # No scores either — trigger background scan and return demo data
    threading.Thread(target=_fetch_recommendations, daemon=True).start()
    return jsonify({
        "data": _get_demo_recommendations(),
        "lastUpdated": time.time(),
        "demo": True,
    })


@app.route("/api/advisor/analyze/<symbol>")
def analyze_single_stock(symbol):
    """Deep analysis for a single stock (Global Search + RSI)."""
    symbol = symbol.upper()
    quote = nse.get_equity_quote(symbol)
    if not quote:
        return jsonify({"error": f"Invalid symbol '{symbol}' or NSE is unresponsive."}), 404

    option_chain = nse.get_option_chain(symbol)
    
    try:
        news = news_service.get_news(symbol, max_articles=8)
    except Exception:
        news = []

    # Calculate live RSI using 3-month daily history
    rsi_val = None
    try:
        history = yfinance_service.get_historical_data(symbol, period="3mo")
        if history and isinstance(history, list) and len(history) > 15:
            import numpy as np
            # Delay importing backtester to avoid circular deps if they exist, though it's at top
            prices = np.array([float(d["close"]) for d in history])
            rsi_array = backtester.calculate_rsi(prices, period=14)
            latest_rsi = rsi_array[-1]
            if not np.isnan(latest_rsi):
                rsi_val = float(latest_rsi)
    except Exception as e:
        print(f"Error calculating RSI for {symbol}: {e}")

    # Generate complete AI Score
    result = advisor.score_stock(symbol, quote, option_chain, news, rsi=rsi_val)
    if not result:
        return jsonify({"error": "Failed to analyze stock data"}), 500

    return jsonify(result)


def _build_signals_from_scores(scores):
    """Build buy/sell signal cards from cached AI scores (fast, no API calls)."""
    sorted_scores = sorted(scores, key=lambda x: x["combinedScore"], reverse=True)
    
    top_buy = []
    for s in sorted_scores[:5]:
        if s["combinedScore"] >= 50:
            top_buy.append({
                "symbol": s["symbol"],
                "price": s.get("price", 0),
                "changePct": round(s.get("changePct", 0), 2),
                "buyScore": s["combinedScore"],
                "sellScore": 100 - s["combinedScore"],
                "pcrOI": round(s.get("marketDetail", {}).get("pcrOI", 1.0), 2),
                "avgCeIV": round(s.get("marketDetail", {}).get("avgCeIV", 20), 1),
                "avgPeIV": round(s.get("marketDetail", {}).get("avgPeIV", 20), 1),
                "signal": s.get("signal", "BUY"),
                "sector": s.get("sector", ""),
            })
    
    top_sell = []
    for s in sorted_scores[-5:]:
        if s["combinedScore"] <= 50:
            top_sell.append({
                "symbol": s["symbol"],
                "price": s.get("price", 0),
                "changePct": round(s.get("changePct", 0), 2),
                "buyScore": s["combinedScore"],
                "sellScore": 100 - s["combinedScore"],
                "pcrOI": round(s.get("marketDetail", {}).get("pcrOI", 1.0), 2),
                "avgCeIV": round(s.get("marketDetail", {}).get("avgCeIV", 20), 1),
                "avgPeIV": round(s.get("marketDetail", {}).get("avgPeIV", 20), 1),
                "signal": s.get("signal", "SELL"),
                "sector": s.get("sector", ""),
            })
    
    return {
        "topBuy": top_buy,
        "topSell": top_sell,
        "bestBullCallSpread": None,
        "bestBearCallSpread": None,
        "bestBullPutSpread": None,
        "bestBearPutSpread": None,
    }


@app.route("/api/backtest", methods=["POST"])
def run_backtest():
    """Run a backtest with given parameters."""
    body = request.get_json() or {}
    symbol = body.get("symbol", "RELIANCE").upper()
    strategy = body.get("strategy", "sma_crossover")
    from_date = body.get("fromDate")
    to_date = body.get("toDate")
    capital = body.get("capital", 100000)
    params = body.get("params", {})
    
    # Fetch historical data
    hist = nse.get_historical_data(symbol, from_date, to_date)
    if not hist or not hist.get("data"):
        # Return demo backtest data
        return jsonify(_get_demo_backtest(symbol, strategy))
    
    bt = Backtester(initial_capital=capital)
    result = bt.run(hist["data"], strategy, params)
    result["symbol"] = symbol
    result["strategy"] = strategy
    return jsonify(result)



def _get_demo_recommendations():
    """Generate demo recommendations when NSE is unavailable."""
    import random
    stocks = SCAN_STOCKS[:10]
    analyses = []
    
    for symbol in stocks:
        price = random.uniform(500, 5000)
        change = random.uniform(-3, 3)
        buy_score = random.randint(20, 95)
        sell_score = 100 - buy_score + random.randint(-10, 10)
        sell_score = max(0, min(100, sell_score))
        
        atm = round(price / 50) * 50
        
        analyses.append({
            "symbol": symbol,
            "price": round(price, 2),
            "changePct": round(change, 2),
            "buyScore": buy_score,
            "sellScore": sell_score,
            "pcrOI": round(random.uniform(0.5, 1.8), 2),
            "pcrVol": round(random.uniform(0.4, 2.0), 2),
            "avgCeIV": round(random.uniform(15, 45), 2),
            "avgPeIV": round(random.uniform(15, 45), 2),
            "totalCeOI": random.randint(100000, 5000000),
            "totalPeOI": random.randint(100000, 5000000),
            "atmStrike": atm,
            "spreads": {
                "bullCallSpread": {
                    "strategy": "Bull Call Spread",
                    "outlook": "Moderately Bullish",
                    "longStrike": atm,
                    "shortStrike": atm + 100,
                    "longPremium": round(random.uniform(20, 80), 2),
                    "shortPremium": round(random.uniform(5, 40), 2),
                    "netDebit": round(random.uniform(15, 50), 2),
                    "maxProfit": round(random.uniform(50, 85), 2),
                    "maxLoss": round(random.uniform(15, 50), 2),
                    "breakeven": round(atm + random.uniform(15, 50), 2),
                    "riskReward": round(random.uniform(1.0, 3.5), 2),
                    "longIV": round(random.uniform(15, 35), 2),
                    "shortIV": round(random.uniform(15, 35), 2),
                },
                "bearCallSpread": {
                    "strategy": "Bear Call Spread",
                    "outlook": "Moderately Bearish",
                    "shortStrike": atm,
                    "longStrike": atm + 100,
                    "shortPremium": round(random.uniform(20, 80), 2),
                    "longPremium": round(random.uniform(5, 40), 2),
                    "netCredit": round(random.uniform(15, 50), 2),
                    "maxProfit": round(random.uniform(15, 50), 2),
                    "maxLoss": round(random.uniform(50, 85), 2),
                    "breakeven": round(atm + random.uniform(15, 50), 2),
                    "riskReward": round(random.uniform(0.3, 1.5), 2),
                    "shortIV": round(random.uniform(15, 35), 2),
                    "longIV": round(random.uniform(15, 35), 2),
                },
                "bullPutSpread": {
                    "strategy": "Bull Put Spread",
                    "outlook": "Moderately Bullish",
                    "shortStrike": atm,
                    "longStrike": atm - 100,
                    "shortPremium": round(random.uniform(20, 80), 2),
                    "longPremium": round(random.uniform(5, 40), 2),
                    "netCredit": round(random.uniform(15, 50), 2),
                    "maxProfit": round(random.uniform(15, 50), 2),
                    "maxLoss": round(random.uniform(50, 85), 2),
                    "breakeven": round(atm - random.uniform(15, 50), 2),
                    "riskReward": round(random.uniform(0.3, 1.5), 2),
                    "shortIV": round(random.uniform(15, 35), 2),
                    "longIV": round(random.uniform(15, 35), 2),
                },
                "bearPutSpread": {
                    "strategy": "Bear Put Spread",
                    "outlook": "Moderately Bearish",
                    "longStrike": atm,
                    "shortStrike": atm - 100,
                    "longPremium": round(random.uniform(20, 80), 2),
                    "shortPremium": round(random.uniform(5, 40), 2),
                    "netDebit": round(random.uniform(15, 50), 2),
                    "maxProfit": round(random.uniform(50, 85), 2),
                    "maxLoss": round(random.uniform(15, 50), 2),
                    "breakeven": round(atm - random.uniform(15, 50), 2),
                    "riskReward": round(random.uniform(1.0, 3.5), 2),
                    "longIV": round(random.uniform(15, 35), 2),
                    "shortIV": round(random.uniform(15, 35), 2),
                },
            },
        })
    
    return analyzer.get_top_recommendations(analyses)


def _get_demo_backtest(symbol, strategy):
    """Generate demo backtest data."""
    import random
    import math
    
    data = []
    price = random.uniform(1000, 3000)
    equity = 100000
    dates = []
    
    from datetime import datetime, timedelta
    start = datetime(2025, 1, 1)
    
    for i in range(252):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        change = random.gauss(0, 0.015)
        price *= (1 + change)
        equity_change = random.gauss(0.0003, 0.008)
        equity *= (1 + equity_change)
        dates.append(d.strftime("%Y-%m-%d"))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "value": round(equity, 2),
            "price": round(price, 2),
        })
    
    total_pnl = equity - 100000
    
    return {
        "symbol": symbol,
        "strategy": strategy,
        "demo": True,
        "equityCurve": data,
        "pnlCurve": [round(random.uniform(-2000, 3000), 2) for _ in range(15)],
        "trades": [
            {"type": "BUY", "date": dates[i * 15] if i * 15 < len(dates) else dates[-1], "price": round(random.uniform(1000, 3000), 2), "shares": random.randint(10, 50)}
            for i in range(8)
        ] + [
            {"type": "SELL", "date": dates[i * 15 + 7] if i * 15 + 7 < len(dates) else dates[-1], "price": round(random.uniform(1000, 3000), 2), "shares": random.randint(10, 50), "pnl": round(random.uniform(-2000, 3000), 2), "pnlPct": round(random.uniform(-5, 8), 2)}
            for i in range(7)
        ],
        "metrics": {
            "initialCapital": 100000,
            "finalCapital": round(equity, 2),
            "totalPnL": round(total_pnl, 2),
            "totalReturnPct": round(total_pnl / 1000, 2),
            "totalTrades": 15,
            "winningTrades": random.randint(7, 11),
            "losingTrades": random.randint(4, 8),
            "winRate": round(random.uniform(50, 75), 2),
            "avgWin": round(random.uniform(1500, 3000), 2),
            "avgLoss": round(random.uniform(-2000, -500), 2),
            "maxDrawdownPct": round(random.uniform(5, 15), 2),
            "sharpeRatio": round(random.uniform(0.5, 2.5), 2),
        },
    }


# ============================================================
# Autonomous Trader Endpoints
# ============================================================

@app.route("/api/auto/start", methods=["POST"])
def auto_start():
    """Start the autonomous trading bot."""
    data = request.json or {}
    amount = data.get("amount", 0)
    # Allow 0 for resume (bot already has capital)
    if float(amount) > 0 and float(amount) < 10000:
        return jsonify({"error": "Minimum investment is ₹10,000"}), 400
    
    # Inject any existing cached scores so the bot has instant data
    cached_scores = _advisor_cache.get("scores", [])
    if cached_scores:
        auto_trader.inject_scores(cached_scores)
    
    result = auto_trader.start(amount)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/auto/stop", methods=["POST"])
def auto_stop():
    """Stop the autonomous trading bot."""
    result = auto_trader.stop()
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/auto/status")
def auto_status():
    """Get current autonomous trader status."""
    return jsonify(auto_trader.get_status())


@app.route("/api/auto/trades")
def auto_trades():
    """Get autonomous trader trade history."""
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"trades": auto_trader.get_trades(limit)})


@app.route("/api/auto/sessions")
def auto_sessions():
    """Get autonomous trader session history."""
    return jsonify({"sessions": auto_trader.get_sessions()})


@app.route("/api/auto/reset", methods=["POST"])
def auto_reset():
    """Reset the autonomous trader."""
    result = auto_trader.reset()
    return jsonify(result)

# ============================================================
# Crypto Trader Endpoints
# ============================================================

@app.route("/api/crypto/start", methods=["POST"])
def crypto_start():
    return jsonify(crypto_trader.start())

@app.route("/api/crypto/stop", methods=["POST"])
def crypto_stop():
    return jsonify(crypto_trader.stop())

@app.route("/api/crypto/reset", methods=["POST"])
def crypto_reset():
    return jsonify(crypto_trader.reset())

@app.route("/api/crypto/status")
def crypto_status():
    total_val = crypto_trader.cash + sum(p['qty'] * p['avgPrice'] for p in crypto_trader.positions.values())
    return jsonify({
        "running": crypto_trader.running,
        "capital": crypto_trader.initial_capital,
        "cash": crypto_trader.cash,
        "total_value": total_val,
        "total_pnl": crypto_trader._total_pnl,
        "pnl_pct": (total_val - crypto_trader.initial_capital) / crypto_trader.initial_capital * 100 if crypto_trader.initial_capital > 0 else 0,
        "trade_count_today": crypto_trader._trade_count_today,
        "status_message": crypto_trader._status_message,
        "positions": crypto_trader.positions,
        "target": crypto_trader.target_capital,
        "initial": crypto_trader.initial_capital
    })

@app.route("/api/crypto/trades")
def crypto_trades():
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"trades": crypto_trader.trades[-limit:]})

@app.route("/api/crypto/export")
def crypto_export():
    import json
    data = crypto_trader.export_trades()
    return app.response_class(
        response=json.dumps(data, indent=2),
        status=200,
        mimetype='application/json',
        headers={"Content-disposition": "attachment; filename=crypto_arbitrage_backtest.json"}
    )

if __name__ == "__main__":
    print("🚀 NSE Trading Bot API Server starting...")
    print("📊 Endpoints:")
    print("   GET  /api/health")
    print("   GET  /api/stocks/top")
    print("   GET  /api/stock/<symbol>/quote")
    print("   GET  /api/stock/<symbol>/history")
    print("   GET  /api/stock/<symbol>/options")
    print("   GET  /api/recommendations")
    print("   POST /api/backtest")
    print("   GET  /api/market/status")
    print("   ─── Autonomous Trader ───")
    print("   POST /api/auto/start")
    print("   POST /api/auto/stop")
    print("   GET  /api/auto/status")
    print("   GET  /api/auto/trades")
    print("   GET  /api/auto/sessions")
    print("   POST /api/auto/reset")
    app.run(host="0.0.0.0", port=5001, debug=True)
