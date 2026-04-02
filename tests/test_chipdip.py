from pathlib import Path
import pytest
from src.scrapers.chipdip import parse_chipdip_catalog


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chipdip_product.html"


def test_parse_chipdip_catalog():
    html = FIXTURE_PATH.read_text()
    items = parse_chipdip_catalog(html)
    assert len(items) == 2
    first = items[0]
    assert first["part_number"] == "IS34ML04G084-TLI"
    assert first["price_rub"] == 3530.0
    assert isinstance(first["price_rub"], float)
    assert first["price_rub"] > 0


def test_parse_chipdip_empty():
    items = parse_chipdip_catalog("<html><body>Empty</body></html>")
    assert items == []
