from datetime import datetime, timezone
from src.models import PriceEntry


def test_price_entry_creation():
    entry = PriceEntry(
        chip_type="eMMC",
        part_number="KLMAG1JETD-B041",
        description="Samsung 16GB eMMC",
        capacity="16GB",
        source="lcsc",
        price_usd=2.80,
        price_rub=252.0,
        moq=10,
        url="https://lcsc.com/product-detail/KLMAG1JETD-B041.html",
        fetched_at=datetime(2026, 4, 2, 14, 0, tzinfo=timezone.utc),
    )
    assert entry.chip_type == "eMMC"
    assert entry.price_usd == 2.80
    assert entry.source == "lcsc"


def test_price_entry_to_sheets_row():
    entry = PriceEntry(
        chip_type="DDR4",
        part_number="MT41K256M16",
        description="Micron 4Gbit DDR4",
        capacity="4Gbit",
        source="mouser",
        price_usd=3.15,
        price_rub=283.5,
        moq=1,
        url="https://mouser.com/ProductDetail/MT41K256M16",
        fetched_at=datetime(2026, 4, 2, 14, 0, tzinfo=timezone.utc),
    )
    row = entry.to_sheets_row()
    assert row == [
        "DDR4",
        "MT41K256M16",
        "Micron 4Gbit DDR4",
        "4Gbit",
        "mouser",
        3.15,
        283.5,
        1,
        "https://mouser.com/ProductDetail/MT41K256M16",
        "2026-04-02 14:00 UTC",
    ]


def test_price_entry_to_history_row():
    entry = PriceEntry(
        chip_type="NAND",
        part_number="TEST123",
        description="Test chip",
        capacity="8GB",
        source="memorymarket",
        price_usd=1.50,
        price_rub=135.0,
        moq=100,
        url="https://memorymarket.com",
        fetched_at=datetime(2026, 4, 2, 14, 0, tzinfo=timezone.utc),
    )
    row = entry.to_history_row()
    assert row == ["2026-04-02", "NAND", "TEST123", "memorymarket", 1.50]
