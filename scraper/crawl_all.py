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

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://mpt:mpt_secure_2026@127.0.0.1:5432/memoryprices")

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

async def crawl_findchips(rate: float) -> list[dict]:
    """FindChips — HTML scraping with pagination."""
    log.info("FindChips: starting")
    entries = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html",
    }
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        for cat in CATEGORIES:
            for page_num in range(1, 30):  # up to 30 pages per category
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
                                p = float(t[2])
                                if best == 0 or (int(t[0]) <= 10 and p > 0):
                                    best = p
                        if best <= 0:
                            continue
                        try:
                            stock = int(str(stock_s).replace(',', ''))
                        except ValueError:
                            stock = 0
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
                    log.info(f"FindChips: {cat} page {page_num}, {len(rows)} rows, total {len(entries)}")
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
    CNY_TO_USD = 0.14
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        for cat in CATEGORIES:
            for pg in range(1, 51):  # up to 50 pages (1500 items / 30 per page)
                try:
                    url = f"https://so.szlcsc.com/global.html?k={cat}&pageIndex={pg}&pageSize=30"
                    resp = await client.get(url)
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
                        best_cny = 0.0
                        for tier in price_list:
                            if isinstance(tier, dict):
                                p = float(tier.get('productPrice', tier.get('thePrice', 0)) or 0)
                                q = int(tier.get('startPurchasedNumber', tier.get('spNumber', 0)) or 0)
                                if p > 0 and (q <= 10 or best_cny == 0):
                                    best_cny = p
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
                    await asyncio.sleep(2)
                except Exception as e:
                    log.warning(f"SZLCSC: {cat} page {pg} error: {e}")
                    break
    log.info(f"SZLCSC: done, {len(entries)} entries")
    return entries

JLCPCB_API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
JLCPCB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://jlcpcb.com/parts/componentSearch",
    "Origin": "https://jlcpcb.com",
}

def _extract_best_price(prices: list) -> float:
    """Return lowest qty-1 price from a JLCPCB componentPrices list."""
    best = 0.0
    for tier in prices:
        p = float(tier.get('productPrice', 0) or 0)
        q = int(tier.get('startNumber', 0) or 0)
        if p > 0 and (q <= 10 or best == 0):
            best = p
    return best

def _jlcpcb_item_to_entry(item: dict, rate: float, source: str, distributor: str) -> dict | None:
    """Convert a raw JLCPCB list item to a normalised price entry. Returns None if unusable."""
    pn = item.get('componentModelEn', '')
    if not pn:
        return None
    desc = item.get('describe', '') or ''
    best = _extract_best_price(item.get('componentPrices', []))
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
            # Pause between categories so the server's rate-limit window resets.
            await asyncio.sleep(category_delay)
        # Fresh client per category — avoids connection-level tracking.
        async with httpx.AsyncClient(timeout=30, headers=JLCPCB_HEADERS) as client:
            for pg in range(1, 50):
                try:
                    body = {"keyword": cat, "currentPage": pg, "pageSize": 100}
                    resp = await client.post(JLCPCB_API, json=body)
                    if resp.status_code == 403:
                        log.warning(f"{source}: {cat} page {pg} — 403 (rate-limited), skipping category")
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
        categories=CATEGORIES,
        rate=rate,
        source='jlcpcb',
        distributor='JLCPCB/LCSC',
        page_delay=3.0,
        category_delay=15.0,
    )
    log.info(f"JLCPCB: done, {len(entries)} entries")
    return entries


# ─── LCSC International ──────────────────────────────────────────────

# Keywords specifically effective for LCSC's international catalogue.
# Subset of CATEGORIES optimised for the LCSC search index (avoids
# redundant queries that return 0 results on the LCSC side).
LCSC_KEYWORDS = [
    "eMMC", "UFS", "DDR4", "DDR5", "DDR3",
    "LPDDR4", "LPDDR5", "NAND Flash", "NOR Flash", "SRAM",
    "Flash Memory", "DRAM", "SDRAM",
]

