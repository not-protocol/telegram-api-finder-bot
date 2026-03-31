"""
data_loader.py v2.0 — Evolved Brain
Multi-layer search with relevance scoring, synonyms, fuzzy matching, and filters.
"""

import re
import math
import random
import logging
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

README_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"

# ── Synonym map — expands user queries intelligently ─────────────────────────
SYNONYMS = {
    "ai":           ["machine learning", "artificial intelligence", "ml", "neural", "nlp", "gpt", "llm"],
    "ml":           ["machine learning", "ai", "artificial intelligence", "deep learning"],
    "crypto":       ["cryptocurrency", "bitcoin", "blockchain", "ethereum", "defi", "web3"],
    "weather":      ["climate", "forecast", "meteorology", "temperature", "rain"],
    "finance":      ["money", "banking", "stock", "trading", "investment", "payments", "financial"],
    "music":        ["audio", "song", "spotify", "soundcloud", "lyrics", "playlist"],
    "video":        ["youtube", "stream", "media", "movies", "film", "tv"],
    "social":       ["twitter", "instagram", "facebook", "reddit", "linkedin"],
    "maps":         ["geo", "location", "geocoding", "routing", "places", "navigation"],
    "food":         ["recipe", "nutrition", "meal", "restaurant", "cooking"],
    "health":       ["medical", "fitness", "exercise", "diet", "wellness"],
    "news":         ["articles", "headlines", "journalism", "rss", "blog"],
    "games":        ["gaming", "esports", "steam", "twitch", "xbox", "playstation"],
    "government":   ["civic", "public data", "open data", "policy"],
    "science":      ["nasa", "space", "biology", "chemistry", "physics", "research"],
    "books":        ["literature", "reading", "library", "ebooks", "isbn"],
    "database":     ["storage", "cloud", "data", "sql", "nosql"],
    "security":     ["auth", "oauth", "authentication", "2fa", "encryption"],
    "translate":    ["language", "localization", "i18n", "multilingual"],
    "email":        ["mail", "smtp", "newsletter", "inbox"],
    "sms":          ["text", "messaging", "twilio", "notification"],
    "payment":      ["stripe", "paypal", "checkout", "billing", "invoice"],
    "image":        ["photo", "picture", "visual", "photography", "unsplash"],
    "test":         ["testing", "fake", "mock", "dummy", "placeholder"],
    "sports":       ["football", "basketball", "soccer", "nba", "nfl", "cricket"],
    "animals":      ["pets", "wildlife", "dog", "cat", "fauna"],
    "jobs":         ["career", "hiring", "recruitment", "linkedin", "resume"],
    "travel":       ["flights", "hotels", "booking", "tourism", "visa"],
    "open source":  ["free", "public", "oss", "community", "github"],
}


