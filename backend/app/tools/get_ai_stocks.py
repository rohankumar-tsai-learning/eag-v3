"""AI stocks tool with live quote retrieval (no hardcoded price data)."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Fixed AI-focused universe. Price fields are fetched live per request.
AI_STOCK_UNIVERSE = [
    {"symbol": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "sector": "AI Chips"},
    {"symbol": "MSFT", "name": "Microsoft", "exchange": "NASDAQ", "sector": "AI/Cloud"},
    {"symbol": "GOOGL", "name": "Google", "exchange": "NASDAQ", "sector": "AI/Search"},
    {"symbol": "META", "name": "Meta", "exchange": "NASDAQ", "sector": "AI/Social"},
    {"symbol": "TSLA", "name": "Tesla", "exchange": "NASDAQ", "sector": "AI/Autonomous"},
    {"symbol": "AMZN", "name": "Amazon", "exchange": "NASDAQ", "sector": "AI/Cloud"},
    {"symbol": "PLTR", "name": "Palantir", "exchange": "NYSE", "sector": "AI/Analytics"},
    {"symbol": "AI", "name": "C3.ai", "exchange": "NYSE", "sector": "AI Software"},
    {"symbol": "CRM", "name": "Salesforce", "exchange": "NYSE", "sector": "AI/CRM"},
    {"symbol": "AVGO", "name": "Broadcom", "exchange": "NASDAQ", "sector": "AI Chips"},
]


class AIStocksFetcher:
    """Fetch AI stock metadata with live quote data."""

    def __init__(self, gemini_client: Any):
        self.client = gemini_client
        self._last_successful_stocks: List[Dict[str, Any]] = []
        self._last_successful_timestamp: Optional[str] = None

    async def _fetch_quotes_batch(
        self,
        session: aiohttp.ClientSession,
        symbols: List[str],
        max_retries: int = 2,
    ) -> Dict[str, Dict[str, Any]]:
        url = "https://query1.finance.yahoo.com/v7/finance/quote"
        params = {"symbols": ",".join(symbols)}

        last_status = None
        last_error: Optional[str] = None
        for attempt in range(max_retries + 1):
            try:
                async with session.get(url, params=params, headers=REQUEST_HEADERS) as response:
                    last_status = response.status
                    if response.status == 429 and attempt < max_retries:
                        backoff_seconds = 1 + attempt
                        await asyncio.sleep(backoff_seconds)
                        continue

                    if response.status != 200:
                        last_error = f"HTTP {response.status}"
                        return {}

                    payload = await response.json()
                    results = payload.get("quoteResponse", {}).get("result", [])
                    return {
                        (item.get("symbol") or "").upper(): item
                        for item in results
                        if item.get("symbol")
                    }
            except Exception as exc:
                last_error = str(exc)

        if last_status == 429:
            logger.warning("Yahoo batch quote exhausted retries due to HTTP 429")
        elif last_status and last_status != 200:
            logger.warning("Yahoo batch quote unavailable (%s) for symbols: %s", last_error, ",".join(symbols))
        elif last_error:
            logger.warning("Yahoo batch quote failed for symbols %s: %s", ",".join(symbols), last_error)
        return {}

    async def _fetch_quote_stooq(
        self,
        session: aiohttp.ClientSession,
        stock: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        symbol = stock["symbol"].lower()
        url = f"https://stooq.com/q/l/?s={symbol}.us&i=d"

        try:
            async with session.get(url, headers=REQUEST_HEADERS) as response:
                if response.status != 200:
                    logger.warning("Stooq quote fetch failed for %s with HTTP %s", stock["symbol"], response.status)
                    return None

                raw_csv = await response.text()
                line = raw_csv.strip().splitlines()[0] if raw_csv.strip() else ""
                parts = [p.strip() for p in line.split(",") if p is not None]
                if len(parts) < 7:
                    return None

                # Stooq row format (no header):
                # Symbol,Date,Time,Open,High,Low,Close,Volume,
                open_value = parts[3] if len(parts) > 3 else None
                close_value = parts[6] if len(parts) > 6 else None
                if not close_value or close_value == "N/D":
                    return None

                current_price = float(close_value)
                previous_close = None
                if open_value and open_value != "N/D":
                    previous_close = float(open_value)

                change = None
                change_percent = None
                if isinstance(previous_close, float) and previous_close > 0:
                    change = current_price - previous_close
                    change_percent = (change / previous_close) * 100

                return {
                    **stock,
                    "currency": "USD",
                    "current_price": current_price,
                    "previous_close": previous_close,
                    "change": round(change, 4) if isinstance(change, float) else None,
                    "change_percent": round(change_percent, 4) if isinstance(change_percent, float) else None,
                    "market_time": None,
                }
        except Exception as exc:
            logger.warning("Stooq quote error for %s: %s", stock["symbol"], exc)
            return None

    @staticmethod
    def _build_stock_payload(stock: Dict[str, str], quote: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_price = quote.get("regularMarketPrice")
        previous_close = quote.get("regularMarketPreviousClose")

        if not isinstance(current_price, (int, float)):
            return None

        change = None
        change_percent = quote.get("regularMarketChangePercent")
        if isinstance(previous_close, (int, float)) and previous_close > 0:
            change = float(current_price) - float(previous_close)

        if not isinstance(change_percent, (int, float)) and isinstance(change, float):
            change_percent = (change / float(previous_close)) * 100 if previous_close else None

        return {
            **stock,
            "name": quote.get("shortName") or stock["name"],
            "currency": quote.get("currency") or "USD",
            "current_price": float(current_price),
            "previous_close": float(previous_close) if isinstance(previous_close, (int, float)) else None,
            "change": round(change, 4) if isinstance(change, float) else None,
            "change_percent": round(float(change_percent), 4) if isinstance(change_percent, (int, float)) else None,
            "market_time": quote.get("regularMarketTime"),
        }

    async def get_top_ai_stocks(self, limit: int = 10) -> Dict[str, Any]:
        logger.info("Fetching top %s AI stocks with live prices...", limit)

        try:
            limited = AI_STOCK_UNIVERSE[: max(1, min(limit, len(AI_STOCK_UNIVERSE)))]
            timeout = aiohttp.ClientTimeout(total=20)
            symbols = [stock["symbol"] for stock in limited]
            used_stooq_fallback = False

            async with aiohttp.ClientSession(timeout=timeout) as session:
                quotes_by_symbol = await self._fetch_quotes_batch(session, symbols)
                stocks = []
                missing_stocks: List[Dict[str, str]] = []

                for stock in limited:
                    quote = quotes_by_symbol.get(stock["symbol"])
                    if quote:
                        normalized = self._build_stock_payload(stock, quote)
                        if normalized:
                            stocks.append(normalized)
                            continue
                    missing_stocks.append(stock)

                if missing_stocks:
                    logger.info("Falling back to Stooq for %s symbol(s)", len(missing_stocks))
                    fallback_tasks = [self._fetch_quote_stooq(session, stock) for stock in missing_stocks]
                    fallback_results = await asyncio.gather(*fallback_tasks)
                    for item in fallback_results:
                        if item:
                            stocks.append(item)
                            used_stooq_fallback = True

            if stocks:
                self._last_successful_stocks = stocks
                self._last_successful_timestamp = datetime.now(timezone.utc).isoformat()
                status = "success"
                note = (
                    "Live quotes from Yahoo Finance quote API."
                    if not used_stooq_fallback
                    else "Live quotes via mixed providers (Yahoo Finance + Stooq fallback)."
                )
            elif self._last_successful_stocks:
                status = "success"
                note = "Live quotes temporarily rate-limited; showing most recent cached market snapshot."
                stocks = self._last_successful_stocks[:limit]
            else:
                status = "error"
                note = "Unable to fetch live quotes at the moment (provider rate-limited)."

            return {
                "status": status,
                "stocks": stocks,
                "count": len(stocks),
                "requested_count": len(limited),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "last_live_timestamp": self._last_successful_timestamp,
                "note": note,
            }
        except Exception as exc:
            logger.error("Error fetching AI stocks: %s", exc)
            return {
                "status": "error",
                "error": str(exc),
                "stocks": [],
                "count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def get_stock_prices(self, symbols: List[str]) -> Dict[str, Any]:
        logger.info("Fetching prices for symbols: %s", symbols)

        symbol_set = {s.strip().upper() for s in symbols if s and s.strip()}
        filtered = [s for s in AI_STOCK_UNIVERSE if s["symbol"] in symbol_set]

        if not filtered:
            return {
                "status": "error",
                "error": "No supported symbols requested",
                "prices": {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        timeout = aiohttp.ClientTimeout(total=20)
        symbols_list = [s["symbol"] for s in filtered]
        async with aiohttp.ClientSession(timeout=timeout) as session:
            quotes_by_symbol = await self._fetch_quotes_batch(session, symbols_list)

            prices = {}
            missing_stocks: List[Dict[str, str]] = []
            for stock in filtered:
                quote = quotes_by_symbol.get(stock["symbol"])
                if not quote:
                    missing_stocks.append(stock)
                    continue
                item = self._build_stock_payload(stock, quote)
                if not item:
                    missing_stocks.append(stock)
                    continue
                prices[item["symbol"]] = {
                    "current_price": item["current_price"],
                    "currency": item.get("currency", "USD"),
                    "change": item.get("change"),
                    "change_percent": item.get("change_percent"),
                }

            if missing_stocks:
                fallback_tasks = [self._fetch_quote_stooq(session, stock) for stock in missing_stocks]
                fallback_results = await asyncio.gather(*fallback_tasks)
                for item in fallback_results:
                    if not item:
                        continue
                    prices[item["symbol"]] = {
                        "current_price": item["current_price"],
                        "currency": item.get("currency", "USD"),
                        "change": item.get("change"),
                        "change_percent": item.get("change_percent"),
                    }

        return {
            "status": "success" if prices else "error",
            "symbols": list(symbol_set),
            "prices": prices,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def create_ai_stocks_fetcher(gemini_client: Any) -> AIStocksFetcher:
    """Factory function to create AIStocksFetcher instance."""
    return AIStocksFetcher(gemini_client)
