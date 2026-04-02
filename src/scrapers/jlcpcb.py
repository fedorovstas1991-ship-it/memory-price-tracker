import logging
from datetime import datetime, timezone

import httpx

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

JLCPCB_API_URL = (
    "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood"
    "/selectSmtComponentList"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://jlcpcb.com",
    "Referer": "https://jlcpcb.com/parts/componentSearch",
}


def _best_price_for_qty(price_tiers: list[dict], max_qty: int = 10) -> float | None:
    """Return the lowest unit price for a tier whose startNumber <= max_qty.

    Price tiers are not guaranteed to be sorted, so we scan all of them.
    endNumber == -1 means "and above" (open-ended).
    """
    best: float | None = None
    for tier in price_tiers:
        start = tier.get("startNumber", 0)
        price = tier.get("productPrice")
        if price is None:
            continue
        if start <= max_qty:
            if best is None or price < best:
                best = price
    return best


class JLCPCBScraper(BaseScraper):
    name = "jlcpcb"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries: list[PriceEntry] = []
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, headers=BROWSER_HEADERS
        ) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                try:
                    entry = await self._fetch_one(
                        client, part_number, chip_type, description, capacity,
                        rate_usd_rub,
                    )
                    if entry:
                        entries.append(entry)
                except Exception:
                    logger.warning(
                        "JLCPCB: failed to fetch %s", part_number, exc_info=True
                    )
        return entries

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        part_number: str,
        chip_type: str,
        description: str,
        capacity: str,
        rate: float,
    ) -> PriceEntry | None:
        payload = {"keyword": part_number, "currentPage": 1, "pageSize": 25}
        resp = await client.post(JLCPCB_API_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

        items: list[dict] = (
            data.get("data", {})
            .get("componentPageInfo", {})
            .get("list", [])
        )
        if not items:
            return None

        # Prefer exact model match; fall back to first result
        item = next(
            (i for i in items if i.get("componentModelEn", "").upper() == part_number.upper()),
            items[0],
        )

        price_tiers: list[dict] = item.get("componentPrices", [])
        if not price_tiers:
            return None

        price_usd = _best_price_for_qty(price_tiers, max_qty=10)
        if price_usd is None:
            return None

        url = item.get("lcscGoodsUrl", "")
        moq = item.get("minPurchaseNum", 1)

        return PriceEntry(
            chip_type=chip_type,
            part_number=item.get("componentModelEn", part_number),
            description=item.get("describe", description),
            capacity=capacity,
            source="jlcpcb",
            price_usd=round(price_usd, 2),
            price_rub=convert_usd_to_rub(price_usd, rate),
            moq=moq,
            url=url,
            fetched_at=datetime.now(timezone.utc),
        )
