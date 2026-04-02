import httpx

CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
FALLBACK_RATE = 90.0


async def get_usd_rub_rate() -> float:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(CBR_URL)
            resp.raise_for_status()
            data = resp.json()
            return float(data["Valute"]["USD"]["Value"])
    except Exception:
        return FALLBACK_RATE


def convert_rub_to_usd(rub: float, rate: float) -> float:
    if rate == 0:
        return 0.0
    return round(rub / rate, 2)


def convert_usd_to_rub(usd: float, rate: float) -> float:
    return round(usd * rate, 2)
