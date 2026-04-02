import httpx
import pytest
import respx
from src.currency import get_usd_rub_rate, convert_rub_to_usd


CBR_RESPONSE = {
    "Valute": {
        "USD": {
            "Value": 90.5,
            "Previous": 89.8
        }
    }
}


@respx.mock
@pytest.mark.asyncio
async def test_get_usd_rub_rate():
    respx.get("https://www.cbr-xml-daily.ru/daily_json.js").mock(
        return_value=httpx.Response(200, json=CBR_RESPONSE)
    )
    rate = await get_usd_rub_rate()
    assert rate == 90.5


@respx.mock
@pytest.mark.asyncio
async def test_get_usd_rub_rate_fallback_on_error():
    respx.get("https://www.cbr-xml-daily.ru/daily_json.js").mock(
        return_value=httpx.Response(500)
    )
    rate = await get_usd_rub_rate()
    assert rate == 90.0


def test_convert_rub_to_usd():
    assert convert_rub_to_usd(900.0, rate=90.0) == 10.0
    assert convert_rub_to_usd(0.0, rate=90.0) == 0.0