class APIDataLoader:
    def __init__(self):
        self._apis: list[dict] = []
        self._category_index: dict[str, list[dict]] = defaultdict(list)
        self._keyword_index: dict[str, list[dict]] = defaultdict(list)
        self._search_cache: dict[str, list[dict]] = {}
        self._loaded = False

    # ── Public Interface ──────────────────────────────────────────────────────

    def load(self):
        try:
            raw_md = self._fetch_readme()
            self._apis = self._parse_readme(raw_md)
            self._build_indexes()
            self._loaded = True
            logger.info(f"✅ Indexed {len(self._apis)} APIs across {len(self._category_index)} categories")
        except Exception as e:
            logger.error(f"❌ Failed to load: {e}")
            self._apis = self._fallback_data()
            self._build_indexes()
            self._loaded = True
            logger.warning("⚠️ Running on fallback dataset")

    def search(self, query: str, max_results: int = 50,
               filter_https: bool = False,
               filter_no_auth: bool = False,
               filter_cors: bool = False) -> list[dict]:
        """
        Multi-layer ranked search:
          Layer 1 — Exact category match           (score: 100)
          Layer 2 — Partial category match          (score: 80)
          Layer 3 — Exact name match                (score: 90)
          Layer 4 — Name contains query             (score: 70)
          Layer 5 — Keyword index hit               (score: 50)
          Layer 6 — Synonym expansion               (score: 40)
          Layer 7 — Fuzzy description match         (score: 20)
        """
        if not self._loaded:
            self.load()

        cache_key = f"{query}|{filter_https}|{filter_no_auth}|{filter_cors}"
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]

        q = query.lower().strip()
        scored: dict[str, tuple[dict, int]] = {}   # name → (api, score)

        def add(api, score):
            key = api["Name"].lower()
            if key not in scored or scored[key][1] < score:
                scored[key] = (api, score)

        # Layer 1 & 2 — Category matching
        for cat, apis in self._category_index.items():
            cat_lower = cat.lower()
            if q == cat_lower:
                for api in apis: add(api, 100)
            elif q in cat_lower:
                for api in apis: add(api, 80)

        # Layer 3 & 4 — Name matching
        for api in self._apis:
            name_lower = api["Name"].lower()
            if q == name_lower:
                add(api, 90)
            elif q in name_lower:
                add(api, 70)

        # Layer 5 — Keyword index
        if q in self._keyword_index:
            for api in self._keyword_index[q]:
                add(api, 50)

        # Layer 6 — Synonym expansion
        synonyms = SYNONYMS.get(q, [])
        for syn in synonyms:
            syn_lower = syn.lower()
            for cat, apis in self._category_index.items():
                if syn_lower in cat.lower():
                    for api in apis: add(api, 40)
            if syn_lower in self._keyword_index:
                for api in self._keyword_index[syn_lower]:
                    add(api, 35)

        # Layer 7 — Fuzzy description substring
        if len(scored) < 5:
            for api in self._apis:
                text = f"{api['Name']} {api['Description']} {api['Category']}".lower()
                if q in text:
                    add(api, 20)

        # Sort by score descending
        results = [api for api, _ in sorted(scored.values(), key=lambda x: -x[1])]

        # Apply filters
        if filter_https:
            results = [a for a in results if a.get("HTTPS")]
        if filter_no_auth:
            results = [a for a in results if not a.get("Auth")]
        if filter_cors:
            results = [a for a in results if a.get("Cors") == "yes"]

        results = results[:max_results]
        self._search_cache[cache_key] = results
        return results

    def get_suggestions(self, query: str, n: int = 4) -> list[str]:
        """Fuzzy category suggestions for unknown keywords."""
        q = query.lower()
        cats = list(self._category_index.keys())
        scored = []
        for cat in cats:
            ratio = SequenceMatcher(None, q, cat.lower()).ratio()
            if ratio > 0.35:
                scored.append((cat, ratio))
        scored.sort(key=lambda x: -x[1])
        return [c for c, _ in scored[:n]]

    def get_categories(self) -> dict[str, int]:
        return {cat: len(apis) for cat, apis in sorted(
            self._category_index.items(), key=lambda x: -len(x[1])
        )}

    def get_random_api(self, category: str = None) -> dict | None:
        if category:
            pool = self._category_index.get(category, [])
            return random.choice(pool) if pool else None
        return random.choice(self._apis) if self._apis else None

    def get_trending(self, n: int = 10) -> list[dict]:
        """Return top APIs from the most popular categories."""
        popular_cats = ["Machine Learning", "Finance", "Development", "Weather",
                        "Cryptocurrency", "Games & Comics", "Music", "Science & Math"]
        results = []
        for cat in popular_cats:
            apis = self._category_index.get(cat, [])
            if apis:
                results.append(random.choice(apis))
        return results[:n]

    def get_api_by_name(self, name: str) -> dict | None:
        for api in self._apis:
            if api["Name"].lower() == name.lower():
                return api
        return None

    def get_stats(self) -> dict:
        total = len(self._apis)
        return {
            "total": total,
            "categories": len(self._category_index),
            "https_count": sum(1 for a in self._apis if a.get("HTTPS")),
            "no_auth_count": sum(1 for a in self._apis if not a.get("Auth")),
            "cors_count": sum(1 for a in self._apis if a.get("Cors") == "yes"),
            "free_and_open": sum(1 for a in self._apis if not a.get("Auth") and a.get("HTTPS")),
        }

    # ── Private Methods ───────────────────────────────────────────────────────

    def _fetch_readme(self) -> str:
        logger.info(f"📥 Fetching from GitHub...")
        req = urllib.request.Request(
            README_URL, headers={"User-Agent": "APIFinderBot/2.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")

    def _parse_readme(self, markdown: str) -> list[dict]:
        apis = []
        current_category = "Uncategorized"
        heading_re = re.compile(r"^#{2,3}\s+(.+)$")
        row_re = re.compile(
            r"^\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|"
            r"\s*([^|]*?)\s*\|"
            r"\s*([^|]*?)\s*\|"
            r"\s*(Yes|No)\s*\|"
            r"\s*([^|]+?)\s*\|",
            re.IGNORECASE,
        )
        for line in markdown.splitlines():
            line = line.strip()
            h = heading_re.match(line)
            if h:
                heading = h.group(1).strip()
                if heading.lower() not in ("index", "table of contents", ""):
                    current_category = heading
                continue
            r = row_re.match(line)
            if r:
                name = r.group(1).strip()
                if name.lower() in ("api", "name"): continue
                auth = r.group(4).strip()
                cors = r.group(6).strip().lower()
                apis.append({
                    "Name": name,
                    "Description": r.group(3).strip() or "No description.",
                    "Auth": auth if auth and auth.lower() != "null" else "",
                    "HTTPS": r.group(5).strip().lower() == "yes",
                    "Cors": "yes" if cors == "yes" else ("no" if cors == "no" else "unknown"),
                    "Link": r.group(2).strip(),
                    "Category": current_category,
                })
        logger.info(f"📊 Parsed {len(apis)} APIs")
        return apis

    def _build_indexes(self):
        self._category_index = defaultdict(list)
        self._keyword_index = defaultdict(list)
        for api in self._apis:
            self._category_index[api["Category"]].append(api)
            text = f"{api['Name']} {api['Description']} {api['Category']}"
            tokens = set(re.findall(r"\b\w{2,}\b", text.lower()))
            for token in tokens:
                self._keyword_index[token].append(api)

    def _fallback_data(self) -> list[dict]:
        return [
            {"Name": "OpenAI", "Description": "GPT models for text generation", "Auth": "apiKey", "HTTPS": True, "Cors": "yes", "Link": "https://platform.openai.com/", "Category": "Machine Learning"},
            {"Name": "OpenWeatherMap", "Description": "Current weather and forecasts", "Auth": "apiKey", "HTTPS": True, "Cors": "yes", "Link": "https://openweathermap.org/api", "Category": "Weather"},
            {"Name": "CoinGecko", "Description": "Cryptocurrency market data", "Auth": "", "HTTPS": True, "Cors": "yes", "Link": "https://www.coingecko.com/en/api", "Category": "Cryptocurrency"},
            {"Name": "GitHub API", "Description": "Repos, issues, and pull requests", "Auth": "OAuth", "HTTPS": True, "Cors": "yes", "Link": "https://docs.github.com/en/rest", "Category": "Development"},
            {"Name": "NASA APIs", "Description": "Space and astronomy data", "Auth": "apiKey", "HTTPS": True, "Cors": "yes", "Link": "https://api.nasa.gov/", "Category": "Science & Math"},
        ]
