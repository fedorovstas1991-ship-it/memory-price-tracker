import json
from pathlib import Path

import httpx
import pytest
import respx

from src.scrapers.jlcpcb import JLCPCBScraper, JLCPCB_API_URL

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jlcpcb_response.json"

JLCPCB_RESPONSE = json.loads(FIXTURE_PATH.read_text())

EMPTY_RESPONSE = {
    "code": 200,
    "data": {
        "componentPageInfo": {
            "total": 0,
            "list": [],
            "pageNum": 1,
            "pageSize": 25,
            "pages": 0,
        }
    },
    "message": None,
}


@respx.mock
@pytest.mark.asyncio
async def test_jlcpcb_fetch_prices():
    respx.post(JLCPCB_API_URL).mock(
        return_value=httpx.Response(200, json=JLCPCB_RESPONSE)
    )
    scraper = JLCPCBScraper()
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert len(results) >= 1
    entry = results[0]
    assert entry.part_number == "KLMAG1JETD-B041"
    assert entry.price_usd == 30.05
    assert entry.price_rub == 2704.65
    assert entry.source == "jlcpcb"
    assert entry.moq == 1
    assert "lcsc.com" in entry.url


@respx.mock
@pytest.mark.asyncio
async def test_jlcpcb_handles_empty_response():
    respx.post(JLCPCB_API_URL).mock(
        return_value=httpx.Response(200, json=EMPTY_RESPONSE)
    )
    scraper = JLCPCBScraper()
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert results == []
