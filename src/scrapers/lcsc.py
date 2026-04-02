import logging
from datetime import datetime, timezone

import httpx

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LCSC_SEARCH_URL = "https://wmsc.lcsc.com/ftps/wm/product/search"


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.lcsc.com/",
    "Origin": "https://www.lcsc.com",
}


class LCSCScraper(BaseScraper):
    name = "lcsc"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=BROWSER_HEADERS) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                try:
                    entry = await self._fetch_one(
                        client, part_number, chip_type, description, capacity, rate_usd_rub
                    )
                    if entry:
                        entries.append(entry)
                except Exception:
                    logger.warning("LCSC: failed to fetch %s", part_number, exc_info=True)
        return entries

    async def _fetch_one(
        self, client: httpx.AsyncClient,
        part_number: str, chip_type: str, description: str, capacity: str,
        rate: float,
    ) -> PriceEntry | None:
        params = {"keyword": part_number}
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = await client.get(LCSC_SEARCH_URL, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        products = (
            data.get("result", {})
            .get("productSearchResultVO", {})
            .get("productList", [])
        )
        if not products:
            return None

        product = products[0]
        price_list = product.get("productPriceList", [])
        if not price_list:
            return None

        price_usd = price_list[0]["usdPrice"]
        for tier in price_list:
            if tier["ladder"] <= 10:
                price_usd = tier["usdPrice"]

        product_url = product.get("productUrl", "")
        if product_url and not product_url.startswith("http"):
            product_url = f"https://www.lcsc.com{product_url}"

        return PriceEntry(
            chip_type=chip_type,
            part_number=product.get("productModel", part_number),
            description=product.get("productDescEn", description),
            capacity=capacity,
            source="lcsc",
            price_usd=round(price_usd, 2),
            price_rub=convert_usd_to_rub(price_usd, rate),
            moq=product.get("minBuyNumber", 1),
            url=product_url,
            fetched_at=datetime.now(timezone.utc),
        )
