import httpx
import pytest
import respx
from src.scrapers.mouser import MouserScraper

MOUSER_RESPONSE = {
    "Errors": [],
    "SearchResults": {
        "Parts": [
            {
                "ManufacturerPartNumber": "MT41K256M16TW-107",
                "Description": "DRAM DDR3L SDRAM 4Gbit 256Mx16 1.35V",
                "PriceBreaks": [
                    {"Quantity": 1, "Price": "$4.50", "Currency": "USD"},
                    {"Quantity": 10, "Price": "$3.15", "Currency": "USD"},
                    {"Quantity": 100, "Price": "$2.80", "Currency": "USD"},
                ],
                "Min": "1",
                "MouserPartNumber": "556-MT41K256M16-107",
                "ProductDetailUrl": "https://www.mouser.com/ProductDetail/Micron/MT41K256M16TW-107",
            }
        ]
    },
}


@respx.mock
@pytest.mark.asyncio
async def test_mouser_fetch_prices():
    respx.post("https://api.mouser.com/api/v1/search/partnumber").mock(
        return_value=httpx.Response(200, json=MOUSER_RESPONSE)
    )
    scraper = MouserScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert len(results) >= 1
    entry = results[0]
    assert entry.part_number == "MT41K256M16TW-107"
    assert entry.price_usd == 3.15
    assert entry.source == "mouser"


@respx.mock
@pytest.mark.asyncio
async def test_mouser_handles_no_parts():
    respx.post("https://api.mouser.com/api/v1/search/partnumber").mock(
        return_value=httpx.Response(200, json={"Errors": [], "SearchResults": {"Parts": []}})
    )
    scraper = MouserScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert results == []
