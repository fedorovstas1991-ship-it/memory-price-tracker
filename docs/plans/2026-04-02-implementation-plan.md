# Memory Price Tracker — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Scrape DRAM/NAND Flash memory chip prices from 4 sources (LCSC, MemoryMarket, Mouser, ChipDip) every 4 hours and display in Google Sheets for procurement teams.

**Architecture:** Python async scrapers fetch prices from 2 APIs (LCSC, Mouser) and 2 HTML sources (MemoryMarket, ChipDip), normalize to USD+RUB via CBR rate, write to a shared Google Sheet with 3 tabs: current prices, spot indexes, and history.

**Tech Stack:** Python 3.11, uv, httpx, selectolax, gspread, google-auth, pytest, system cron.

---

## Project Structure

```
memory-price-tracker/
├── pyproject.toml
├── .gitignore
├── .env.example              # Template for API keys
├── src/
│   ├── __init__.py
│   ├── config.py             # Watchlist, settings
│   ├── models.py             # PriceEntry dataclass
│   ├── currency.py           # CBR RUB/USD rate
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py           # BaseScraper ABC
│   │   ├── lcsc.py           # LCSC API scraper
│   │   ├── memorymarket.py   # MemoryMarket HTML scraper
│   │   ├── mouser.py         # Mouser API scraper
│   │   └── chipdip.py        # ChipDip HTML scraper
│   ├── sheets.py             # Google Sheets writer
│   └── main.py               # Orchestrator entry point
├── tests/
│   ├── conftest.py           # Shared fixtures
│   ├── test_models.py
│   ├── test_currency.py
│   ├── fixtures/             # HTML snapshots for scraper tests
│   │   ├── memorymarket_spot.html
│   │   └── chipdip_product.html
│   ├── test_lcsc.py
│   ├── test_memorymarket.py
│   ├── test_mouser.py
│   ├── test_chipdip.py
│   └── test_sheets.py
├── docs/plans/
└── credentials/              # .gitignored, Google service account JSON
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/__init__.py`
- Create: `src/scrapers/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/` (empty dir)

**Step 1: Initialize git repo**

```bash
cd ~/memory-price-tracker
git init
```

**Step 2: Create pyproject.toml**

```toml
[project]
name = "memory-price-tracker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "selectolax>=0.3",
    "gspread>=6.0",
    "google-auth>=2.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "respx>=0.22",
]

[project.scripts]
mpt = "src.main:main"
```

**Step 3: Create .gitignore**

```
__pycache__/
*.pyc
.env
credentials/
.venv/
*.egg-info/
dist/
```

**Step 4: Create .env.example**

```
LCSC_API_KEY=
MOUSER_API_KEY=
GOOGLE_SHEET_ID=
GOOGLE_CREDENTIALS_PATH=credentials/service_account.json
```

**Step 5: Create empty __init__.py files**

```bash
touch src/__init__.py src/scrapers/__init__.py tests/__init__.py
mkdir -p tests/fixtures
```

**Step 6: Install dependencies**

```bash
cd ~/memory-price-tracker
uv venv --python 3.11
uv pip install -e ".[dev]"
```

**Step 7: Verify pytest runs**

```bash
cd ~/memory-price-tracker && uv run pytest --co -q
```
Expected: `no tests ran` (no errors)

**Step 8: Commit**

```bash
git add -A
git commit -m "chore: scaffold project with dependencies"
```

---

## Task 2: Data Model (PriceEntry)

**Files:**
- Create: `src/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
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
```

**Step 2: Run test to verify it fails**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_models.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.models'`

**Step 3: Write the implementation**

```python
# src/models.py
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PriceEntry:
    chip_type: str       # eMMC, UFS, DDR4, LPDDR4, NAND, etc.
    part_number: str     # e.g. KLMAG1JETD-B041
    description: str     # e.g. "Samsung 16GB eMMC"
    capacity: str        # e.g. "16GB", "4Gbit"
    source: str          # lcsc, memorymarket, mouser, chipdip
    price_usd: float
    price_rub: float
    moq: int
    url: str
    fetched_at: datetime

    def to_sheets_row(self) -> list:
        return [
            self.chip_type,
            self.part_number,
            self.description,
            self.capacity,
            self.source,
            self.price_usd,
            self.price_rub,
            self.moq,
            self.url,
            self.fetched_at.strftime("%Y-%m-%d %H:%M UTC"),
        ]

    def to_history_row(self) -> list:
        return [
            self.fetched_at.strftime("%Y-%m-%d"),
            self.chip_type,
            self.part_number,
            self.source,
            self.price_usd,
        ]
```

