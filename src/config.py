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
    # eMMC — Samsung
    ("KLMAG1JETD-B041", "eMMC", "Samsung 16GB eMMC 5.1", "16GB"),
    ("KLMBG4WEBD-B031", "eMMC", "Samsung 32GB eMMC 5.1", "32GB"),
    ("KLMAG2WEMB-B031", "eMMC", "Samsung 16GB eMMC 5.1", "16GB"),
    # eMMC — Kioxia
    ("THGBMHG6C1LBAIL", "eMMC", "Kioxia 8GB eMMC 5.1", "8GB"),
    ("THGBMNG5D1LBAIL", "eMMC", "Kioxia 16GB eMMC 5.1", "16GB"),
    # eMMC — Micron
    ("MTFC4GACAJCN-4M", "eMMC", "Micron 4GB eMMC 5.1", "4GB"),
    ("MTFC8GAKAJCN-4M", "eMMC", "Micron 8GB eMMC 5.1", "8GB"),
    # eMMC — SK Hynix
    ("H26M52003EQR", "eMMC", "SK Hynix 8GB eMMC 5.1", "8GB"),
    # UFS — Samsung
    ("KLUCG4J1ED-B0C1", "UFS", "Samsung 64GB UFS 2.1", "64GB"),
    ("KLUDG8UHDB-B0DC", "UFS", "Samsung 128GB UFS 3.1", "128GB"),
    # UFS — Kioxia
    ("THGJFGT0T25BAIL", "UFS", "Kioxia 32GB UFS 2.1", "32GB"),
    # UFS — Micron
    ("MTFD64AIT-4 AIT", "UFS", "Micron 64GB UFS 2.1", "64GB"),
    # DDR4 — Micron
    ("MT41K256M16TW-107", "DDR4", "Micron 4Gbit DDR4-2133", "4Gbit"),
    ("MT40A512M16LY-075E", "DDR4", "Micron 8Gbit DDR4-2666", "8Gbit"),
    # DDR4 — Samsung
    ("K4A8G165WC-BCTD", "DDR4", "Samsung 8Gbit DDR4-2400", "8Gbit"),
    ("K4AAG085WA-BCWE", "DDR4", "Samsung 16Gbit DDR4-3200", "16Gbit"),
    # DDR4 — SK Hynix
    ("H5AN8G6NDJR-XNC", "DDR4", "SK Hynix 8Gbit DDR4-3200", "8Gbit"),
    ("H5AN4G6NBJR-UHC", "DDR4", "SK Hynix 4Gbit DDR4-2400", "4Gbit"),
    # DDR5 — Samsung
    ("K4RAH165WA-BCRC", "DDR5", "Samsung 16Gbit DDR5-4800", "16Gbit"),
    # DDR5 — Micron
    ("MT60B1G16HC-48B", "DDR5", "Micron 16Gbit DDR5-4800", "16Gbit"),
    # DDR5 — SK Hynix
    ("H5CG48AGBDX018", "DDR5", "SK Hynix 16Gbit DDR5-4800", "16Gbit"),
    # LPDDR4X — Micron
    ("MT53E512M32D2DS-046", "LPDDR4X", "Micron 16Gbit LPDDR4X", "16Gbit"),
    ("MT53D512M64D4NQ-046", "LPDDR4X", "Micron 32Gbit LPDDR4X", "32Gbit"),
    # LPDDR4X — Samsung
    ("K4F6E3S4HM-MGCL", "LPDDR4X", "Samsung 16Gbit LPDDR4X", "16Gbit"),
    ("K4UBE3D4AM-MGCL", "LPDDR4X", "Samsung 32Gbit LPDDR4X", "32Gbit"),
    # LPDDR5 — SK Hynix
    ("H9JCNNNCP3MLYR-N6E", "LPDDR5", "SK Hynix 16Gbit LPDDR5", "16Gbit"),
    # NAND Flash — Samsung
    ("K9GBG08U0A-PIB0", "NAND", "Samsung 8Gbit SLC NAND", "8Gbit"),
    ("K9F2G08U0C-SCB0", "NAND", "Samsung 2Gbit SLC NAND", "2Gbit"),
    # NAND Flash — Micron
    ("MT29F2G08ABAEAH4", "NAND", "Micron 2Gbit SLC NAND", "2Gbit"),
    # NAND Flash — Kioxia
    ("TC58CVG1S3HRAIJ", "NAND", "Kioxia 2Gbit SLC NAND", "2Gbit"),
    # NOR Flash — Winbond
    ("W25Q128JVSIQ", "NOR", "Winbond 128Mbit NOR Flash", "128Mbit"),
    ("W25Q256JVEIQ", "NOR", "Winbond 256Mbit NOR Flash", "256Mbit"),
    # NOR Flash — Macronix
    ("MX25L12833FM2I-10G", "NOR", "Macronix 128Mbit NOR Flash", "128Mbit"),
    # NOR Flash — GigaDevice
    ("GD25Q127CSIG", "NOR", "GigaDevice 128Mbit NOR Flash", "128Mbit"),
]

# Scraper settings
REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
