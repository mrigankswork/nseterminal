"""
News Service — Enhanced with Analyst Recommendations, Market Alerts, and Daily Auto-Refresh.
Fetches from Google News RSS and categorizes articles.
"""

import requests
import xml.etree.ElementTree as ET
import time
import re
import json
import os
from html import unescape
from urllib.parse import quote_plus
from datetime import datetime, timezone, timedelta


# Keywords for classification
ANALYST_KEYWORDS = [
    "upgrade", "downgrade", "target price", "price target", "rating", "buy rating",
    "sell rating", "hold rating", "outperform", "underperform", "accumulate",
    "overweight", "underweight", "neutral rating", "analyst", "brokerage",
    "recommendation", "initiates coverage", "maintains buy", "maintains sell",
]
ALERT_KEYWORDS = [
    "breaking", "urgent", "crash", "plunge", "surge", "record high", "record low",
    "circuit", "upper circuit", "lower circuit", "halt", "block deal",
    "bulk deal", "insider", "probe", "fraud", "sebi",
]
RISING_KEYWORDS = [
    "rally", "surges", "gains", "jumps", "soars", "climbs", "breakout",
    "52-week high", "all-time high", "bullish", "strong buying",
]


class NewsService:
    """Fetches and categorizes stock news with analyst recommendations."""

    CACHE_DIR = os.path.join(os.path.dirname(__file__), ".news_cache")

    def __init__(self, cache_ttl=600):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_ttl = cache_ttl  # 10 minutes for per-symbol
        self._market_news_cache = None
        self._market_news_ts = 0
        os.makedirs(self.CACHE_DIR, exist_ok=True)

    # ─── Per-symbol news ──────────────────────────────────────
    def get_news(self, symbol, max_articles=10):
        """Get categorized news articles for a stock symbol."""
        cache_key = symbol.upper()
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return cached_data

        articles = []
        queries = [
            f"{symbol} NSE stock",
            f"{symbol} share price India",
            f"{symbol} analyst recommendation",
        ]
        seen_titles = set()

        for query in queries:
            try:
                fetched = self._fetch_google_news(query)
                for article in fetched:
                    title_key = article["title"].lower().strip()[:50]
                    if title_key not in seen_titles:
                        seen_titles.add(title_key)
                        article["tags"] = self._classify(article["title"])
                        articles.append(article)
            except Exception as e:
                print(f"Error fetching news for query '{query}': {e}")

        articles = articles[:max_articles]
        self._cache[cache_key] = (time.time(), articles)
        return articles

    # ─── Broad market news feed ───────────────────────────────
    def get_market_news(self, max_articles=25):
        """Get broad market news for the dashboard news ticker."""
        # Cache for 5 minutes
        if self._market_news_cache and (time.time() - self._market_news_ts) < 300:
            return self._market_news_cache

        # Also check disk cache (daily)
        disk_cache = self._read_disk_cache("market_news")
        if disk_cache and disk_cache.get("articles"):
            cache_age_hours = (time.time() - disk_cache.get("timestamp", 0)) / 3600
            if cache_age_hours < 2:  # Within 2 hours
                self._market_news_cache = disk_cache["articles"]
                self._market_news_ts = disk_cache["timestamp"]
                return self._market_news_cache

        articles = []
        queries = [
            "NSE India stock market today",
            "Indian stock market analyst recommendation",
            "Nifty Sensex latest news",
            "NSE stocks buy sell recommendation",
        ]
        seen_titles = set()

        for query in queries:
            try:
                fetched = self._fetch_google_news(query)
                for article in fetched:
                    title_key = article["title"].lower().strip()[:50]
                    if title_key not in seen_titles:
                        seen_titles.add(title_key)
                        article["tags"] = self._classify(article["title"])
                        articles.append(article)
            except Exception as e:
                print(f"Error fetching market news: {e}")

        # Sort: prioritize analyst / alert tagged articles, then by recency
        def sort_key(a):
            priority = 0
            tags = a.get("tags", [])
            if "analyst" in tags:
                priority -= 3
            if "alert" in tags:
                priority -= 2
            if "rising" in tags:
                priority -= 1
            return priority

        articles.sort(key=sort_key)
        articles = articles[:max_articles]

        # Save to memory and disk
        self._market_news_cache = articles
        self._market_news_ts = time.time()
        self._write_disk_cache("market_news", {
            "articles": articles,
            "timestamp": time.time(),
        })

        return articles

    # ─── Internals ────────────────────────────────────────────
    def _classify(self, title):
        """Classify article into categories based on title keywords."""
        title_lower = title.lower()
        tags = []
        if any(kw in title_lower for kw in ANALYST_KEYWORDS):
            tags.append("analyst")
        if any(kw in title_lower for kw in ALERT_KEYWORDS):
            tags.append("alert")
        if any(kw in title_lower for kw in RISING_KEYWORDS):
            tags.append("rising")
        return tags

    def _fetch_google_news(self, query):
        """Fetch articles from Google News RSS feed."""
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"

        try:
            resp = self.session.get(url, timeout=8)
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            articles = []

            for item in root.findall(".//item"):
                title_el = item.find("title")
                link_el = item.find("link")
                pub_date_el = item.find("pubDate")
                source_el = item.find("source")
                desc_el = item.find("description")

                title = title_el.text if title_el is not None else ""
                link = link_el.text if link_el is not None else ""
                pub_date = pub_date_el.text if pub_date_el is not None else ""
                source = source_el.text if source_el is not None else "Unknown"

                description = ""
                if desc_el is not None and desc_el.text:
                    desc_text = unescape(desc_el.text)
                    desc_text = re.sub(r'<[^>]+>', '', desc_text)
                    description = desc_text.strip()[:200]

                if title and link:
                    articles.append({
                        "title": unescape(title),
                        "link": link,
                        "pubDate": pub_date,
                        "source": source,
                        "description": description,
                        "timeAgo": self._time_ago(pub_date),
                    })

            return articles

        except Exception as e:
            print(f"Google News RSS error: {e}")
            return []

    def _read_disk_cache(self, key):
        """Read cache from disk."""
        path = os.path.join(self.CACHE_DIR, f"{key}.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _write_disk_cache(self, key, data):
        """Write cache to disk."""
        path = os.path.join(self.CACHE_DIR, f"{key}.json")
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error writing news cache: {e}")

    @staticmethod
    def _time_ago(pub_date_str):
        """Convert RSS date string to human-readable 'time ago' format."""
        if not pub_date_str:
            return "Recently"
        try:
            from email.utils import parsedate_to_datetime
            pub_dt = parsedate_to_datetime(pub_date_str)
            now = datetime.now(timezone.utc)
            diff = now - pub_dt

            seconds = int(diff.total_seconds())
            if seconds < 60:
                return "Just now"
            elif seconds < 3600:
                mins = seconds // 60
                return f"{mins}m ago"
            elif seconds < 86400:
                hours = seconds // 3600
                return f"{hours}h ago"
            elif seconds < 604800:
                days = seconds // 86400
                return f"{days}d ago"
            else:
                weeks = seconds // 604800
                return f"{weeks}w ago"
        except Exception:
            return "Recently"


# Singleton
news_service = NewsService()