**Step 4: Run test to verify it passes**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_models.py -v
```
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat: add PriceEntry data model"
```

---

## Task 3: Currency Converter (CBR API)

**Files:**
- Create: `src/currency.py`
- Create: `tests/test_currency.py`

**Step 1: Write the failing test**

```python
# tests/test_currency.py
import httpx
import pytest
import respx
from src.currency import get_usd_rub_rate, convert_rub_to_usd


CBR_RESPONSE = {
    "Valute": {
        "USD": {
            "Value": 90.5,
            "Previous": 89.8
        }
    }
}


@respx.mock
@pytest.mark.asyncio
async def test_get_usd_rub_rate():
    respx.get("https://www.cbr-xml-daily.ru/daily_json.js").mock(
        return_value=httpx.Response(200, json=CBR_RESPONSE)
    )
    rate = await get_usd_rub_rate()
    assert rate == 90.5


@respx.mock
@pytest.mark.asyncio
async def test_get_usd_rub_rate_fallback_on_error():
    respx.get("https://www.cbr-xml-daily.ru/daily_json.js").mock(
        return_value=httpx.Response(500)
    )
    rate = await get_usd_rub_rate()
    assert rate == 90.0  # fallback


def test_convert_rub_to_usd():
    assert convert_rub_to_usd(900.0, rate=90.0) == 10.0
    assert convert_rub_to_usd(0.0, rate=90.0) == 0.0
```

**Step 2: Run test to verify it fails**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_currency.py -v
```
Expected: FAIL

**Step 3: Write the implementation**

```python
# src/currency.py
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
```

**Step 4: Run tests**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_currency.py -v
```
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/currency.py tests/test_currency.py
git commit -m "feat: add CBR currency converter"
```

---

## Task 4: Config & Watchlist

**Files:**
- Create: `src/config.py`

**Step 1: Write config**

```python
# src/config.py
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
```

**Step 2: Commit**

```bash
git add src/config.py
git commit -m "feat: add config with chip watchlist"
```

---

## Task 5: Base Scraper Interface

**Files:**
- Create: `src/scrapers/base.py`

**Step 1: Write base class**

```python
# src/scrapers/base.py
from abc import ABC, abstractmethod
from src.models import PriceEntry


class BaseScraper(ABC):
    name: str

    @abstractmethod
    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        """Fetch prices for all watchlist items. Returns list of PriceEntry."""
        ...
```

**Step 2: Commit**

```bash
git add src/scrapers/base.py
git commit -m "feat: add BaseScraper interface"
```

---

## Task 6: LCSC Scraper

LCSC API docs: `https://www.lcsc.com/docs/openapi/`. Search by part number, get price tiers.

**Files:**
- Create: `src/scrapers/lcsc.py`
- Create: `tests/test_lcsc.py`

**Step 1: Write the failing test**

```python
# tests/test_lcsc.py
import httpx
import pytest
import respx
from src.scrapers.lcsc import LCSCScraper

LCSC_SEARCH_RESPONSE = {
    "code": 200,
    "result": {
        "productSearchResultVO": {
            "productList": [
                {
                    "productCode": "C123456",
                    "productModel": "KLMAG1JETD-B041",
                    "productDescEn": "Samsung 16GB eMMC 5.1 FBGA153",
                    "productPriceList": [
                        {"ladder": 1, "usdPrice": 3.50},
                        {"ladder": 10, "usdPrice": 2.80},
                        {"ladder": 100, "usdPrice": 2.50},
                    ],
                    "minBuyNumber": 1,
                    "productUrl": "/product-detail/C123456.html",
                }
            ]
        }
    },
}


@respx.mock
@pytest.mark.asyncio
async def test_lcsc_fetch_prices():
    respx.get("https://wmsc.lcsc.com/ftps/wm/product/search").mock(
        return_value=httpx.Response(200, json=LCSC_SEARCH_RESPONSE)
    )
    scraper = LCSCScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert len(results) >= 1
    entry = results[0]
    assert entry.part_number == "KLMAG1JETD-B041"
    assert entry.price_usd == 2.80  # 10-unit tier
    assert entry.price_rub == 252.0
    assert entry.source == "lcsc"
    assert "lcsc.com" in entry.url


@respx.mock
@pytest.mark.asyncio
async def test_lcsc_handles_empty_response():
    respx.get("https://wmsc.lcsc.com/ftps/wm/product/search").mock(
        return_value=httpx.Response(200, json={"code": 200, "result": {"productSearchResultVO": {"productList": []}}})
    )
    scraper = LCSCScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert results == []
```

