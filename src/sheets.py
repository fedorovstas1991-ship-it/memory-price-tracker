import logging

import gspread
from google.oauth2.service_account import Credentials

from src.config import GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_PATH
from src.models import PriceEntry

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PRICES_HEADER = ["Type", "Chip", "Description", "Capacity", "Source", "Price USD", "Price RUB", "MOQ", "Link", "Updated"]
HISTORY_HEADER = ["Date", "Type", "Part Number", "Source", "Price USD"]


def _get_spreadsheet():
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID)


def update_prices_sheet(entries: list[PriceEntry]) -> None:
    sh = _get_spreadsheet()
    ws = sh.worksheet("Prices Now")
    rows = [PRICES_HEADER] + [e.to_sheets_row() for e in entries]
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    logger.info("Updated 'Prices Now' with %d entries", len(entries))


def update_history_sheet(entries: list[PriceEntry]) -> None:
    sh = _get_spreadsheet()
    ws = sh.worksheet("History")
    rows = [e.to_history_row() for e in entries]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info("Appended %d rows to 'History'", len(rows))
