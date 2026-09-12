"""Outbound clients for external market-data providers (Finnhub, CoinGecko, Frankfurter)."""

import httpx

from wealthdock_server.core.config import get_settings


class QuoteNotFoundError(Exception):
    """Raised when a provider has no data for the requested symbol."""


class QuoteProviderError(Exception):
    """Raised when a provider is unreachable or returns an unexpected error."""


COINGECKO_ID_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "LTC": "litecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "USDT": "tether",
    "USDC": "usd-coin",
}

# Currencies Frankfurter (ECB reference rates) publishes. Used for a cheap
# early rejection before making a round trip for an unsupported base.
FRANKFURTER_SUPPORTED_CURRENCIES: set[str] = {
    "EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "SEK", "NOK",
    "DKK", "PLN", "CZK", "HUF", "RON", "TRY", "ILS", "INR", "IDR", "KRW",
    "CNY", "HKD", "SGD", "MYR", "PHP", "THB", "ZAR", "BRL", "MXN", "ISK",
}

FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v2"


async def fetch_finnhub_quote(symbol: str) -> float:
    """Fetch the current price for a stock/ETF symbol from Finnhub."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        raise RuntimeError("FINNHUB_API_KEY is not configured.")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": symbol, "token": settings.finnhub_api_key},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise QuoteProviderError(f"Finnhub request failed for '{symbol}': {e}") from e

    price = data.get("c")
    if price is None or price == 0:
        raise QuoteNotFoundError(symbol)
    return float(price)


async def fetch_coingecko_price(symbol: str) -> float:
    """Fetch the current USD price for a crypto symbol from CoinGecko."""
    coin_id = COINGECKO_ID_MAP.get(symbol.upper())
    if coin_id is None:
        raise QuoteNotFoundError(symbol)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise QuoteProviderError(f"CoinGecko request failed for '{symbol}': {e}") from e

    price = data.get(coin_id, {}).get("usd")
    if price is None:
        raise QuoteNotFoundError(symbol)
    return float(price)


async def fetch_exchange_rates(base: str) -> dict[str, float]:
    """Fetch the latest ECB reference rates for `base` against all other
    currencies Frankfurter tracks, keyed by target currency code.

    Note: Frankfurter serves ECB rates, which update once daily
    (~16:00 CET) — fine for portfolio valuation, not for intraday FX.
    """
    base = base.upper()
    if base not in FRANKFURTER_SUPPORTED_CURRENCIES:
        raise QuoteNotFoundError(base)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{FRANKFURTER_BASE_URL}/latest",
                params={"base": base},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise QuoteProviderError(f"Frankfurter request failed for base '{base}': {e}") from e

    rates = data.get("rates")
    if not rates:
        raise QuoteNotFoundError(base)
    return {currency: float(rate) for currency, rate in rates.items()}
