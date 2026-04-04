import random
"""
Memory Price Tracker — Full Catalog Crawler (Scrapling)
Crawls ALL memory chips from ALL available sources.
Writes results to PostgreSQL.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from html import unescape

import asyncpg
import httpx
from scrapling import Fetcher
from scrapling.fetchers import AsyncStealthySession

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("crawl_all")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://mpt:changeme@127.0.0.1:5432/memoryprices")

# ─── Brand extraction ───────────────────────────────────────────────
BRAND_MAP = {
    'Samsung': ['K4', 'K9', 'KLM', 'KLU', 'KLD', 'K4F', 'K4A', 'K4R', 'K4U', 'K4B'],
    'Micron': ['MT', 'MTFC', 'MTE'],
    'SK Hynix': ['H5', 'H9', 'HY', 'H54', 'H58'],
    'Kioxia': ['TH', 'TC58', 'THGB', 'THGJ'],
    'Winbond': ['W25Q', 'W29N', 'W25N', 'W9'],
    'GigaDevice': ['GD25', 'GD5F'],
    'Macronix': ['MX25', 'MX29', 'MX66'],
    'ISSI': ['IS61', 'IS62', 'IS66', 'IS25'],
    'Nanya': ['NT5'],
    'Alliance': ['AS4C', 'AS7C'],
    'Cypress': ['S25F', 'S29', 'CY'],
    'Spansion': ['S25F', 'S29GL'],
    'Intel': ['JS29', 'PC29'],
    'Toshiba': ['TC58', 'TH58'],
    'SanDisk': ['SDIN', 'SDIO'],
}

def extract_brand(pn: str, desc: str = '') -> str:
    up = pn.upper()
    for brand, prefixes in BRAND_MAP.items():
        for p in prefixes:
            if up.startswith(p):
                return brand
    for brand in BRAND_MAP:
        if brand.upper() in desc.upper():
            return brand
    return 'Other'

CHIP_TYPES = {
    'eMMC': ['emmc', 'embedded mmc', 'embedded multi'],
    'UFS': ['ufs', 'universal flash'],
    'DDR4': ['ddr4'],
    'DDR5': ['ddr5'],
    'DDR3': ['ddr3'],
    'LPDDR4': ['lpddr4'],
    'LPDDR4X': ['lpddr4x'],
    'LPDDR5': ['lpddr5'],
    'NAND': ['nand flash', 'nand', 'slc nand', 'mlc nand', 'tlc', 'qlc'],
    'NOR Flash': ['nor flash', 'serial flash', 'spi flash'],
    'SRAM': ['sram', 'static ram'],
    'SDRAM': ['sdram'],
    'DRAM': ['dram'],
}

def classify_type(pn: str, desc: str) -> str:
    text = f"{pn} {desc}".lower()
    for typ, keywords in CHIP_TYPES.items():
        for kw in keywords:
            if kw in text:
                return typ
    return 'Memory IC'

# ─── Utility ────────────────────────────────────────────────────────
def parse_price(text: str) -> float:
    cleaned = re.sub(r'[^\d.,]', '', str(text)).replace(',', '.')
    try:
        return round(float(cleaned), 4)
    except (ValueError, TypeError):
        return 0.0

async def get_usd_rub_rate() -> float:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://www.cbr-xml-daily.ru/daily_json.js")
            return float(r.json()["Valute"]["USD"]["Value"])
    except Exception:
        return 85.0

# ─── Crawlers ───────────────────────────────────────────────────────

CATEGORIES = [
    "eMMC", "UFS", "DDR4 SDRAM", "DDR5 SDRAM", "DDR3 SDRAM",
    "LPDDR4", "LPDDR5", "NAND Flash", "NOR Flash", "SRAM",
    "Flash Memory", "DRAM", "SDRAM", "Memory IC",
]

# Expanded keyword list for JLCPCB: generic memory types + manufacturer part prefixes.
# Each keyword targets a distinct product family and returns results the generic
# type queries miss (because the search index matches on part number prefix).
# 68 keywords × 100 per page = up to 6 800 JLCPCB entries per run.
# LCSC now uses a dedicated category-browse approach (wmCatalogId=1288) instead.
EXPANDED_KEYWORDS = [
    # Generic types (same as CATEGORIES, kept for baseline coverage)
    "eMMC", "UFS", "DDR4", "DDR5", "DDR3", "LPDDR4", "LPDDR5",
    "NAND Flash", "NOR Flash", "SRAM", "Flash Memory", "DRAM", "SDRAM",
    # Additional memory types not in CATEGORIES
    "EEPROM", "FRAM", "MRAM", "PSRAM",
    # Samsung eMMC / UFS
    "KLMAG", "KLMBG", "KLUCG", "KLUDG",
    # Kioxia (formerly Toshiba)
    "THGBM", "THGJF", "TC58",
    # Micron
    "MTFC", "MT41K", "MT40A", "MT53E", "MT60B", "MT29F",
    # SK Hynix
    "H5AN", "H5CG", "H9J",
    # Winbond NOR / NAND
    "W25Q128", "W25Q256", "W25Q64", "W25N",
    # GigaDevice
    "GD25Q", "GD5F",
    # Macronix
    "MX25L", "MX25U", "MX66",
    # ISSI
    "IS25", "IS62", "IS66",
    # Samsung DRAM
    "K4A8G", "K4AAG", "K4RAH", "K4F6E", "K4UBE",
    # Samsung NAND
    "K9GBG", "K9F2G",
    # Nanya
    "NT5CC", "NT5AD",
    # Alliance
    "AS4C", "AS7C",
    # Cypress / Spansion NOR
    "S25FL", "S29GL",
    # Microchip SST
    "SST26", "SST39",
    # Adesto / Dialog
    "AT25", "AT45",
    # Cypress FRAM
    "FM25", "FM24",
    # Micron NOR (legacy N25Q brand, now MT25Q)
    "N25Q", "MT25Q",
    # Cypress SRAM
    "CY62", "CY7C",
]

# FindChips uses both the generic category names AND manufacturer prefixes so that
# the unlimited pagination returns the widest possible unique result set.
FINDCHIPS_KEYWORDS = CATEGORIES + [kw for kw in EXPANDED_KEYWORDS if kw not in CATEGORIES]

async def crawl_findchips(rate: float) -> list[dict]:
    """FindChips — HTML scraping with pagination."""
    log.info("FindChips: starting")
    entries = []
    seen_pns = set()  # Track part numbers to dedup across pages/keywords
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html",
    }
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        for cat in FINDCHIPS_KEYWORDS:
            prev_total = len(entries)
            for page_num in range(1, 30):  # up to 30 pages per keyword
                try:
                    url = f"https://www.findchips.com/search/{cat}"
                    params = {"page": page_num} if page_num > 1 else {}
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        break
                    from scrapling.parser import Selector
                    page = Selector(resp.text)
                    rows = page.css('tr[data-distributor_name][data-price]')
                    if not rows:
                        break
                    for row in rows:
                        dist = row.attrib.get('data-distributor_name', '')
                        pn = row.attrib.get('data-mfrpartnumber', '')
                        stock_s = row.attrib.get('data-instock', '0')
                        price_raw = unescape(row.attrib.get('data-price', '[]'))
                        if not pn or not dist:
                            continue
                        try:
                            tiers = json.loads(price_raw)
                        except json.JSONDecodeError:
                            continue
                        best = 0.0
                        for t in tiers:
                            if len(t) >= 3 and t[1] == 'USD':
                                p = float(str(t[2]).replace(",", ""))
                                if best == 0 or (int(t[0]) <= 10 and p > 0):
                                    best = p
                        if best <= 0:
                            continue
                        try:
                            stock = int(str(stock_s).replace(',', ''))
                        except ValueError:
                            stock = 0
                        dedup_key = (pn, dist)
                        if dedup_key in seen_pns:
                            continue
                        seen_pns.add(dedup_key)
                        entries.append({
                            'chip_type': classify_type(pn, cat),
                            'part_number': pn,
                            'description': f"{cat} via {dist}",
                            'brand': extract_brand(pn, ''),
                            'capacity': '',
                            'source': 'findchips',
                            'distributor': dist,
                            'price_usd': round(best, 4),
                            'price_rub': round(best * rate, 2),
                            'price_cny': None,
                            'moq': 1,
                            'stock': stock,
                            'url': f"https://www.findchips.com/search/{pn}",
                        })
                    new_count = len(entries) - prev_total
                    log.info(f"FindChips: {cat} page {page_num}, {len(rows)} rows, {new_count} new, total {len(entries)}")
                    if new_count == 0:
                        log.info(f"FindChips: {cat} page {page_num} — no new items, stopping keyword")
                        break
                    prev_total = len(entries)
                    await asyncio.sleep(1.5)
                except Exception as e:
                    log.warning(f"FindChips: {cat} page {page_num} error: {e}")
                    break
    log.info(f"FindChips: done, {len(entries)} entries")
    return entries

async def crawl_szlcsc(rate: float) -> list[dict]:
    """SZLCSC (Chinese LCSC) — SSR HTML with __NEXT_DATA__ (requires Googlebot UA for SSR mode)."""
    log.info("SZLCSC: starting")
    entries = []
    # Googlebot UA triggers SSR mode: __NEXT_DATA__ with full product list (30 items/page).
    # Regular browser UA causes CSR-only response with just 3 JSON-LD items regardless of page.
    headers = {
        "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    # Try to get live CNY/USD rate, fall back to hardcoded
    CNY_TO_USD = 0.14
    try:
        async with httpx.AsyncClient(timeout=10) as fx_client:
            r = await fx_client.get("https://open.er-api.com/v6/latest/CNY")
            if r.status_code == 200:
                usd_rate = r.json().get("rates", {}).get("USD")
                if usd_rate and 0.10 < usd_rate < 0.20:
                    CNY_TO_USD = round(usd_rate, 4)
                    log.info(f"SZLCSC: live CNY/USD rate = {CNY_TO_USD}")
    except Exception:
        log.info(f"SZLCSC: using fallback CNY/USD = {CNY_TO_USD}")
    # SZLCSC-specific keywords (short names work better than full names)
    szlcsc_keywords = [
        "eMMC", "UFS", "DDR4", "DDR5", "DDR3", "LPDDR4", "LPDDR5",
        "NAND", "NOR", "SRAM", "DRAM", "SDRAM", "Flash", "SSD",
    ]
    for cat in szlcsc_keywords:
        # Fresh client per keyword — avoids session-level rate limiting (302 → login)
        async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=False) as client:
            for pg in range(1, 11):  # up to 10 pages (300 items) per keyword — SZLCSC IP limit
                try:
                    url = f"https://so.szlcsc.com/global.html?k={cat}&pageIndex={pg}&pageSize=30"
                    resp = await client.get(url)
                    if resp.status_code in (301, 302, 303):
                        log.warning(f"SZLCSC: {cat} page {pg} — redirect (rate-limit), stopping keyword")
                        break
                    if resp.status_code != 200:
                        break
                    # Extract __NEXT_DATA__ via regex (faster than HTML parser)
                    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
                    if not m:
                        log.warning(f"SZLCSC: {cat} page {pg} — no __NEXT_DATA__ (CSR mode?), stopping")
                        break
                    data = json.loads(m.group(1))
                    # Path: props.pageProps.soData.searchResult.productRecordList
                    try:
                        products = data['props']['pageProps']['soData']['searchResult']['productRecordList']
                    except (KeyError, TypeError):
                        products = []
                    if not products:
                        break
                    for prod in products:
                        if not isinstance(prod, dict):
                            continue
                        vo = prod.get('productVO', prod)
                        pn = vo.get('productModel', vo.get('productName', ''))
                        # productType is the category in English (e.g. "eMMC")
                        desc = vo.get('productType', vo.get('remark', ''))
                        if not desc:
                            desc = ''
                        price_list = vo.get('productPriceList', [])
                        stock_qty = int(vo.get('stockNumber', vo.get('validStockNumber', 0)) or 0)
                        best_cny = 0.0
                        best_tier_qty = 0
                        fallback_cny = 0.0
                        for tier in price_list:
                            if isinstance(tier, dict):
                                p = float(tier.get('productPrice', tier.get('thePrice', 0)) or 0)
                                q = int(tier.get('startPurchasedNumber', tier.get('spNumber', 0)) or 0)
                                if p <= 0:
                                    continue
                                if fallback_cny == 0 or q <= 1:
                                    fallback_cny = p
                                # Best price at highest tier where tier_qty <= stock
                                if stock_qty > 0 and q <= stock_qty and q >= best_tier_qty:
                                    best_cny = p
                                    best_tier_qty = q
                                elif stock_qty <= 0 and (q <= 10 or best_cny == 0):
                                    best_cny = p
                        if best_cny <= 0:
                            best_cny = fallback_cny
                        if best_cny <= 0 or not pn:
                            continue
                        price_usd = round(best_cny * CNY_TO_USD, 4)
                        brand_raw = vo.get('productGradePlateName', '')
                        # Strip Chinese brand name suffix in parentheses
                        brand_clean = re.sub(r'\(.*?\)', '', brand_raw).strip()
                        entries.append({
                            'chip_type': classify_type(pn, desc),
                            'part_number': pn,
                            'description': desc[:200],
                            'brand': extract_brand(pn, brand_clean) if extract_brand(pn, '') == 'Other' else extract_brand(pn, ''),
                            'capacity': '',
                            'source': 'szlcsc',
                            'distributor': 'SZLCSC',
                            'price_usd': price_usd,
                            'price_rub': round(price_usd * rate, 2),
                            'price_cny': best_cny,
                            'moq': int(vo.get('minBuyNumber', 1) or 1),
                            'stock': int(vo.get('stockNumber', vo.get('validStockNumber', 0)) or 0),
                            'url': f"https://item.szlcsc.com/{vo.get('productId', '')}.html",
                        })
                    log.info(f"SZLCSC: {cat} page {pg}, {len(products)} products, total {len(entries)}")
                    await asyncio.sleep(30 + random.uniform(5, 15))  # SZLCSC: longer delays to avoid 302
                except Exception as e:
                    log.warning(f"SZLCSC: {cat} page {pg} error: {e}")
                    break
        await asyncio.sleep(90 + random.uniform(10, 30))  # SZLCSC: long cooldown between keywords
    log.info(f"SZLCSC: done, {len(entries)} entries")
    return entries

JLCPCB_API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
JLCPCB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://jlcpcb.com/parts/componentSearch",
    "Origin": "https://jlcpcb.com",
}

def _extract_best_price(prices: list, stock: int = 0) -> float:
    """Return best price at highest tier where tier_qty <= stock.
    If stock unknown (0), fall back to qty-1 price."""
    best = 0.0
    best_qty = 0
    fallback = 0.0
    for tier in prices:
        p = float(tier.get('productPrice', 0) or 0)
        q = int(tier.get('startNumber', 0) or 0)
        if p <= 0:
            continue
        if fallback == 0 or q <= 1:
            fallback = p
        if stock > 0 and q <= stock and q >= best_qty:
            best = p
            best_qty = q
        elif stock <= 0 and (q <= 10 or best == 0):
            best = p
    return best if best > 0 else fallback

def _jlcpcb_item_to_entry(item: dict, rate: float, source: str, distributor: str) -> dict | None:
    """Convert a raw JLCPCB list item to a normalised price entry. Returns None if unusable."""
    pn = item.get('componentModelEn', '')
    if not pn:
        return None
    desc = item.get('describe', '') or ''
    stock = int(item.get('stockCount', item.get('componentStock', 0)) or 0)
    best = _extract_best_price(item.get('componentPrices', []), stock)
    if best <= 0:
        return None
    return {
        'chip_type': classify_type(pn, desc),
        'part_number': pn,
        'description': desc[:200],
        'brand': extract_brand(pn, desc),
        'capacity': '',
        'source': source,
        'distributor': distributor,
        'price_usd': round(best, 4),
        'price_rub': round(best * rate, 2),
        'price_cny': None,
        'moq': int(item.get('minPurchaseNum', item.get('leastNumber', 1)) or 1),
        'stock': int(item.get('stockCount', 0) or 0),
        'url': item.get('lcscGoodsUrl', ''),
    }

async def _jlcpcb_fetch_pages(
    categories: list[str],
    rate: float,
    source: str,
    distributor: str,
    page_delay: float = 3.0,
    category_delay: float = 15.0,
) -> list[dict]:
    """Generic paginator over the JLCPCB component search API.

    Rate-limit strategy: JLCPCB enforces a per-IP burst limit that kicks in
    after ~1 request per connection. Opening a fresh connection per category
    and waiting `category_delay` seconds between categories avoids the 403
    wall that otherwise kills every category after the first.
    """
    entries = []
    for cat_idx, cat in enumerate(categories):
        if cat_idx > 0:
            await asyncio.sleep(category_delay)
        # Use cookies jar to maintain XSRF-TOKEN across pages
        async with httpx.AsyncClient(timeout=30, headers=JLCPCB_HEADERS, cookies=httpx.Cookies()) as client:
            for pg in range(1, 50):
                try:
                    body = {"keyword": cat, "currentPage": pg, "pageSize": 100}
                    # After first request, add XSRF-TOKEN from cookie to headers
                    xsrf = client.cookies.get("XSRF-TOKEN")
                    if xsrf:
                        client.headers["X-XSRF-TOKEN"] = xsrf
                    resp = await client.post(JLCPCB_API, json=body)
                    if resp.status_code == 403:
                        log.warning(f"{source}: {cat} page {pg} — 403 (CSRF?), skipping category")
                        break
                    if resp.status_code != 200:
                        log.warning(f"{source}: {cat} page {pg} — HTTP {resp.status_code}, stopping")
                        break
                    data = resp.json()
                    items = data.get('data', {}).get('componentPageInfo', {}).get('list', [])
                    if not items:
                        break
                    before = len(entries)
                    for item in items:
                        entry = _jlcpcb_item_to_entry(item, rate, source, distributor)
                        if entry:
                            entries.append(entry)
                    log.info(f"{source}: {cat} page {pg}, {len(items)} items (+{len(entries)-before}), total {len(entries)}")
                    await asyncio.sleep(page_delay)
                except Exception as e:
                    log.warning(f"{source}: {cat} page {pg} error: {e}")
                    break
    return entries

async def crawl_jlcpcb(rate: float) -> list[dict]:
    """JLCPCB SMT component library — JSON API with anti-rate-limit delay."""
    log.info("JLCPCB: starting")
    entries = await _jlcpcb_fetch_pages(
        categories=EXPANDED_KEYWORDS,
        rate=rate,
        source='jlcpcb',
        distributor='JLCPCB/LCSC',
        page_delay=3.0,
        category_delay=3.0,
    )
    log.info(f"JLCPCB: done, {len(entries)} entries")
    return entries


# ─── LCSC International ──────────────────────────────────────────────
#
# LCSC uses its own API at wmsc.lcsc.com, completely separate from JLCPCB.
# Strategy:
#   Phase 1 — Full category browse: wmCatalogId=1288 ("Memory ICs") yields
#             ~47 000 products across 1 667 pages.  We cap at 200 pages
#             (5 600 items) to finish within the nightly window, sorted by
#             stock descending so in-stock parts always come first.
#   Phase 2 — Keyword supplement: run EXPANDED_KEYWORDS through the same
#             endpoint to catch long-tail parts that the category browse
#             may order too late (e.g. rare prefixes), but only 5 pages
#             per keyword so we stay fast.

LCSC_API = "https://wmsc.lcsc.com/ftps/wm/search/v2/global"
LCSC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://www.lcsc.com/",
    "Origin": "https://www.lcsc.com",
    "Accept": "application/json",
}
# wmCatalogId=1288 = "Memory (ICs)" under Integrated Circuits → Memory
LCSC_MEMORY_CATALOG_ID = 1288
# Maximum pages to fetch in the category-browse phase (28 items/page → 5 600 items)
LCSC_CATEGORY_MAX_PAGES = 200


def _lcsc_item_to_entry(prod: dict, rate: float) -> dict | None:
    """Convert a LCSC productSearchResultVO productList item to a price entry."""
    pn = prod.get("productModel", "")
    if not pn:
        return None
    price_list = prod.get("productPriceList") or []
    stock_qty = int(prod.get("stockNumber") or 0)
    best = 0.0
    best_ladder = 0
    fallback = 0.0
    for tier in price_list:
        p = float(tier.get("usdPrice") or tier.get("currencyPrice") or 0)
        ladder = int(tier.get("ladder") or 0)
        if p <= 0:
            continue
        if fallback == 0 or ladder <= 1:
            fallback = p
        # Best price at highest tier where tier_qty <= stock
        if stock_qty > 0 and ladder <= stock_qty and ladder >= best_ladder:
            best = p
            best_ladder = ladder
        elif stock_qty <= 0 and (ladder <= 10 or best == 0):
            best = p
    if best <= 0:
        best = fallback
    if best <= 0:
        return None
    product_code = prod.get("productCode", "")
    url = prod.get("url") or (
        f"https://www.lcsc.com/product-detail/{product_code}.html" if product_code else ""
    )
    desc = prod.get("productIntroEn") or prod.get("productDescEn") or ""
    catalog = prod.get("catalogName") or prod.get("parentCatalogName") or ""
    brand = prod.get("brandNameEn") or ""
    return {
        "chip_type": classify_type(pn, f"{desc} {catalog}"),
        "part_number": pn,
        "description": (f"{catalog}: {desc}"[:200]) if desc else catalog[:200],
        "brand": extract_brand(pn, brand) if extract_brand(pn, "") == "Other" else extract_brand(pn, ""),
        "capacity": "",
        "source": "lcsc",
        "distributor": "LCSC",
        "price_usd": round(best, 4),
        "price_rub": round(best * rate, 2),
        "price_cny": None,
        "moq": int(prod.get("minBuyNumber") or 1),
        "stock": int(prod.get("stockNumber") or 0),
        "url": url,
    }


async def crawl_lcsc(rate: float) -> list[dict]:
    """LCSC International (lcsc.com) — real LCSC search API.

    Phase 1: Category browse — fetches up to LCSC_CATEGORY_MAX_PAGES pages of
    the Memory IC category (wmCatalogId=1288), sorted by stock descending so
    in-stock parts appear first.  ~47 000 total products available; we take
    the top 5 600 (capped to keep nightly runtime reasonable).

    Phase 2: Keyword supplement — runs EXPANDED_KEYWORDS through the search
    API (5 pages each) to catch long-tail parts not covered by the category
    sort order.

    Both phases use wmsc.lcsc.com, which is the real LCSC product database,
    NOT the JLCPCB API.
    """
    log.info("LCSC: starting")
    entries: list[dict] = []
    seen_pns: set[str] = set()

    async with httpx.AsyncClient(timeout=30, headers=LCSC_HEADERS) as client:

        # ── Phase 1: Full Memory IC category browse ─────────────────────────
        log.info(f"LCSC: phase 1 — category browse (wmCatalogId={LCSC_MEMORY_CATALOG_ID})")
        for pg in range(1, LCSC_CATEGORY_MAX_PAGES + 1):
            try:
                body = {
                    "keyword": "memory",          # non-empty keyword required
                    "wmCatalogId": LCSC_MEMORY_CATALOG_ID,
                    "currentPage": pg,
                    "pageSize": 28,               # API default page size
                }
                resp = await client.post(LCSC_API, json=body)
                if resp.status_code != 200:
                    log.warning(f"LCSC cat page {pg}: HTTP {resp.status_code}, stopping phase 1")
                    break
                data = resp.json()
                if not data.get("ok"):
                    log.warning(f"LCSC cat page {pg}: API error code={data.get('code')}, stopping phase 1")
                    break
                psrvo = (data.get("result") or {}).get("productSearchResultVO") or {}
                products = psrvo.get("productList") or []
                if not products:
                    log.info(f"LCSC cat page {pg}: no products, done with phase 1")
                    break
                before = len(entries)
                for prod in products:
                    entry = _lcsc_item_to_entry(prod, rate)
                    if entry and entry["part_number"] not in seen_pns:
                        seen_pns.add(entry["part_number"])
                        entries.append(entry)
                total_pages = data["result"].get("productTotalPage", 0)
                log.info(
                    f"LCSC cat page {pg}/{min(total_pages, LCSC_CATEGORY_MAX_PAGES)}: "
                    f"{len(products)} items (+{len(entries)-before} new), total {len(entries)}"
                )
                if pg >= total_pages:
                    log.info("LCSC: reached last page of category, done with phase 1")
                    break
                await asyncio.sleep(2.0)
            except Exception as e:
                log.warning(f"LCSC cat page {pg} error: {e}")
                break

        log.info(f"LCSC: phase 1 done — {len(entries)} entries from category browse")

        # ── Phase 2: Keyword supplement ─────────────────────────────────────
        log.info("LCSC: phase 2 — keyword supplement")
        for kw_idx, kw in enumerate(EXPANDED_KEYWORDS):
            if kw_idx > 0:
                await asyncio.sleep(5.0)
            for pg in range(1, 6):  # 5 pages × 100 items = 500 per keyword
                try:
                    body = {"keyword": kw, "currentPage": pg, "pageSize": 100}
                    resp = await client.post(LCSC_API, json=body)
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data.get("ok"):
                        break
                    psrvo = (data.get("result") or {}).get("productSearchResultVO") or {}
                    products = psrvo.get("productList") or []
                    if not products:
                        break
                    before = len(entries)
                    for prod in products:
                        entry = _lcsc_item_to_entry(prod, rate)
                        if entry and entry["part_number"] not in seen_pns:
                            seen_pns.add(entry["part_number"])
                            entries.append(entry)
                    log.info(
                        f"LCSC kw={kw!r} page {pg}: {len(products)} items "
                        f"(+{len(entries)-before} new), total {len(entries)}"
                    )
                    await asyncio.sleep(1.5)
                except Exception as e:
                    log.warning(f"LCSC kw={kw!r} page {pg} error: {e}")
                    break

    log.info(f"LCSC: done, {len(entries)} entries total")
    return entries

async def crawl_memorymarket(rate: float) -> list[dict]:
    """MemoryMarket — spot price index + detail pages.

    Main page has 16 tables with columns: [Product Item, Latest, Previous, Change, Currency, Trend].
    Price is in column index 1 (Latest), NOT index 2 (Previous).
    Tables with 'Add Cost Item' header are component-cost tables — skip them.

    Detail page IDs: valid range is ~100160–100257 (not 1–500).
    IDs outside this range return HTTP 500.
    """
    log.info("MemoryMarket: starting")
    entries = []
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        # ── Main page: 16 price tables ──────────────────────────────────────
        try:
            resp = await client.get("https://www.memorymarket.com/")
            if resp.status_code == 200:
                # Use regex-based parsing (scrapling not available on all envs)
                html = resp.text
                table_blocks = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
                before_count = len(entries)
                for table_html in table_blocks:
                    # Determine header row
                    header_cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>',
                                              re.search(r'<thead[^>]*>(.*?)</thead>', table_html, re.DOTALL).group(1)
                                              if re.search(r'<thead', table_html, re.DOTALL) else '', re.DOTALL)
                    headers_text = [re.sub(r'<[^>]+>', '', h).strip().lower() for h in header_cells]
                    # Only process "product item / latest / ..." tables
                    if not headers_text or 'product item' not in headers_text[0]:
                        continue
                    # Price column: find index of "latest"
                    price_col = headers_text.index('latest') if 'latest' in headers_text else 1
                    # Parse tbody rows
                    tbody_m = re.search(r'<tbody[^>]*>(.*?)</tbody>', table_html, re.DOTALL)
                    if not tbody_m:
                        continue
                    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody_m.group(1), re.DOTALL)
                    for row in rows:
                        cells_raw = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
                        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells_raw]
                        if len(cells) <= price_col:
                            continue
                        # Extract product name (first cell, strip inner tags)
                        product = cells[0]
                        if not product:
                            continue
                        try:
                            price = float(cells[price_col].replace(',', '').replace('$', ''))
                        except (ValueError, IndexError):
                            continue
                        if price <= 0:
                            continue
                        entries.append({
                            'chip_type': classify_type(product, ''),
                            'part_number': product,
                            'description': f"{product} spot index",
                            'brand': extract_brand(product, ''),
                            'capacity': '',
                            'source': 'memorymarket',
                            'distributor': 'Spot Index',
                            'price_usd': round(price, 4),
                            'price_rub': round(price * rate, 2),
                            'price_cny': None,
                            'moq': 0,
                            'stock': None,
                            'url': 'https://www.memorymarket.com/',
                        })
                log.info(f"MemoryMarket: main page, {len(entries) - before_count} entries from tables")
        except Exception as e:
            log.warning(f"MemoryMarket: main page error: {e}")

        # ── Detail pages: valid IDs are 100160–100257 (only ~12 exist) ───────
        # IDs outside this range return HTTP 500. Range 1–500 is completely wrong.
        # We scan 100160–100300 to cover all known IDs and handle future additions.
        for pid in range(100160, 100301):
            try:
                resp = await client.get(f"https://www.memorymarket.com/price/in/{pid}")
                if resp.status_code != 200:
                    continue
                html = resp.text
                # Extract page title
                title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
                if not title_m:
                    continue
                title_text = re.sub(r'\s*\|.*', '', title_m.group(1)).strip()
                # Extract latest price from the first price table (second table has historical data)
                # Look for the price table rows: date | low | open | close
                # The latest price is in the first data row of table 2 (the history table)
                price = 0.0
                # Detail page price is in span.n-price inside div.new-price: "$28.00"
                new_price_m = re.search(r'class="n-price[^"]*">\s*\$([\d.]+)', html)
                if new_price_m:
                    price = parse_price(new_price_m.group(1))
                else:
                    # fallback: first price value from history table (date | low | open | close)
                    table_m = re.search(r'<td[^>]*>([\d]{4}-[\d]{2}-[\d]{2})[^<]*</td>.*?<td[^>]*>([\d.]+)</td>', html, re.DOTALL)
                    if table_m:
                        price = parse_price(table_m.group(2))
                if price > 0:
                    entries.append({
                        'chip_type': classify_type(title_text, ''),
                        'part_number': title_text[:100],
                        'description': f"{title_text} historical spot price",
                        'brand': extract_brand(title_text, ''),
                        'capacity': '',
                        'source': 'memorymarket',
                        'distributor': 'MemoryMarket',
                        'price_usd': round(price, 4),
                        'price_rub': round(price * rate, 2),
                        'price_cny': None,
                        'moq': 0,
                        'stock': None,
                        'url': f'https://www.memorymarket.com/price/in/{pid}',
                    })
                if pid % 20 == 0:
                    log.info(f"MemoryMarket: scanned up to id {pid}, total {len(entries)}")
                await asyncio.sleep(0.5)
            except Exception:
                continue
    log.info(f"MemoryMarket: done, {len(entries)} entries")
    return entries

async def crawl_chipdip(rate: float) -> list[dict]:
    """ChipDip — Scrapling StealthyFetcher for bot protection.
    Note: ChipDip blocks datacenter IPs (DigitalOcean etc). Needs residential proxy.
    """
    log.info("ChipDip: starting (stealth mode)")
    entries = []
    try:
        async with AsyncStealthySession(headless=True) as session:
            for pg in range(1, 50):
                try:
                    url = f"https://www.chipdip.ru/catalog-show/ic-memory?x.page={pg}"
                    page = await session.fetch(url)
                    items = page.css('.with-hover') or page.css('[class*=item]')
                    if not items:
                        log.info(f"ChipDip: page {pg} — no items, stopping")
                        break
                    for item in items:
                        links = item.css('a[href*="/product/"]')
                        prices_els = item.css('[class*=price]')
                        if not links or not prices_els:
                            continue
                        pn = str(links.first.text).strip()
                        href = links.first.attrib.get('href', '')
                        price_rub = parse_price(str(prices_els.first.text))
                        if price_rub <= 0 or not pn:
                            continue
                        descs = item.css('[class*=desc]')
                        desc = str(descs.first.text).strip() if descs else ''
                        price_usd = round(price_rub / rate, 4) if rate > 0 else 0
                        entries.append({
                            'chip_type': classify_type(pn, desc),
                            'part_number': pn,
                            'description': desc[:200],
                            'brand': extract_brand(pn, desc),
                            'capacity': '',
                            'source': 'chipdip',
                            'distributor': 'ChipDip',
                            'price_usd': price_usd,
                            'price_rub': price_rub,
                            'price_cny': None,
                            'moq': 1,
                            'stock': None,
                            'url': f"https://www.chipdip.ru{href}" if href.startswith('/') else href,
                        })
                    log.info(f"ChipDip: page {pg}, {len(items)} items, total {len(entries)}")
                    await asyncio.sleep(2)
                except Exception as e:
                    log.warning(f"ChipDip: page {pg} error: {e}")
                    break
    except Exception as e:
        log.error(f"ChipDip: stealth session failed: {e}")
    log.info(f"ChipDip: done, {len(entries)} entries")
    return entries

async def crawl_ebay(rate: float) -> list[dict]:
    """eBay — Scrapling StealthyFetcher."""
    log.info("eBay: starting (stealth mode)")
    entries = []
    SEARCH_CATS = ["eMMC chip", "DDR4 IC", "NAND Flash IC", "NOR Flash IC", "DDR5 SDRAM", "LPDDR4 chip", "UFS IC"]
    try:
        async with AsyncStealthySession(headless=True) as session:
            for cat in SEARCH_CATS:
                try:
                    url = f"https://www.ebay.com/sch/i.html?_nkw={cat.replace(' ', '+')}&_sacat=0&LH_BIN=1&_pgn=1"
                    page = await session.fetch(url, network_idle=True)
                    cards = page.css('.s-card') or []
                    count = 0
                    for card in cards:
                        pe = card.css('[class*=price]')
                        te = card.css('[class*=title] span')
                        if not pe or not te:
                            continue
                        title = str(te.first.text).strip()
                        if 'shop on ebay' in title.lower():
                            continue
                        price = parse_price(str(pe.first.text))
                        if price <= 0 or price > 10000:
                            continue
                        count += 1
                        entries.append({
                            'chip_type': classify_type(cat, title),
                            'part_number': title[:100],
                            'description': title[:200],
                            'brand': extract_brand(title, ''),
                            'capacity': '',
                            'source': 'ebay',
                            'distributor': 'eBay',
                            'price_usd': round(price, 4),
                            'price_rub': round(price * rate, 2),
                            'price_cny': None,
                            'moq': 1,
                            'stock': None,
                            'url': url,
                        })
                    log.info(f"eBay: '{cat}' — {count} listings, total {len(entries)}")
                    await asyncio.sleep(3)
                except Exception as e:
                    log.warning(f"eBay: '{cat}' error: {e}")
    except Exception as e:
        log.error(f"eBay: stealth session failed: {e}")
    log.info(f"eBay: done, {len(entries)} entries")
    return entries

# ─── Database ───────────────────────────────────────────────────────

async def write_source_to_db(source_name: str, entries: list[dict], pool):
    """Write one source's entries to DB immediately (DELETE old + INSERT new).
    This allows iterative updates — each source appears in the app as soon as it's done."""
    if not entries:
        return 0
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete old data for this source only (not TRUNCATE entire table)
            deleted = await conn.execute(
                "DELETE FROM prices WHERE source = $1", source_name
            )
            log.info(f"DB: deleted old {source_name} rows ({deleted})")

            records = [
            (
                e['chip_type'], e['part_number'], e.get('description', ''),
                e.get('brand', 'Other'), e.get('capacity', ''),
                e['source'], e.get('distributor', ''),
                e.get('price_usd'), e.get('price_rub'), e.get('price_cny'),
                e.get('moq', 1), e.get('stock'),
                e.get('url', ''), now,
            )
            for e in entries
        ]
            await conn.copy_records_to_table(
                'prices',
                records=records,
                columns=['chip_type', 'part_number', 'description', 'brand', 'capacity',
                         'source', 'distributor', 'price_usd', 'price_rub', 'price_cny',
                         'moq', 'stock', 'url', 'fetched_at'],
            )
            # History (append only)
            hist = [
                (e['part_number'], e['source'], e.get('price_usd'), now)
                for e in entries if e.get('price_usd')
            ]
            if hist:
                await conn.copy_records_to_table(
                    'history',
                    records=hist,
                    columns=['part_number', 'source', 'price_usd', 'fetched_at'],
                )
            log.info(f"DB: {source_name} → {len(records)} prices + {len(hist)} history rows")
    return len(records)

