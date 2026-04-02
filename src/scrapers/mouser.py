import logging
import re
from datetime import datetime, timezone

import httpx

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"


class MouserScraper(BaseScraper):
    name = "mouser"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                try:
                    entry = await self._fetch_one(
                        client, part_number, chip_type, description, capacity, rate_usd_rub
                    )
                    if entry:
                        entries.append(entry)
                except Exception:
                    logger.warning("Mouser: failed to fetch %s", part_number, exc_info=True)
        return entries

    async def _fetch_one(
        self, client: httpx.AsyncClient,
        part_number: str, chip_type: str, description: str, capacity: str,
        rate: float,
    ) -> PriceEntry | None:
        body = {
            "SearchByPartRequest": {
                "mouserPartNumber": part_number,
                "partSearchOptions": "BeginsWith",
            }
        }
        params = {"apiKey": self.api_key}
        resp = await client.post(MOUSER_SEARCH_URL, json=body, params=params)
        resp.raise_for_status()
        data = resp.json()

        parts = data.get("SearchResults", {}).get("Parts", [])
        if not parts:
            return None

        part = parts[0]
        price_breaks = part.get("PriceBreaks", [])
        if not price_breaks:
            return None

        price_usd = self._parse_price(price_breaks[0]["Price"])
        for pb in price_breaks:
            if pb["Quantity"] <= 10:
                price_usd = self._parse_price(pb["Price"])

        return PriceEntry(
            chip_type=chip_type,
            part_number=part.get("ManufacturerPartNumber", part_number),
            description=part.get("Description", description),
            capacity=capacity,
            source="mouser",
            price_usd=round(price_usd, 2),
            price_rub=convert_usd_to_rub(price_usd, rate),
            moq=int(part.get("Min", 1)),
            url=part.get("ProductDetailUrl", ""),
            fetched_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _parse_price(price_str: str) -> float:
        cleaned = re.sub(r"[^\d.]", "", price_str)
        return float(cleaned) if cleaned else 0.0