async def crawl_lcsc(rate: float) -> list[dict]:
    """LCSC International (lcsc.com) — uses the JLCPCB/LCSC component search JSON API.

    The endpoint is shared infrastructure: results have lcscGoodsUrl pointing to
    lcsc.com product pages and USD prices already denominated in USD.
    We tag entries source='lcsc' / distributor='LCSC' to keep them separate from
    the JLCPCB SMT-library entries.
    """
    log.info("LCSC: starting")
    entries = await _jlcpcb_fetch_pages(
        categories=LCSC_KEYWORDS,
        rate=rate,
        source='lcsc',
        distributor='LCSC',
        page_delay=3.0,
        category_delay=15.0,
    )
    log.info(f"LCSC: done, {len(entries)} entries")
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

async def write_to_db(all_entries: list[dict]):
    log.info(f"Writing {len(all_entries)} entries to PostgreSQL...")
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    now = datetime.now(timezone.utc)
    try:
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE prices RESTART IDENTITY")
            records = [
                (
                    e['chip_type'], e['part_number'], e.get('description', ''),
                    e.get('brand', 'Other'), e.get('capacity', ''),
                    e['source'], e.get('distributor', ''),
                    e.get('price_usd'), e.get('price_rub'), e.get('price_cny'),
                    e.get('moq', 1), e.get('stock'),
                    e.get('url', ''), now,
                )
                for e in all_entries
            ]
            await conn.copy_records_to_table(
                'prices',
                records=records,
                columns=['chip_type', 'part_number', 'description', 'brand', 'capacity',
                         'source', 'distributor', 'price_usd', 'price_rub', 'price_cny',
                         'moq', 'stock', 'url', 'fetched_at'],
            )
            log.info(f"Prices table: {len(records)} rows written")
            # History (append only)
            hist = [
                (e['part_number'], e['source'], e.get('price_usd'), now)
                for e in all_entries if e.get('price_usd')
            ]
            await conn.copy_records_to_table(
                'history',
                records=hist,
                columns=['part_number', 'source', 'price_usd', 'fetched_at'],
            )
            log.info(f"History table: {len(hist)} rows appended")
    finally:
        await pool.close()

# ─── Main ───────────────────────────────────────────────────────────

async def main():
    log.info("=== FULL CATALOG CRAWL STARTING ===")
    t0 = time.time()

    rate = await get_usd_rub_rate()
    log.info(f"USD/RUB: {rate:.2f}")

    # Run HTTP-based crawlers concurrently, browser-based sequentially
    http_results = await asyncio.gather(
        crawl_findchips(rate),
        crawl_szlcsc(rate),
        crawl_jlcpcb(rate),
        crawl_lcsc(rate),
        crawl_memorymarket(rate),
        return_exceptions=True,
    )

    all_entries = []
    for name, result in zip(['findchips', 'szlcsc', 'jlcpcb', 'lcsc', 'memorymarket'], http_results):
        if isinstance(result, Exception):
            log.error(f"{name}: FAILED — {result}")
        else:
            log.info(f"{name}: {len(result)} entries")
            all_entries.extend(result)

    # Browser-based (sequential to save memory)
    for crawler_fn, name in [(crawl_chipdip, 'chipdip'), (crawl_ebay, 'ebay')]:
        try:
            result = await crawler_fn(rate)
            log.info(f"{name}: {len(result)} entries")
            all_entries.extend(result)
        except Exception as e:
            log.error(f"{name}: FAILED — {e}")

    # Deduplicate by (part_number, source, distributor)
    seen = set()
    unique = []
    for e in all_entries:
        key = (e['part_number'], e['source'], e.get('distributor', ''))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    log.info(f"Total: {len(all_entries)} raw → {len(unique)} unique entries")

    if unique:
        await write_to_db(unique)

    elapsed = time.time() - t0
    log.info(f"=== DONE in {elapsed:.0f}s ===")

if __name__ == "__main__":
    asyncio.run(main())