# ─── Main ───────────────────────────────────────────────────────────

async def _dedup(entries: list[dict]) -> list[dict]:
    """Deduplicate by (part_number, source, distributor)."""
    seen = set()
    unique = []
    for e in entries:
        key = (e['part_number'], e['source'], e.get('distributor', ''))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


async def main():
    log.info("=== FULL CATALOG CRAWL STARTING ===")
    t0 = time.time()

    rate = await get_usd_rub_rate()
    log.info(f"USD/RUB: {rate:.2f}")

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    total_written = 0

    try:
        # ── Iterative crawl: each source writes to DB as soon as it finishes ──

        # 1. Fast sources first (they update the app quickly)
        crawlers = [
            ('jlcpcb',       crawl_jlcpcb),
            ('szlcsc',       crawl_szlcsc),
            ('memorymarket', crawl_memorymarket),
            ('lcsc',         crawl_lcsc),
            ('findchips',    crawl_findchips),
        ]

        for source_name, crawler_fn in crawlers:
            try:
                result = await crawler_fn(rate)
                if result:
                    unique = await _dedup(result)
                    log.info(f"{source_name}: {len(result)} raw → {len(unique)} unique")
                    n = await write_source_to_db(source_name, unique, pool)
                    total_written += n
                else:
                    log.warning(f"{source_name}: 0 entries")
            except Exception as e:
                log.error(f"{source_name}: FAILED — {e}")

        # 2. Browser-based (sequential)
        for crawler_fn, name in [(crawl_chipdip, 'chipdip')]:  # eBay removed — unreliable data
            try:
                result = await crawler_fn(rate)
                if result:
                    unique = await _dedup(result)
                    log.info(f"{name}: {len(result)} raw → {len(unique)} unique")
                    n = await write_source_to_db(name, unique, pool)
                    total_written += n
            except Exception as e:
                log.error(f"{name}: FAILED — {e}")

        # Cleanup: delete history rows older than 90 days
        try:
            async with pool.acquire() as conn:
                deleted = await conn.execute(
                    "DELETE FROM history WHERE fetched_at < NOW() - INTERVAL '90 days'"
                )
                log.info(f"History cleanup: {deleted}")
        except Exception as e:
            log.warning(f"History cleanup failed: {e}")

    finally:
        await pool.close()
    try:
        async with pool.acquire() as conn:
            deleted = await conn.execute(
                "DELETE FROM history WHERE fetched_at < NOW() - INTERVAL '90 days'"
            )
            log.info(f"History cleanup: {deleted}")
    except Exception as e:
        log.warning(f"History cleanup failed: {e}")

    elapsed = time.time() - t0
    log.info(f"=== DONE in {elapsed:.0f}s — {total_written} total entries written ===")

if __name__ == "__main__":
    asyncio.run(main())
