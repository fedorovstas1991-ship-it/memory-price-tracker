import statistics
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scrapers.ebay import parse_ebay_search, EbayScraper

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ebay_search.html"


def test_parse_ebay_search_returns_three_items():
    """Fixture has 3 real items + 1 placeholder + 1 range; only 3 should be parsed."""
    html = FIXTURE_PATH.read_text()
    items = parse_ebay_search(html)
    assert len(items) == 3


def test_parse_ebay_search_prices():
    html = FIXTURE_PATH.read_text()
    items = parse_ebay_search(html)
    prices = sorted(item["price"] for item in items)
    assert prices == [13.50, 20.00, 28.00]


def test_parse_ebay_search_titles():
    html = FIXTURE_PATH.read_text()
    items = parse_ebay_search(html)
    titles = [item["title"] for item in items]
    assert any("TEST-PART-001" in t for t in titles)
    # Placeholders must be excluded
    assert not any(t.lower() == "shop on ebay" for t in titles)


def test_parse_ebay_search_urls():
    html = FIXTURE_PATH.read_text()
    items = parse_ebay_search(html)
    for item in items:
        assert item["url"].startswith("https://www.ebay.com/itm/")


def test_parse_ebay_search_empty_html():
    items = parse_ebay_search("<html><body>No cards here</body></html>")
    assert items == []


def test_parse_ebay_search_median():
    html = FIXTURE_PATH.read_text()
    items = parse_ebay_search(html)
    prices = [item["price"] for item in items]
    median = statistics.median(prices)
    assert median == 20.00


@pytest.mark.asyncio
async def test_fetch_prices_uses_median():
    """EbayScraper.fetch_prices should return one entry per chip with median price."""
    html = FIXTURE_PATH.read_text()

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.text = html

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=fake_response)

    rate = 90.0
    watchlist = [("TEST-PART-001", "eMMC", "Test 16GB eMMC", "16GB")]

    with (
        patch("src.scrapers.ebay.httpx.AsyncClient", return_value=fake_client),
        patch("src.scrapers.ebay.WATCHLIST", watchlist),
    ):
        scraper = EbayScraper()
        entries = await scraper.fetch_prices(rate)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == "ebay"
    assert entry.part_number == "TEST-PART-001"
    assert entry.price_usd == 20.00
    assert entry.price_rub == round(20.00 * rate, 2)
    assert entry.moq == 1
    assert "TEST-PART-001" in entry.url


@pytest.mark.asyncio
async def test_fetch_prices_returns_empty_on_http_error():
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(side_effect=Exception("Network error"))

    watchlist = [("MISSING-CHIP", "DDR4", "Some DDR4", "4Gbit")]
    with (
        patch("src.scrapers.ebay.httpx.AsyncClient", return_value=fake_client),
        patch("src.scrapers.ebay.WATCHLIST", watchlist),
    ):
        scraper = EbayScraper()
        entries = await scraper.fetch_prices(90.0)

    assert entries == []
