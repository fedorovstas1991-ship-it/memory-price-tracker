from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from src.models import PriceEntry
from src.sheets import update_prices_sheet, update_history_sheet


def _make_entry(**overrides):
    defaults = dict(
        chip_type="eMMC",
        part_number="TEST-001",
        description="Test chip",
        capacity="16GB",
        source="lcsc",
        price_usd=2.80,
        price_rub=252.0,
        moq=10,
        url="https://example.com",
        fetched_at=datetime(2026, 4, 2, 14, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return PriceEntry(**defaults)


@patch("src.sheets._get_spreadsheet")
def test_update_prices_sheet(mock_get):
    mock_sheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_worksheet
    mock_get.return_value = mock_sheet

    entries = [_make_entry(), _make_entry(part_number="TEST-002", source="mouser")]
    update_prices_sheet(entries)

    mock_worksheet.clear.assert_called_once()
    assert mock_worksheet.update.called
    args = mock_worksheet.update.call_args
    rows = args[0][0]
    assert len(rows) == 3  # header + 2 entries
    assert rows[0][0] == "Type"


@patch("src.sheets._get_spreadsheet")
def test_update_history_sheet(mock_get):
    mock_sheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_worksheet
    mock_get.return_value = mock_sheet

    entries = [_make_entry()]
    update_history_sheet(entries)

    assert mock_worksheet.append_rows.called
