import os
from dotenv import load_dotenv

load_dotenv()

LCSC_API_KEY = os.getenv("LCSC_API_KEY", "")
MOUSER_API_KEY = os.getenv("MOUSER_API_KEY", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json"
)

# Chips to monitor: (part_number, chip_type, description, capacity)
WATCHLIST = [
    # eMMC
    ("KLMAG1JETD-B041", "eMMC", "Samsung 16GB eMMC 5.1", "16GB"),
    ("THGBMHG6C1LBAIL", "eMMC", "Kioxia 8GB eMMC 5.1", "8GB"),
    ("MTFC4GACAJCN-4M", "eMMC", "Micron 4GB eMMC", "4GB"),
    # UFS
    ("KLUCG4J1ED-B0C1", "UFS", "Samsung 64GB UFS 2.1", "64GB"),
    ("THGJFGT0T25BAIL", "UFS", "Kioxia 32GB UFS", "32GB"),
    # DDR4
    ("MT41K256M16TW-107", "DDR4", "Micron 4Gbit DDR4", "4Gbit"),
    ("K4A8G165WC-BCTD", "DDR4", "Samsung 8Gbit DDR4", "8Gbit"),
    ("H5AN8G6NDJR-XNC", "DDR4", "SK Hynix 8Gbit DDR4", "8Gbit"),
    # LPDDR4/4X
    ("MT53E512M32D2DS-046", "LPDDR4X", "Micron 16Gbit LPDDR4X", "16Gbit"),
    ("K4F6E3S4HM-MGCL", "LPDDR4X", "Samsung 16Gbit LPDDR4X", "16Gbit"),
]

# Scraper settings
REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
