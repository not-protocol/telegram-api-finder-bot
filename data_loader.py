"""
data_loader.py — Fetches and indexes the public-apis/public-apis repository data.

Strategy:
  1. On startup, fetch the raw README.md from GitHub (it's a massive markdown table).
  2. Parse all API entries into structured dicts.
  3. Build an in-memory search index for O(1) category lookups and fast fuzzy matching.
  4. Cache everything — no repeated HTTP calls.
"""

import re
import random
import logging
import urllib.request
import urllib.error
from collections import defaultdict
from difflib import get_close_matches

logger = logging.getLogger(__name__)

# Public APIs README — the single source of truth
README_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"

# GitHub base URL for linking directly to sections
GITHUB_BASE = "https://github.com/public-apis/public-apis"


class APIDataLoader:
    """
    Loads, parses, and indexes all APIs from the public-apis README.

    Internal data structure per API entry:
    {
        "Name": "OpenAI",
        "Description": "OpenAI GPT models for text/image generation",
        "Auth": "apiKey",
        "HTTPS": True,
        "Cors": "yes",
        "Link": "https://platform.openai.com/",
        "Category": "Machine Learning"
    }
    """

    def __init__(self):
        self._apis: list[dict] = []
        self._category_index: dict[str, list[dict]] = defaultdict(list)
        self._keyword_index: dict[str, list[dict]] = defaultdict(list)
        self._loaded = False

    # ─── Public Interface ────────────────────────────────────────────────────

    def load(self):
        """Fetch data from GitHub and build search indexes."""
        try:
            raw_md = self._fetch_readme()
            self._apis = self._parse_readme(raw_md)
            self._build_indexes()
            self._loaded = True
            logger.info(f"✅ Indexed {len(self._apis)} APIs across {len(self._category_index)} categories")
        except Exception as e:
            logger.error(f"❌ Failed to load API data: {e}")
            # Fall back to a small embedded dataset so the bot still works
            self._apis = self._fallback_data()
            self._build_indexes()
            self._loaded = True
            logger.warning("⚠️ Running with fallback dataset")

    def search(self, keyword: str, max_results: int = 50) -> list[dict]:
        """
        Search APIs by keyword.
        Priority order:
          1. Exact category name match
          2. Keyword appears in category name
          3. Keyword appears in API name or description
        """
        if not self._loaded:
            self.load()

        kw = keyword.lower().strip()
        seen_names = set()
        results = []

        def add_unique(apis):
            for api in apis:
                key = api["Name"].lower()
                if key not in seen_names:
                    seen_names.add(key)
                    results.append(api)

        # 1. Exact category match
        for cat, apis in self._category_index.items():
            if kw == cat.lower():
                add_unique(apis)

        # 2. Partial category match
        for cat, apis in self._category_index.items():
            if kw in cat.lower() and kw != cat.lower():
                add_unique(apis)

        # 3. Keyword index (name + description tokens)
        if kw in self._keyword_index:
            add_unique(self._keyword_index[kw])

        # 4. Broad substring match across all APIs
        if len(results) < 5:
            for api in self._apis:
                searchable = (
                    api["Name"] + " " +
                    api["Description"] + " " +
                    api["Category"]
                ).lower()
                if kw in searchable:
                    key = api["Name"].lower()
                    if key not in seen_names:
                        seen_names.add(key)
                        results.append(api)

        return results[:max_results]

    def get_suggestions(self, keyword: str, n: int = 5) -> list[str]:
        """Return fuzzy-matched category suggestions for unknown keywords."""
        categories = list(self._category_index.keys())
        matches = get_close_matches(keyword.lower(), [c.lower() for c in categories], n=n, cutoff=0.4)
        return matches

    def get_categories(self) -> dict[str, int]:
        """Return dict of {category_name: api_count}."""
        return {cat: len(apis) for cat, apis in self._category_index.items()}

    def get_random_api(self) -> dict | None:
        """Return a random API entry."""
        if not self._apis:
            return None
        return random.choice(self._apis)

    def get_stats(self) -> dict:
        """Return summary statistics."""
        total = len(self._apis)
        https_count = sum(1 for a in self._apis if a.get("HTTPS"))
        no_auth_count = sum(1 for a in self._apis if not a.get("Auth"))
        cors_count = sum(1 for a in self._apis if a.get("Cors") == "yes")
        return {
            "total": total,
            "categories": len(self._category_index),
            "https_count": https_count,
            "no_auth_count": no_auth_count,
            "cors_count": cors_count,
        }

    # ─── Private Methods ──────────────────────────────────────────────────────

    def _fetch_readme(self) -> str:
        """Fetch raw README.md from GitHub."""
        logger.info(f"📥 Fetching data from {README_URL}")
        req = urllib.request.Request(
            README_URL,
            headers={"User-Agent": "APIFinderBot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")

    def _parse_readme(self, markdown: str) -> list[dict]:
        """
        Parse the public-apis README markdown into structured API dicts.

        The README format is:
        ## Category Name
        | API | Description | Auth | HTTPS | CORS |
        |-----|-------------|------|-------|------|
        | [Name](url) | Description | apiKey | Yes | Yes |
        """
        apis = []
        current_category = "Uncategorized"

        # Regex patterns
        heading_pattern = re.compile(r"^#{2,3}\s+(.+)$")
        # Match table rows: | [Name](url) | desc | auth | https | cors |
        row_pattern = re.compile(
            r"^\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|"   # | [Name](url) |
            r"\s*([^|]*?)\s*\|"                        # Description |
            r"\s*([^|]*?)\s*\|"                        # Auth |
            r"\s*(Yes|No)\s*\|"                        # HTTPS |
            r"\s*([^|]+?)\s*\|",                       # CORS |
            re.IGNORECASE,
        )

        for line in markdown.splitlines():
            line = line.strip()

            # Detect category heading
            h_match = heading_pattern.match(line)
            if h_match:
                heading = h_match.group(1).strip()
                # Skip table header pseudo-headings and nav links
                if heading.lower() not in ("index", "table of contents", ""):
                    current_category = heading
                continue

            # Detect API table row
            r_match = row_pattern.match(line)
            if r_match:
                name = r_match.group(1).strip()
                link = r_match.group(2).strip()
                description = r_match.group(3).strip()
                auth = r_match.group(4).strip()
                https_str = r_match.group(5).strip().lower()
                cors = r_match.group(6).strip().lower()

                # Skip header rows
                if name.lower() in ("api", "name"):
                    continue

                apis.append({
                    "Name": name,
                    "Description": description or "No description available.",
                    "Auth": auth if auth and auth.lower() != "null" else "",
                    "HTTPS": https_str == "yes",
                    "Cors": "yes" if cors == "yes" else ("no" if cors == "no" else "unknown"),
                    "Link": link,
                    "Category": current_category,
                })

        logger.info(f"📊 Parsed {len(apis)} API entries")
        return apis

    def _build_indexes(self):
        """Build fast lookup indexes from parsed APIs."""
        self._category_index = defaultdict(list)
        self._keyword_index = defaultdict(list)

        for api in self._apis:
            # Category index
            cat = api["Category"].lower()
            self._category_index[api["Category"]].append(api)

            # Keyword index: tokenize name + description + category
            text = f"{api['Name']} {api['Description']} {api['Category']}"
            tokens = set(re.findall(r"\b\w{2,}\b", text.lower()))
            for token in tokens:
                self._keyword_index[token].append(api)

        logger.info(f"🗂 Built indexes: {len(self._category_index)} categories, {len(self._keyword_index)} keywords")

    def _fallback_data(self) -> list[dict]:
        """Minimal fallback dataset if GitHub fetch fails."""
        return [
            {
                "Name": "OpenAI API",
                "Description": "Access GPT models for text generation and understanding",
                "Auth": "apiKey",
                "HTTPS": True,
                "Cors": "yes",
                "Link": "https://platform.openai.com/",
                "Category": "Machine Learning",
            },
            {
                "Name": "OpenWeatherMap",
                "Description": "Current weather data, forecasts, and historical weather",
                "Auth": "apiKey",
                "HTTPS": True,
                "Cors": "yes",
                "Link": "https://openweathermap.org/api",
                "Category": "Weather",
            },
            {
                "Name": "CoinGecko",
                "Description": "Cryptocurrency prices, market data, and exchange rates",
                "Auth": "",
                "HTTPS": True,
                "Cors": "yes",
                "Link": "https://www.coingecko.com/en/api",
                "Category": "Cryptocurrency",
            },
            {
                "Name": "GitHub API",
                "Description": "Access GitHub repositories, issues, pull requests and more",
                "Auth": "OAuth",
                "HTTPS": True,
                "Cors": "yes",
                "Link": "https://docs.github.com/en/rest",
                "Category": "Development",
            },
            {
                "Name": "NASA APIs",
                "Description": "Access NASA data including astronomy, space, and earth science",
                "Auth": "apiKey",
                "HTTPS": True,
                "Cors": "yes",
                "Link": "https://api.nasa.gov/",
                "Category": "Science & Math",
            },
        ]
