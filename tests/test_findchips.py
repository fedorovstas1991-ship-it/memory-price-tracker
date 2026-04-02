from pathlib import Path
from src.scrapers.findchips import parse_findchips_results


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "findchips_search.html"


def test_parse_findchips_results():
    html = FIXTURE_PATH.read_text()
    results = parse_findchips_results(html, "KLMAG1JETD-B041")
    assert len(results) == 2  # NoPrice row should be skipped
    lcsc = results[0]
    assert lcsc["distributor"] == "LCSC"
    assert lcsc["price_usd"] == 31.73  # 1-unit tier (<=10)
    assert lcsc["stock"] == 22
    winsource = results[1]
    assert winsource["distributor"] == "Win Source"
    assert winsource["price_usd"] == 29.18  # 9-unit tier (<=10)


def test_parse_findchips_empty():
    results = parse_findchips_results("<html><body></body></html>", "TEST")
    assert results == []