**Step 2: Run test to verify it fails**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_lcsc.py -v
```

**Step 3: Write the implementation**

```python
# src/scrapers/lcsc.py
import logging
from datetime import datetime, timezone

import httpx

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

LCSC_SEARCH_URL = "https://wmsc.lcsc.com/ftps/wm/product/search"


class LCSCScraper(BaseScraper):
    name = "lcsc"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                try:
                    entry = await self._fetch_one(
                        client, part_number, chip_type, description, capacity, rate_usd_rub
                    )
                    if entry:
                        entries.append(entry)
                except Exception:
                    logger.warning("LCSC: failed to fetch %s", part_number, exc_info=True)
        return entries

    async def _fetch_one(
        self, client: httpx.AsyncClient,
        part_number: str, chip_type: str, description: str, capacity: str,
        rate: float,
    ) -> PriceEntry | None:
        params = {"keyword": part_number}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = await client.get(LCSC_SEARCH_URL, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        products = (
            data.get("result", {})
            .get("productSearchResultVO", {})
            .get("productList", [])
        )
        if not products:
            return None

        product = products[0]
        price_list = product.get("productPriceList", [])
        if not price_list:
            return None

        # Pick the 10-unit tier if available, otherwise first tier
        price_usd = price_list[0]["usdPrice"]
        for tier in price_list:
            if tier["ladder"] <= 10:
                price_usd = tier["usdPrice"]

        product_url = product.get("productUrl", "")
        if product_url and not product_url.startswith("http"):
            product_url = f"https://www.lcsc.com{product_url}"

        return PriceEntry(
            chip_type=chip_type,
            part_number=product.get("productModel", part_number),
            description=product.get("productDescEn", description),
            capacity=capacity,
            source="lcsc",
            price_usd=round(price_usd, 2),
            price_rub=convert_usd_to_rub(price_usd, rate),
            moq=product.get("minBuyNumber", 1),
            url=product_url,
            fetched_at=datetime.now(timezone.utc),
        )
```

**Step 4: Run tests**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_lcsc.py -v
```
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/scrapers/lcsc.py tests/test_lcsc.py
git commit -m "feat: add LCSC API scraper"
```

---

## Task 7: Mouser Scraper

Mouser API: `https://api.mouser.com/api/v1/search/partnumber`. Free with registration.

**Files:**
- Create: `src/scrapers/mouser.py`
- Create: `tests/test_mouser.py`

**Step 1: Write the failing test**

```python
# tests/test_mouser.py
import httpx
import pytest
import respx
from src.scrapers.mouser import MouserScraper

MOUSER_RESPONSE = {
    "Errors": [],
    "SearchResults": {
        "Parts": [
            {
                "ManufacturerPartNumber": "MT41K256M16TW-107",
                "Description": "DRAM DDR3L SDRAM 4Gbit 256Mx16 1.35V",
                "PriceBreaks": [
                    {"Quantity": 1, "Price": "$4.50", "Currency": "USD"},
                    {"Quantity": 10, "Price": "$3.15", "Currency": "USD"},
                    {"Quantity": 100, "Price": "$2.80", "Currency": "USD"},
                ],
                "Min": "1",
                "MouserPartNumber": "556-MT41K256M16-107",
                "ProductDetailUrl": "https://www.mouser.com/ProductDetail/Micron/MT41K256M16TW-107",
            }
        ]
    },
}


@respx.mock
@pytest.mark.asyncio
async def test_mouser_fetch_prices():
    respx.post("https://api.mouser.com/api/v1/search/partnumber").mock(
        return_value=httpx.Response(200, json=MOUSER_RESPONSE)
    )
    scraper = MouserScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert len(results) >= 1
    entry = results[0]
    assert entry.part_number == "MT41K256M16TW-107"
    assert entry.price_usd == 3.15
    assert entry.source == "mouser"


@respx.mock
@pytest.mark.asyncio
async def test_mouser_handles_no_parts():
    respx.post("https://api.mouser.com/api/v1/search/partnumber").mock(
        return_value=httpx.Response(200, json={"Errors": [], "SearchResults": {"Parts": []}})
    )
    scraper = MouserScraper(api_key="test-key")
    results = await scraper.fetch_prices(rate_usd_rub=90.0)
    assert results == []
```

**Step 2: Run test to verify it fails**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_mouser.py -v
```

**Step 3: Write the implementation**

```python
# src/scrapers/mouser.py
import logging
import re
from datetime import datetime, timezone

import httpx

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"


class MouserScraper(BaseScraper):
    name = "mouser"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                try:
                    entry = await self._fetch_one(
                        client, part_number, chip_type, description, capacity, rate_usd_rub
                    )
                    if entry:
                        entries.append(entry)
                except Exception:
                    logger.warning("Mouser: failed to fetch %s", part_number, exc_info=True)
        return entries

    async def _fetch_one(
        self, client: httpx.AsyncClient,
        part_number: str, chip_type: str, description: str, capacity: str,
        rate: float,
    ) -> PriceEntry | None:
        body = {
            "SearchByPartRequest": {
                "mouserPartNumber": part_number,
                "partSearchOptions": "BeginsWith",
            }
        }
        params = {"apiKey": self.api_key}
        resp = await client.post(MOUSER_SEARCH_URL, json=body, params=params)
        resp.raise_for_status()
        data = resp.json()

        parts = data.get("SearchResults", {}).get("Parts", [])
        if not parts:
            return None

        part = parts[0]
        price_breaks = part.get("PriceBreaks", [])
        if not price_breaks:
            return None

        # Pick the 10-unit tier if available
        price_usd = self._parse_price(price_breaks[0]["Price"])
        for pb in price_breaks:
            if pb["Quantity"] <= 10:
                price_usd = self._parse_price(pb["Price"])

        return PriceEntry(
            chip_type=chip_type,
            part_number=part.get("ManufacturerPartNumber", part_number),
            description=part.get("Description", description),
            capacity=capacity,
            source="mouser",
            price_usd=round(price_usd, 2),
            price_rub=convert_usd_to_rub(price_usd, rate),
            moq=int(part.get("Min", 1)),
            url=part.get("ProductDetailUrl", ""),
            fetched_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _parse_price(price_str: str) -> float:
        cleaned = re.sub(r"[^\d.]", "", price_str)
        return float(cleaned) if cleaned else 0.0
```

**Step 4: Run tests**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_mouser.py -v
```
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/scrapers/mouser.py tests/test_mouser.py
git commit -m "feat: add Mouser API scraper"
```

---

## Task 8: MemoryMarket Scraper (HTML)

Scrapes spot price tables from memorymarket.com — NAND wafer, DDR4/DDR5, eMMC, UFS indexes.

**Files:**
- Create: `src/scrapers/memorymarket.py`
- Create: `tests/fixtures/memorymarket_spot.html`
- Create: `tests/test_memorymarket.py`

**Step 1: First, fetch a real page snapshot for test fixture**

```bash
cd ~/memory-price-tracker
curl -s -o tests/fixtures/memorymarket_spot.html "https://www.memorymarket.com/" --max-time 15
```

If the page isn't available or is too large, create a minimal HTML fixture manually:

```html
<!-- tests/fixtures/memorymarket_spot.html -->
<table class="price-table">
  <thead>
    <tr><th>Product</th><th>Spec</th><th>Price(USD)</th><th>Change</th></tr>
  </thead>
  <tbody>
    <tr><td>DDR4</td><td>8Gb eTT</td><td>1.82</td><td>-0.5%</td></tr>
    <tr><td>DDR5</td><td>16Gb</td><td>3.45</td><td>+0.3%</td></tr>
    <tr><td>NAND TLC</td><td>512Gb</td><td>2.45</td><td>+0.1%</td></tr>
    <tr><td>eMMC</td><td>64GB</td><td>2.10</td><td>-0.2%</td></tr>
  </tbody>
</table>
```

**Step 2: Write the failing test**

```python
# tests/test_memorymarket.py
from pathlib import Path
import pytest
from src.scrapers.memorymarket import MemoryMarketScraper, parse_spot_table


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memorymarket_spot.html"


def test_parse_spot_table():
    html = FIXTURE_PATH.read_text()
    rows = parse_spot_table(html)
    assert len(rows) > 0
    first = rows[0]
    assert "product" in first
    assert "price_usd" in first
    assert isinstance(first["price_usd"], float)
```

**Step 3: Write the implementation**

Note: The actual HTML structure of memorymarket.com will need to be inspected after fetching a real page. The scraper should extract spot price tables. This implementation uses selectolax and adapts to the real DOM structure found in the fixture.

```python
# src/scrapers/memorymarket.py
import logging
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

MEMORYMARKET_URL = "https://www.memorymarket.com/"


def parse_spot_table(html: str) -> list[dict]:
    """Parse spot price table from MemoryMarket HTML. Returns list of dicts."""
    tree = HTMLParser(html)
    rows = []
    for table in tree.css("table"):
        headers = [th.text(strip=True).lower() for th in table.css("thead th")]
        if not headers:
            continue
        for tr in table.css("tbody tr"):
            cells = [td.text(strip=True) for td in tr.css("td")]
            if len(cells) < 3:
                continue
            try:
                price_str = cells[2].replace(",", "").replace("$", "")
                price = float(price_str) if price_str else 0.0
            except ValueError:
                continue
            change_str = cells[3] if len(cells) > 3 else "0%"
            rows.append({
                "product": cells[0],
                "spec": cells[1] if len(cells) > 1 else "",
                "price_usd": price,
                "change": change_str,
            })
    return rows


class MemoryMarketScraper(BaseScraper):
    name = "memorymarket"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(MEMORYMARKET_URL)
                resp.raise_for_status()
                html = resp.text
        except Exception:
            logger.warning("MemoryMarket: failed to fetch page", exc_info=True)
            return []

        rows = parse_spot_table(html)
        now = datetime.now(timezone.utc)
        entries = []
        for row in rows:
            product = row["product"]
            entries.append(PriceEntry(
                chip_type=product,
                part_number=f"{product} {row['spec']}",
                description=f"{product} {row['spec']} spot",
                capacity=row["spec"],
                source="memorymarket",
                price_usd=row["price_usd"],
                price_rub=convert_usd_to_rub(row["price_usd"], rate_usd_rub),
                moq=0,
                url=MEMORYMARKET_URL,
                fetched_at=now,
            ))
        return entries
```

**Step 4: Run tests**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_memorymarket.py -v
```

**Important:** After fetching the real HTML fixture, you may need to adjust selectors in `parse_spot_table()` to match the actual DOM. Inspect the fixture HTML and adapt `table`, `thead`, `tbody`, `th`, `td` selectors accordingly.

**Step 5: Commit**

```bash
git add src/scrapers/memorymarket.py tests/test_memorymarket.py tests/fixtures/
git commit -m "feat: add MemoryMarket HTML scraper"
```

---

## Task 9: ChipDip Scraper (HTML)

Scrapes chipdip.ru product pages for memory IC prices in RUB.

**Files:**
- Create: `src/scrapers/chipdip.py`
- Create: `tests/fixtures/chipdip_product.html`
- Create: `tests/test_chipdip.py`

**Step 1: Fetch a test fixture**

```bash
curl -s -o tests/fixtures/chipdip_product.html \
  "https://www.chipdip.ru/catalog-show/ic-memory?x.page=1" --max-time 15
```

Or create minimal fixture:

```html
<!-- tests/fixtures/chipdip_product.html -->
<div class="catalog-list">
  <div class="catalog-item">
    <a class="link" href="/product/IS34ML04G084">IS34ML04G084-TLI</a>
    <span class="description">NAND Flash 4Gbit SLC TSOP48</span>
    <span class="price">3 530 &#8381;</span>
  </div>
  <div class="catalog-item">
    <a class="link" href="/product/W25Q128JVSIQ">W25Q128JVSIQ</a>
    <span class="description">NOR Flash 128Mbit SPI</span>
    <span class="price">145 &#8381;</span>
  </div>
</div>
```

**Step 2: Write the failing test**

```python
# tests/test_chipdip.py
from pathlib import Path
import pytest
from src.scrapers.chipdip import parse_chipdip_catalog


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chipdip_product.html"


def test_parse_chipdip_catalog():
    html = FIXTURE_PATH.read_text()
    items = parse_chipdip_catalog(html)
    assert len(items) > 0
    first = items[0]
    assert "part_number" in first
    assert "price_rub" in first
    assert isinstance(first["price_rub"], float)
    assert first["price_rub"] > 0
```

**Step 3: Write the implementation**

```python
# src/scrapers/chipdip.py
import logging
import re
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from src.currency import convert_rub_to_usd
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CHIPDIP_CATALOG_URL = "https://www.chipdip.ru/catalog-show/ic-memory"
CHIPDIP_SEARCH_URL = "https://www.chipdip.ru/search?searchtext="


def parse_chipdip_catalog(html: str) -> list[dict]:
    """Parse product list from ChipDip HTML."""
    tree = HTMLParser(html)
    items = []
    for item in tree.css(".catalog-item, .product-item, [class*='item']"):
        link = item.css_first("a.link, a[href*='/product/']")
        price_el = item.css_first(".price, [class*='price']")
        desc_el = item.css_first(".description, [class*='desc']")
        if not link or not price_el:
            continue
        part_number = link.text(strip=True)
        href = link.attributes.get("href", "")
        price_text = price_el.text(strip=True)
        price_rub = _parse_rub_price(price_text)
        if price_rub <= 0:
            continue
        items.append({
            "part_number": part_number,
            "description": desc_el.text(strip=True) if desc_el else "",
            "price_rub": price_rub,
            "url": f"https://www.chipdip.ru{href}" if href.startswith("/") else href,
        })
    return items


def _parse_rub_price(text: str) -> float:
    cleaned = re.sub(r"[^\d,.]", "", text).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class ChipDipScraper(BaseScraper):
    name = "chipdip"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    CHIPDIP_CATALOG_URL,
                    headers={"Accept-Language": "ru-RU,ru;q=0.9"},
                )
                resp.raise_for_status()
                html = resp.text
        except Exception:
            logger.warning("ChipDip: failed to fetch catalog", exc_info=True)
            return []

        items = parse_chipdip_catalog(html)
        now = datetime.now(timezone.utc)
        entries = []
        for item in items:
            entries.append(PriceEntry(
                chip_type="Memory IC",
                part_number=item["part_number"],
                description=item["description"],
                capacity="",
                source="chipdip",
                price_usd=convert_rub_to_usd(item["price_rub"], rate_usd_rub),
                price_rub=item["price_rub"],
                moq=1,
                url=item["url"],
                fetched_at=now,
            ))
        return entries
```

**Step 4: Run tests**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_chipdip.py -v
```

**Important:** Like MemoryMarket, you'll need to inspect the actual HTML from chipdip.ru and adjust selectors. The fixture-based test ensures parsing logic works on known HTML.

**Step 5: Commit**

```bash
git add src/scrapers/chipdip.py tests/test_chipdip.py tests/fixtures/chipdip_product.html
git commit -m "feat: add ChipDip HTML scraper"
```

---

## Task 10: Google Sheets Writer

**Files:**
- Create: `src/sheets.py`
- Create: `tests/test_sheets.py`

**Step 1: Write the failing test**

```python
# tests/test_sheets.py
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
    rows = args[0][0]  # First positional arg
    assert len(rows) == 3  # header + 2 entries
    assert rows[0][0] == "Type"  # header


@patch("src.sheets._get_spreadsheet")
def test_update_history_sheet(mock_get):
    mock_sheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_worksheet
    mock_get.return_value = mock_sheet

    entries = [_make_entry()]
    update_history_sheet(entries)

    assert mock_worksheet.append_rows.called
```

**Step 2: Run test to verify it fails**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_sheets.py -v
```

**Step 3: Write the implementation**

```python
# src/sheets.py
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
    # Append only (never clear history)
    rows = [e.to_history_row() for e in entries]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info("Appended %d rows to 'History'", len(rows))
```

**Step 4: Run tests**

```bash
cd ~/memory-price-tracker && uv run pytest tests/test_sheets.py -v
```
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/sheets.py tests/test_sheets.py
git commit -m "feat: add Google Sheets writer"
```

---

## Task 11: Main Orchestrator

**Files:**
- Create: `src/main.py`

**Step 1: Write the orchestrator**

```python
# src/main.py
import asyncio
import logging
import sys

from src.config import LCSC_API_KEY, MOUSER_API_KEY
from src.currency import get_usd_rub_rate
from src.models import PriceEntry
from src.scrapers.lcsc import LCSCScraper
from src.scrapers.mouser import MouserScraper
from src.scrapers.memorymarket import MemoryMarketScraper
from src.scrapers.chipdip import ChipDipScraper
from src.sheets import update_prices_sheet, update_history_sheet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    logger.info("Starting price fetch...")

    rate = await get_usd_rub_rate()
    logger.info("USD/RUB rate: %.2f", rate)

    scrapers = [
        LCSCScraper(api_key=LCSC_API_KEY),
        MouserScraper(api_key=MOUSER_API_KEY),
        MemoryMarketScraper(),
        ChipDipScraper(),
    ]

    all_entries: list[PriceEntry] = []
    results = await asyncio.gather(
        *[s.fetch_prices(rate) for s in scrapers],
        return_exceptions=True,
    )

    for scraper, result in zip(scrapers, results):
        if isinstance(result, Exception):
            logger.error("Scraper %s failed: %s", scraper.name, result)
        else:
            logger.info("Scraper %s returned %d entries", scraper.name, len(result))
            all_entries.extend(result)

    if not all_entries:
        logger.warning("No entries fetched from any source!")
        return

    logger.info("Total entries: %d. Updating Google Sheets...", len(all_entries))
    update_prices_sheet(all_entries)
    update_history_sheet(all_entries)
    logger.info("Done.")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

**Step 2: Test it runs (dry run without credentials)**

```bash
cd ~/memory-price-tracker && uv run python -c "from src.main import main; print('Import OK')"
```

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: add main orchestrator"
```

---

## Task 12: Cron Setup

**Step 1: Create a runner script**

```bash
# Create run.sh at project root
cat > ~/memory-price-tracker/run.sh << 'SCRIPT'
#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python -m src.main >> /tmp/memory-price-tracker.log 2>&1
SCRIPT
chmod +x ~/memory-price-tracker/run.sh
```

**Step 2: Add crontab entry (every 4 hours)**

```bash
(crontab -l 2>/dev/null; echo "0 */4 * * * $HOME/memory-price-tracker/run.sh") | crontab -
```

**Step 3: Verify crontab**

```bash
crontab -l | grep memory-price-tracker
```
Expected: `0 */4 * * * /Users/fedorovstas/memory-price-tracker/run.sh`

**Step 4: Commit**

```bash
cd ~/memory-price-tracker
git add run.sh
git commit -m "feat: add cron runner script"
```

---

## Task 13: Google Sheets Setup (Manual)

This task requires manual steps by the user:

1. Go to https://console.cloud.google.com/
2. Create a new project (e.g. "memory-price-tracker")
3. Enable "Google Sheets API"
4. Create a Service Account → download JSON key → save to `credentials/service_account.json`
5. Create a Google Sheet manually with 3 tabs: "Prices Now", "Spot Indexes", "History"
6. Share the sheet with the service account email (found in the JSON key)
7. Copy the sheet ID from the URL → add to `.env` as `GOOGLE_SHEET_ID`

**Step 1: Create .env from template**

```bash
cp .env.example .env
# Then edit .env with actual values
```

---

## Task 14: End-to-End Test

**Step 1: Run with real credentials**

```bash
cd ~/memory-price-tracker
source .venv/bin/activate
python -m src.main
```

**Step 2: Verify Google Sheet populated**

Open the Google Sheet URL and check:
- "Prices Now" tab has rows with prices, links, timestamps
- "History" tab has rows appended
- Links are clickable
- USD and RUB prices both populated

**Step 3: Run full test suite**

```bash
cd ~/memory-price-tracker && uv run pytest -v
```
Expected: All tests pass

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup, ready for production"
```

---

## Execution Order

| Task | Depends On | Description |
|------|-----------|-------------|
| 1 | - | Project scaffolding |
| 2 | 1 | PriceEntry model |
| 3 | 1 | Currency converter |
| 4 | 1 | Config + watchlist |
| 5 | 2 | BaseScraper interface |
| 6 | 3, 4, 5 | LCSC scraper |
| 7 | 3, 4, 5 | Mouser scraper |
| 8 | 3, 5 | MemoryMarket scraper |
| 9 | 3, 5 | ChipDip scraper |
| 10 | 2 | Sheets writer |
| 11 | 6, 7, 8, 9, 10 | Main orchestrator |
| 12 | 11 | Cron setup |
| 13 | - | Google Sheets setup (manual) |
| 14 | 11, 13 | End-to-end test |

**Parallelizable:** Tasks 6+7+8+9 can be done in parallel (all depend on 3+4+5, not each other). Tasks 10 can run in parallel with 6-9.
