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
from scrapling.fetchers import StealthySession

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
    """SZLCSC (Chinese LCSC) — SSR HTML with __NEXT_DATA__."""
    log.info("SZLCSC: starting")
    entries = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    CNY_TO_USD = 0.14
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        for cat in CATEGORIES:
            for pg in range(1, 20):
                try:
                    url = f"https://so.szlcsc.com/global.html?k={cat}&pageIndex={pg}&pageSize=30"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        break
                    from scrapling.parser import Selector
                    page = Selector(resp.text)
                    script = page.css_first('script#__NEXT_DATA__')
                    if not script:
                        break
                    data = json.loads(script.text())
                    # Navigate to product list
                    products = []
                    props = data.get('props', {}).get('pageProps', {})
                    # Try multiple paths
                    for path in [
                        lambda: props['productList'],
                        lambda: props['soData']['searchResult']['productRecordList'],
                        lambda: props['data']['productList'],
                    ]:
                        try:
                            products = path()
                            if products:
                                break
                        except (KeyError, TypeError):
                            continue
                    if not products:
                        break
                    for prod in products:
                        if not isinstance(prod, dict):
                            continue
                        vo = prod.get('productVO', prod)
                        pn = vo.get('productModel', vo.get('productName', ''))
                        desc = vo.get('productDescEn', vo.get('catalogName', ''))
                        price_list = vo.get('productPriceList', [])
                        best_cny = 0.0
                        for tier in price_list:
                            if isinstance(tier, dict):
                                p = float(tier.get('productPrice', tier.get('price', 0)) or 0)
                                q = int(tier.get('ladder', tier.get('startPurchasedNumber', 0)) or 0)
                                if p > 0 and (q <= 10 or best_cny == 0):
                                    best_cny = p
                        if best_cny <= 0:
                            continue
                        price_usd = round(best_cny * CNY_TO_USD, 4)
                        entries.append({
                            'chip_type': classify_type(pn, desc),
                            'part_number': pn,
                            'description': desc[:200],
                            'brand': extract_brand(pn, desc),
                            'capacity': '',
                            'source': 'szlcsc',
                            'distributor': 'SZLCSC',
                            'price_usd': price_usd,
                            'price_rub': round(price_usd * rate, 2),
                            'price_cny': best_cny,
                            'moq': 1,
                            'stock': int(vo.get('stockNumber', vo.get('stockCount', 0)) or 0),
                            'url': f"https://so.szlcsc.com/global.html?k={pn}",
                        })
                    log.info(f"SZLCSC: {cat} page {pg}, {len(products)} products, total {len(entries)}")
                    await asyncio.sleep(2)
                except Exception as e:
                    log.warning(f"SZLCSC: {cat} page {pg} error: {e}")
                    break
    log.info(f"SZLCSC: done, {len(entries)} entries")
    return entries

async def crawl_jlcpcb(rate: float) -> list[dict]:
    """JLCPCB — JSON API."""
    log.info("JLCPCB: starting")
    entries = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
    }
    API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        for cat in CATEGORIES:
            for pg in range(1, 50):
                try:
                    body = {"keyword": cat, "currentPage": pg, "pageSize": 100}
                    resp = await client.post(API, json=body)
                    if resp.status_code == 403:
                        log.warning(f"JLCPCB: {cat} page {pg} — 403, moving on")
                        break
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    items = data.get('data', {}).get('componentPageInfo', {}).get('list', [])
                    if not items:
                        break
                    for item in items:
                        pn = item.get('componentModelEn', '')
                        desc = item.get('describe', '')
                        prices = item.get('componentPrices', [])
                        best = 0.0
                        for tier in prices:
                            p = float(tier.get('productPrice', 0) or 0)
                            q = int(tier.get('startNumber', 0) or 0)
                            if p > 0 and (q <= 10 or best == 0):
                                best = p
                        if best <= 0 or not pn:
                            continue
                        entries.append({
                            'chip_type': classify_type(pn, desc),
                            'part_number': pn,
                            'description': desc[:200],
                            'brand': extract_brand(pn, desc),
                            'capacity': '',
                            'source': 'jlcpcb',
                            'distributor': 'JLCPCB/LCSC',
                            'price_usd': round(best, 4),
                            'price_rub': round(best * rate, 2),
                            'price_cny': None,
                            'moq': int(item.get('leastNumber', 1) or 1),
                            'stock': int(item.get('stockCount', 0) or 0),
                            'url': item.get('lcscGoodsUrl', ''),
                        })
                    log.info(f"JLCPCB: {cat} page {pg}, {len(items)} items, total {len(entries)}")
                    await asyncio.sleep(2)
                except Exception as e:
                    log.warning(f"JLCPCB: {cat} page {pg} error: {e}")
                    break
    log.info(f"JLCPCB: done, {len(entries)} entries")
    return entries

