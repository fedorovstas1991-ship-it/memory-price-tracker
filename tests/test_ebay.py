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


# ---------------------------------------------------------------------------
# fetch_prices tests — mock Playwright so no real browser is needed.
# NOTE: live eBay scraping requires a real playwright/Chromium install.
# ---------------------------------------------------------------------------

def _make_playwright_mock(html: str):
    """Build a mock playwright context that returns *html* from page.content()."""
    # page mock
    page = AsyncMock()
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value=html)
    page.close = AsyncMock()

    # browser mock
    browser = AsyncMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    # chromium launcher
    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    # pw (playwright instance)
    pw = AsyncMock()
    pw.chromium = chromium
    pw.stop = AsyncMock()

    # async_playwright() returns a context manager whose __aenter__ yields pw
    pw_ctx = AsyncMock()
    pw_ctx.start = AsyncMock(return_value=pw)

    return pw_ctx, browser, page


@pytest.mark.asyncio
async def test_fetch_prices_uses_median():
    """EbayScraper.fetch_prices should return one entry per chip with median price."""
    html = FIXTURE_PATH.read_text()
    pw_ctx, browser, page = _make_playwright_mock(html)

    rate = 90.0
    watchlist = [("TEST-PART-001", "eMMC", "Test 16GB eMMC", "16GB")]

    with (
        patch("src.scrapers.ebay.async_playwright", return_value=pw_ctx),
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
    pw_ctx, browser, page = _make_playwright_mock("")
    page.goto = AsyncMock(side_effect=Exception("Network error"))

    watchlist = [("MISSING-CHIP", "DDR4", "Some DDR4", "4Gbit")]
    with (
        patch("src.scrapers.ebay.async_playwright", return_value=pw_ctx),
        patch("src.scrapers.ebay.WATCHLIST", watchlist),
    ):
        scraper = EbayScraper()
        entries = await scraper.fetch_prices(90.0)

    assert entries == []
