# Memory Price Tracker MVP — Design

## Goal
Monitor DRAM and NAND Flash memory chip prices across China, Russia, and global markets for procurement teams manufacturing consumer electronics (TVs, tablets). Display in Google Sheets for easy access by non-technical buyers.

## Target Memory Types
- eMMC (4-16GB)
- UFS (32-64GB)
- DDR4 SDRAM (4-8Gbit)
- LPDDR4/4X (16Gbit)

## Architecture

```
[Cron every 4h]
    -> Python async scrapers (4 modules)
        -> LCSC REST API (China, IC prices)
        -> MemoryMarket HTML scrape (Global spot prices)
        -> Mouser REST API (Global distributor prices)
        -> ChipDip HTML scrape (Russia, RUB prices)
    -> Normalize (currency via CBR API, units)
    -> Google Sheets API -> shared spreadsheet
```

## Google Sheet Structure

### Sheet 1: "Prices Now" (main view for buyers)
Columns: Type | Chip | Volume | Source | Price USD | Price RUB | MOQ | Link | Updated

### Sheet 2: "Spot Indexes" (market overview)
Columns: Type | Spec | Price USD | Day Change | Week Change | Source | Updated

### Sheet 3: "History" (for charts)
Columns: Date | Type | Spec | Source | Price USD
Standard Google Sheets charts on top.

## Stack
- Python 3.12
- httpx (async HTTP)
- selectolax (HTML parsing)
- gspread + google-auth (Sheets API)
- System cron (every 4 hours)
- cbr-xml-daily.ru (RUB/USD rate)

## Initial Chip Watchlist
- eMMC: KLMAG1JETD (Samsung 16GB), THGBMHG6C1LBAIL (Kioxia 8GB), MTFC4GACAJCN (Micron 4GB)
- UFS: KLUCG4J1ED (Samsung 64GB), THGJFGT0T25BAIL (Kioxia 32GB)
- DDR4: MT41K256M16 (Micron 4Gbit), K4A8G165WC (Samsung 8Gbit), H5AN8G6NDJR (SK Hynix 8Gbit)
- LPDDR4/4X: MT53E512M32D2DS (Micron 16Gbit), K4F6E3S4HM (Samsung 16Gbit)

## Data Sources

| Source | Region | Method | Free | Update Freq |
|--------|--------|--------|------|-------------|
| LCSC (lcsc.com) | China | REST API (1000 req/day) | Yes | Real-time |
| MemoryMarket (memorymarket.com) | Global | HTML scrape | Yes | Daily |
| Mouser (mouser.com) | Global | REST API | Yes | Real-time |
| ChipDip (chipdip.ru) | Russia | HTML scrape | Yes | Daily |

## Out of Scope (MVP)
- Telegram alerts
- Auth / multi-user
- Auto-ordering
- Price forecasting
- DigiKey / Arrow (can add later)

## Update Frequency
Every 4-6 hours via cron.

## Currency
All prices normalized to USD + RUB (via CBR daily rate).
