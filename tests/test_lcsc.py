import httpx
import pytest
import respx
from src.scrapers.lcsc import LCSCScraper

LCSC_SEARCH_RESPONSE = {
    "code": 200,
    "result": {
        "productSearchResultVO": {
            "productList": [
                {
                    "productCode": "C123456",
                    "productModel": "KLMAG1JETD-B041",
                    "productDescEn": "Samsung 16GB eMMC 5.1 FBGA153",
                    "productPriceList": [
                        {"ladder": 1, "usdPrice": 3.50},
                        {"ladder": 10, "usdPrice": 2.80},
                        {"ladder": 100, "usdPrice": 2.50},
                    ],
                    "minBuyNumber": 1,
                    "productUrl": "/product-detail/C123456.html",
                }
            ]
        }
    },
}


@respx.mock
@pytest.mark.asyncio
async def test_lcsc_fetch_prices():
    respx.get("https://wmsc.lcsc.com/ftps/wm/product/search").mock(
        return_value=httpx.Response(200, json=LCSC_SEARCH_RESPONSE)
    )
    scraper = LCSCScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert len(results) >= 1
    entry = results[0]
    assert entry.part_number == "KLMAG1JETD-B041"
    assert entry.price_usd == 2.80
    assert entry.price_rub == 252.0
    assert entry.source == "lcsc"
    assert "lcsc.com" in entry.url


@respx.mock
@pytest.mark.asyncio
async def test_lcsc_handles_empty_response():
    respx.get("https://wmsc.lcsc.com/ftps/wm/product/search").mock(
        return_value=httpx.Response(200, json={"code": 200, "result": {"productSearchResultVO": {"productList": []}}})
    )
    scraper = LCSCScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert results == []
