from pathlib import Path
from src.scrapers.szlcsc import parse_szlcsc_products


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "szlcsc_search.html"


def test_parse_szlcsc_products():
    html = FIXTURE_PATH.read_text()
    products = parse_szlcsc_products(html)
    assert len(products) >= 1
    first = products[0]
    assert first["part_number"] == "KLMAG1JETD-B041"
    assert first["price_cny"] == 189.35
    assert first["stock"] == 3090


def test_parse_szlcsc_empty():
    products = parse_szlcsc_products("<html><body></body></html>")
    assert products == []