async def crawl_memorymarket(rate: float) -> list[dict]:
    """MemoryMarket — spot price index + detail pages."""
    log.info("MemoryMarket: starting")
    entries = []
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"}
    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
        # Main page
        try:
            resp = await client.get("https://www.memorymarket.com/")
            if resp.status_code == 200:
                from scrapling.parser import Selector
                page = Selector(resp.text)
                for table in page.css('table'):
                    hdrs = [th.text(strip=True).lower() for th in table.css('thead th')]
                    if not hdrs:
                        continue
                    for tr in table.css('tbody tr'):
                        cells = [td.text(strip=True) for td in tr.css('td')]
                        if len(cells) < 3:
                            continue
                        try:
                            price = float(cells[2].replace(',', '').replace('$', ''))
                        except ValueError:
                            continue
                        if price <= 0:
                            continue
                        product = cells[0]
                        spec = cells[1] if len(cells) > 1 else ''
                        entries.append({
                            'chip_type': classify_type(product, spec),
                            'part_number': f"{product} {spec}".strip(),
                            'description': f"{product} {spec} spot index",
                            'brand': extract_brand(product, ''),
                            'capacity': spec,
                            'source': 'memorymarket',
                            'distributor': 'Spot Index',
                            'price_usd': round(price, 4),
                            'price_rub': round(price * rate, 2),
                            'price_cny': None,
                            'moq': 0,
                            'stock': None,
                            'url': 'https://www.memorymarket.com/',
                        })
                log.info(f"MemoryMarket: main page, {len(entries)} entries")
        except Exception as e:
            log.warning(f"MemoryMarket: main page error: {e}")
        # Detail pages /price/in/1..500
        for pid in range(1, 500):
            try:
                resp = await client.get(f"https://www.memorymarket.com/price/in/{pid}")
                if resp.status_code != 200:
                    continue
                from scrapling.parser import Selector
                page = Selector(resp.text)
                title = page.css_first('h1')
                if not title:
                    continue
                title_text = title.text(strip=True)
                # Look for price in page
                price_el = page.find_by_regex(r'\$[\d,.]+')
                if price_el:
                    price_text = price_el[0].text(strip=True) if hasattr(price_el[0], 'text') else str(price_el[0])
                    price = parse_price(price_text)
                    if price > 0:
                        entries.append({
                            'chip_type': classify_type(title_text, ''),
                            'part_number': title_text[:100],
                            'description': title_text[:200],
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
                if pid % 50 == 0:
                    log.info(f"MemoryMarket: detail pages 1-{pid}, total {len(entries)}")
                await asyncio.sleep(0.5)
            except Exception:
                continue
    log.info(f"MemoryMarket: done, {len(entries)} entries")
    return entries

async def crawl_chipdip(rate: float) -> list[dict]:
    """ChipDip — Scrapling StealthyFetcher for bot protection."""
    log.info("ChipDip: starting (stealth mode)")
    entries = []
    try:
        with StealthySession(headless=True) as session:
            for pg in range(1, 50):
                try:
                    url = f"https://www.chipdip.ru/catalog-show/ic-memory?x.page={pg}"
                    page = session.fetch(url)
                    items = page.css('.with-hover', all=True) or page.css('[class*=item]', all=True)
                    if not items:
                        log.info(f"ChipDip: page {pg} — no items, stopping")
                        break
                    for item in items:
                        link = item.css_first('a[href*="/product/"]')
                        price_el = item.css_first('[class*=price]')
                        if not link or not price_el:
                            continue
                        pn = link.text(strip=True)
                        href = link.attrib.get('href', '')
                        price_rub = parse_price(price_el.text(strip=True))
                        if price_rub <= 0 or not pn:
                            continue
                        desc_el = item.css_first('[class*=desc]')
                        desc = desc_el.text(strip=True) if desc_el else ''
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
                    time.sleep(2)
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
        with StealthySession(headless=True) as session:
            for cat in SEARCH_CATS:
                try:
                    url = f"https://www.ebay.com/sch/i.html?_nkw={cat.replace(' ', '+')}&_sacat=0&LH_BIN=1&_pgn=1"
                    page = session.fetch(url, network_idle=True)
                    cards = page.css('.s-item, [class*=s-card]', all=True)
                    prices_found = []
                    for card in cards:
                        price_el = card.css_first('.s-item__price, [class*=price]')
                        title_el = card.css_first('.s-item__title, [class*=title] span')
                        if not price_el or not title_el:
                            continue
                        title = title_el.text(strip=True)
                        if 'shop on ebay' in title.lower():
                            continue
                        price = parse_price(price_el.text(strip=True))
                        if price > 0:
                            prices_found.append((title, price))
                    if prices_found:
                        # Take median
                        sorted_p = sorted(prices_found, key=lambda x: x[1])
                        mid = len(sorted_p) // 2
                        title, median_price = sorted_p[mid]
                        entries.append({
                            'chip_type': classify_type(cat, ''),
                            'part_number': cat,
                            'description': f"eBay median ({len(prices_found)} listings)",
                            'brand': extract_brand(title, ''),
                            'capacity': '',
                            'source': 'ebay',
                            'distributor': 'eBay',
                            'price_usd': round(median_price, 4),
                            'price_rub': round(median_price * rate, 2),
                            'price_cny': None,
                            'moq': 1,
                            'stock': len(prices_found),
                            'url': url,
                        })
                        log.info(f"eBay: '{cat}' — {len(prices_found)} listings, median ${median_price:.2f}")
                    time.sleep(3)
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
        crawl_memorymarket(rate),
        return_exceptions=True,
    )

    all_entries = []
    for name, result in zip(['findchips', 'szlcsc', 'jlcpcb', 'memorymarket'], http_results):
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
