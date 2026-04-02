from pathlib import Path
import pytest
from src.scrapers.memorymarket import parse_spot_table


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memorymarket_spot.html"


def test_parse_spot_table():
    html = FIXTURE_PATH.read_text()
    rows = parse_spot_table(html)
    assert len(rows) == 4
    first = rows[0]
    assert first["product"] == "DDR4"
    assert first["price_usd"] == 1.82
    assert isinstance(first["price_usd"], float)


def test_parse_spot_table_empty_html():
    rows = parse_spot_table("<html><body>No tables here</body></html>")
    assert rows == []
