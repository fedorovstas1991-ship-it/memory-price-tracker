import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import datetime, date
from typing import Literal, Optional

import asyncpg
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from src.capacity import SQL_CAPACITY_REGEX, normalize_capacity_literal


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


class SafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, cls=DecimalEncoder, ensure_ascii=False).encode("utf-8")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://mpt:mpt_secure_2026@127.0.0.1:5432/memoryprices",
)

pool: asyncpg.Pool = None  # type: ignore[assignment]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    yield
    await pool.close()


app = FastAPI(title="Memory Price Tracker API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fedorovstas1991-ship-it.github.io",
        "*",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_SORT_COLUMNS = {"price_usd", "price_rub", "part_number"}
ALLOWED_ORDERS = {"asc", "desc"}

FLASH_TYPES = ['eMMC', 'UFS', 'NAND Flash', 'NOR Flash', 'NAND', 'NOR']
RAM_TYPES = ['DDR3', 'DDR4', 'DDR5', 'LPDDR4', 'LPDDR4X', 'LPDDR5', 'SRAM', 'SDRAM', 'DRAM']
ALL_TYPES = FLASH_TYPES + RAM_TYPES


def _resolve_chip_types(group: Optional[str]) -> list:
    if group == "flash":
        return FLASH_TYPES
    if group == "ram":
        return RAM_TYPES
    return ALL_TYPES


def _safe_sort(sort: str, order: str) -> str:
    col = sort if sort in ALLOWED_SORT_COLUMNS else "price_usd"
    direction = order.lower() if order.lower() in ALLOWED_ORDERS else "asc"
    return f"{col} {direction}"


def _capacity_sql_expr(
    description_col: str = "description", part_number_col: str = "part_number"
) -> str:
    cap_match_expr = (
        f"COALESCE(regexp_match({description_col}, '{SQL_CAPACITY_REGEX}'), "
        f"regexp_match({part_number_col}, '{SQL_CAPACITY_REGEX}'))"
    )
    return f"({cap_match_expr})[1] || ({cap_match_expr})[2]"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/prices")
async def get_prices(
    type: Optional[str] = Query(None, description="Filter by chip_type (comma-separated for multiple)"),
    brand: Optional[str] = Query(None, description="Filter by brand"),
    capacity: Optional[str] = Query(None, description="Filter by capacity"),
    source: Optional[str] = Query(None, description="Filter by source"),
    search: Optional[str] = Query(
        None, description="ILIKE search on part_number, description, brand"
    ),
    in_stock: Optional[bool] = Query(None, description="Filter only items with stock > 0"),
    min_stock: Optional[int] = Query(None, ge=0, description="Minimum stock quantity"),
    sort: str = Query("price_usd", description="Sort column: price_usd | price_rub | part_number"),
    order: str = Query("asc", description="Sort direction: asc | desc"),
    limit: int = Query(100, ge=1, le=100000, description="Max rows (1-100000)"),
    offset: int = Query(0, ge=0, description="Row offset"),
    include_meta: bool = Query(False, description="Include meta counts and chart_meta in response"),
):
    conditions = []
    params = []
    idx = 1

    if type is not None:
        type_list = [t.strip() for t in type.split(",") if t.strip()]
        if len(type_list) == 1:
            conditions.append(f"chip_type = ${idx}")
            params.append(type_list[0])
            idx += 1
        elif type_list:
            placeholders = ", ".join(f"${idx + i}" for i in range(len(type_list)))
            conditions.append(f"chip_type IN ({placeholders})")
            params.extend(type_list)
            idx += len(type_list)

    if brand is not None:
        conditions.append(f"brand = ${idx}")
        params.append(brand)
        idx += 1

    if capacity is not None:
        normalized_capacity = normalize_capacity_literal(capacity)
        if normalized_capacity:
            conditions.append(f"{_capacity_sql_expr()} = ${idx}")
            params.append(normalized_capacity)
            idx += 1
        else:
            # Keep backward-compat for malformed/legacy capacity values.
            # Case-sensitive regex avoids merging Mb/MB and Gb/GB.
            cap_pattern = re.sub(r"(?<=\d)(?=[A-Za-z])", lambda _: r"\s*", capacity)
            conditions.append(f"(description ~ ${idx} OR part_number ~ ${idx})")
            params.append(f"(^|[^0-9A-Za-z]){cap_pattern}($|[^A-Za-z0-9])")
            idx += 1

    if source is not None:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1

    if search is not None:
        pattern = f"%{search}%"
        conditions.append(
            f"(part_number ILIKE ${idx} OR description ILIKE ${idx} OR brand ILIKE ${idx})"
        )
        params.append(pattern)
        idx += 1

    if in_stock is True:
        conditions.append("stock > 0")

    if min_stock is not None and min_stock > 0:
        conditions.append(f"stock >= ${idx}")
        params.append(min_stock)
        idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order_clause = _safe_sort(sort, order)

    # params for WHERE only (used in meta queries)
    where_params = list(params)

    params.append(limit)
    params.append(offset)

    items_query = f"""
        SELECT
            id,
            chip_type,
            part_number,
            description,
            capacity,
            brand,
            source,
            price_usd,
            price_rub,
            moq,
            stock,
            url,
            fetched_at
        FROM prices
        {where_clause}
        ORDER BY {order_clause}
        LIMIT ${idx} OFFSET ${idx + 1}
    """

    if not include_meta:
        async with pool.acquire() as conn:
            rows = await conn.fetch(items_query, *params)
        return SafeJSONResponse(content=[dict(r) for r in rows])

    # --- include_meta=true: run 4 queries in parallel ---
    meta_query = f"""
        SELECT
            COUNT(*)                                              AS total,
            COUNT(*) FILTER (WHERE stock > 0)                    AS stock_total,
            COUNT(DISTINCT chip_type)                            AS types_total,
            COUNT(DISTINCT source)                               AS sources_total,
            COALESCE(SUM(stock) FILTER (WHERE stock > 0), 0)    AS total_stock
        FROM prices
        {where_clause}
    """

    cap_expr = _capacity_sql_expr()

    prices_by_cap_query = f"""
        WITH filtered AS (
            SELECT price_usd, description, part_number
            FROM prices
            {where_clause}
        ),
        extracted AS (
            SELECT
                price_usd,
                {cap_expr} AS cap
            FROM filtered
            WHERE price_usd > 0
        )
        SELECT cap AS capacity,
               ROUND(AVG(price_usd)::numeric, 2) AS avg_price,
               COUNT(*) AS count
        FROM extracted
        WHERE cap IS NOT NULL
        GROUP BY cap
        ORDER BY count DESC
        LIMIT 10
    """

    stock_by_cap_query = f"""
        WITH filtered AS (
            SELECT stock, description, part_number
            FROM prices
            {where_clause}
        ),
        extracted AS (
            SELECT
                stock,
                {cap_expr} AS cap
            FROM filtered
            WHERE stock > 0
        )
        SELECT cap AS capacity,
               SUM(stock) AS total_stock,
               COUNT(*) AS positions
        FROM extracted
        WHERE cap IS NOT NULL
        GROUP BY cap
        ORDER BY total_stock DESC
        LIMIT 10
    """

    types_query = f"""
        SELECT chip_type AS type, COUNT(*) AS count
        FROM prices
        {where_clause}
        GROUP BY chip_type
        ORDER BY count DESC
    """

    brands_where = (where_clause + " AND brand IS NOT NULL AND brand != ''") if where_clause else "WHERE brand IS NOT NULL AND brand != ''"
    brands_query = f"""
        SELECT brand, COUNT(*) AS count
        FROM prices
        {brands_where}
        GROUP BY brand
        ORDER BY count DESC
    """

    sources_query = f"""
        SELECT source, COUNT(*) AS count
        FROM prices
        {where_clause}
        GROUP BY source
        ORDER BY count DESC
    """

    capacities_query = f"""
        WITH caps AS (
            SELECT {cap_expr} AS cap
            FROM prices
            {where_clause}
        )
        SELECT cap AS val, COUNT(*) AS count
        FROM caps
        WHERE cap IS NOT NULL
        GROUP BY cap
        ORDER BY count DESC
    """

    async with pool.acquire() as conn:
        items_rows = await conn.fetch(items_query, *params)
        meta_row = await conn.fetchrow(meta_query, *where_params)
        price_cap_rows = await conn.fetch(prices_by_cap_query, *where_params)
        stock_cap_rows = await conn.fetch(stock_by_cap_query, *where_params)
        types_rows = await conn.fetch(types_query, *where_params)
        brands_rows = await conn.fetch(brands_query, *where_params)
        sources_rows = await conn.fetch(sources_query, *where_params)
        caps_rows = await conn.fetch(capacities_query, *where_params)

    meta = {
        "total": meta_row["total"],
        "stock_total": meta_row["stock_total"],
        "types_total": meta_row["types_total"],
        "sources_total": meta_row["sources_total"],
    }

    prices_by_capacity = [
        {
            "capacity": r["capacity"],
            "avg_price": float(r["avg_price"]) if r["avg_price"] is not None else None,
            "count": r["count"],
        }
        for r in price_cap_rows
    ]

    stock_by_capacity = [
        {
            "capacity": r["capacity"],
            "total_stock": r["total_stock"],
            "positions": r["positions"],
        }
        for r in stock_cap_rows
    ]

    return SafeJSONResponse(content={
        "items": [dict(r) for r in items_rows],
        "meta": meta,
        "chart_meta": {
            "prices_by_capacity": prices_by_capacity,
            "stock_by_capacity": stock_by_capacity,
            "total_stock": int(meta_row["total_stock"]),
        },
        "filter_options": {
            "types": [{"type": r["type"], "count": r["count"]} for r in types_rows],
            "brands": [{"brand": r["brand"], "count": r["count"]} for r in brands_rows],
            "sources": [{"source": r["source"], "count": r["count"]} for r in sources_rows],
            "capacities": [{"val": r["val"], "count": r["count"]} for r in caps_rows],
        },
    })


@app.get("/api/types")
async def get_types():
    query = """
        SELECT chip_type AS type, COUNT(*) AS count
        FROM prices
        GROUP BY chip_type
        ORDER BY count DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return SafeJSONResponse(content=[dict(r) for r in rows])


@app.get("/api/brands")
async def get_brands():
    query = """
        SELECT brand, COUNT(*) AS count
        FROM prices
        WHERE brand IS NOT NULL AND brand <> ''
        GROUP BY brand
        ORDER BY count DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return SafeJSONResponse(content=[dict(r) for r in rows])


@app.get("/api/sources")
async def get_sources():
    query = """
        SELECT source, COUNT(*) AS count
        FROM prices
        GROUP BY source
        ORDER BY count DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return SafeJSONResponse(content=[dict(r) for r in rows])


@app.get("/api/export")
async def export_csv(
    type: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    capacity: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    in_stock: Optional[bool] = Query(None),
    min_stock: Optional[int] = Query(None, ge=0),
    sort: str = Query("price_usd"),
    order: str = Query("asc"),
):
    """Export filtered prices as CSV file."""
    conditions = []
    params = []
    idx = 1

    if type is not None:
        type_list = [t.strip() for t in type.split(",") if t.strip()]
        if len(type_list) == 1:
            conditions.append(f"chip_type = ${idx}")
            params.append(type_list[0])
            idx += 1
        elif type_list:
            placeholders = ", ".join(f"${idx + i}" for i in range(len(type_list)))
            conditions.append(f"chip_type IN ({placeholders})")
            params.extend(type_list)
            idx += len(type_list)

    if brand is not None:
        conditions.append(f"brand = ${idx}")
        params.append(brand)
        idx += 1

    if capacity is not None:
        normalized_capacity = normalize_capacity_literal(capacity)
        if normalized_capacity:
            conditions.append(f"{_capacity_sql_expr()} = ${idx}")
            params.append(normalized_capacity)
            idx += 1
        else:
            cap_pattern = re.sub(r"(?<=\d)(?=[A-Za-z])", lambda _: r"\s*", capacity)
            conditions.append(f"(description ~ ${idx} OR part_number ~ ${idx})")
            params.append(f"(^|[^0-9A-Za-z]){cap_pattern}($|[^A-Za-z0-9])")
            idx += 1

    if source is not None:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1

    if search is not None:
        conditions.append(
            f"(part_number ILIKE ${idx} OR description ILIKE ${idx} OR brand ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1

    if in_stock is True:
        conditions.append("stock > 0")

    if min_stock is not None and min_stock > 0:
        conditions.append(f"stock >= ${idx}")
        params.append(min_stock)
        idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order_clause = _safe_sort(sort, order)

    query = f"""
        SELECT part_number, chip_type, brand, description, capacity,
               source, price_usd, price_rub, stock, moq, url
        FROM prices {where_clause}
        ORDER BY {order_clause}
        LIMIT 100000
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    import io
    import csv
    output = io.StringIO()
    output.write("\ufeff")  # BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["Part Number", "Type", "Brand", "Description", "Capacity",
                     "Source", "Price USD", "Price RUB", "Stock", "MOQ", "URL"])
    for r in rows:
        writer.writerow([
            r["part_number"], r["chip_type"], r["brand"], r["description"],
            r["capacity"], r["source"],
            float(r["price_usd"]) if r["price_usd"] else "",
            float(r["price_rub"]) if r["price_rub"] else "",
            r["stock"] or "", r["moq"] or "", r["url"] or "",
        ])

    output.seek(0)
    today = date.today().isoformat()
    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="memory-prices-{today}.csv"'},
    )


@app.get("/api/stats")
async def get_stats():
    query = """
        SELECT
            COUNT(*)                                     AS total,
            COUNT(*) FILTER (WHERE stock > 0)           AS in_stock,
            COUNT(DISTINCT chip_type)                   AS types,
            COUNT(DISTINCT brand)                       AS brands,
            COUNT(DISTINCT source)                      AS sources,
            MAX(fetched_at)                             AS updated
        FROM prices
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query)

    result = dict(row)
    # Serialize datetime to ISO string if present
    if result.get("updated") is not None:
        result["updated"] = result["updated"].isoformat()
    return SafeJSONResponse(content=result)


@app.get("/api/history/{part_number}")
async def get_history(
    part_number: str,
    mode: Literal["daily", "full"] = Query(
        "daily", description="History mode: daily (latest point per day/source) or full"
    ),
):
    if mode == "full":
        query = """
            SELECT
                h.fetched_at AS date,
                h.source,
                h.price_usd
            FROM history h
            WHERE h.part_number = $1
              AND h.price_usd IS NOT NULL
            ORDER BY h.fetched_at ASC, h.source ASC
        """
    else:
        query = """
            SELECT
                day AS date,
                source,
                price_usd
            FROM (
                SELECT DISTINCT ON ((h.fetched_at::date), h.source)
                    h.fetched_at::date AS day,
                    h.source,
                    h.price_usd,
                    h.fetched_at
                FROM history h
                WHERE h.part_number = $1
                  AND h.price_usd IS NOT NULL
                ORDER BY (h.fetched_at::date), h.source, h.fetched_at DESC
            ) latest_per_day
            ORDER BY date ASC, source ASC
        """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, part_number)

    if not rows:
        raise HTTPException(status_code=404, detail="Part number not found")

    result = []
    for r in rows:
        result.append(
            {
                "date": r["date"].isoformat(),
                "source": r["source"],
                "price_usd": r["price_usd"],
            }
        )
    return SafeJSONResponse(content=result)


@app.get("/api/capacities")
async def get_capacities():
    cap_expr = _capacity_sql_expr()
    query = f"""
        SELECT val, COUNT(*) AS count
        FROM (
            SELECT {cap_expr} AS val
            FROM prices
        ) sub
        WHERE val IS NOT NULL
        GROUP BY val
        ORDER BY count DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return SafeJSONResponse(content=[dict(r) for r in rows])


@app.get("/api/charts/avg_by_type")
async def chart_avg_by_type():
    query = """
        SELECT
            chip_type AS type,
            ROUND(AVG(price_usd)::numeric, 4) AS avg_price,
            COUNT(*) AS count
        FROM prices
        GROUP BY chip_type
        ORDER BY avg_price ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)

    result = []
    for r in rows:
        result.append(
            {
                "type": r["type"],
                "avg_price": float(r["avg_price"]) if r["avg_price"] is not None else None,
                "count": r["count"],
            }
        )
    return SafeJSONResponse(content=result)


@app.get("/api/charts/by_source")
async def chart_by_source():
    query = """
        SELECT source, COUNT(*) AS count
        FROM prices
        GROUP BY source
        ORDER BY count DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return SafeJSONResponse(content=[dict(r) for r in rows])


@app.get("/api/market")
async def get_market():
    query = """
        SELECT m.source, m.item, m.category, m.daily_high, m.daily_low,
               m.session_avg, m.session_change, m.price_date, m.fetched_at,
               m.percent_week, m.percent_month
        FROM market_prices m
        INNER JOIN (
            SELECT source, category,
                   MAX(COALESCE(price_date, '1970-01-01'::date)) AS max_date
            FROM market_prices
            GROUP BY source, category
        ) latest ON m.source = latest.source
                 AND m.category = latest.category
                 AND COALESCE(m.price_date, '1970-01-01'::date) = latest.max_date
        ORDER BY m.category, m.item
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)

    result: dict[str, list] = {}
    for r in rows:
        cat = r["category"]
        if cat not in result:
            result[cat] = []
        result[cat].append(
            {
                "source": r["source"],
                "item": r["item"],
                "daily_high": r["daily_high"],
                "daily_low": r["daily_low"],
                "session_avg": r["session_avg"],
                "session_change": r["session_change"],
                "price_date": r["price_date"].isoformat() if r["price_date"] else None,
                "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
                "percent_week": float(r["percent_week"]) if r["percent_week"] is not None else None,
                "percent_month": float(r["percent_month"]) if r["percent_month"] is not None else None,
            }
        )
    return SafeJSONResponse(content=result)


@app.get("/api/market/history/{item}")
async def get_market_history(
    item: str,
    limit: int = Query(200, ge=1, le=5000, description="Max rows"),
):
    query = """
        SELECT source, daily_high, daily_low, session_avg, session_change, price_date,
               percent_week, percent_month
        FROM market_prices
        WHERE item = $1
        ORDER BY price_date ASC
        LIMIT $2
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, item, limit)

    if not rows:
        raise HTTPException(status_code=404, detail="Item not found")

    result = []
    for r in rows:
        result.append(
            {
                "source": r["source"],
                "daily_high": r["daily_high"],
                "daily_low": r["daily_low"],
                "session_avg": r["session_avg"],
                "session_change": r["session_change"],
                "price_date": r["price_date"].isoformat() if r["price_date"] else None,
                "percent_week": float(r["percent_week"]) if r["percent_week"] is not None else None,
                "percent_month": float(r["percent_month"]) if r["percent_month"] is not None else None,
            }
        )
    return SafeJSONResponse(content=result)


@app.get("/api/charts/market_summary")
async def chart_market_summary():
    """Average price per market category (latest data only)."""
    query = """
        WITH latest AS (
            SELECT source, category,
                   MAX(COALESCE(price_date, '1970-01-01'::date)) AS max_date
            FROM market_prices
            GROUP BY source, category
        )
        SELECT m.category,
               ROUND(AVG(m.session_avg)::numeric, 2) AS avg_price,
               COUNT(*) AS items
        FROM market_prices m
        JOIN latest l ON m.source = l.source AND m.category = l.category
             AND COALESCE(m.price_date, '1970-01-01'::date) = l.max_date
        WHERE m.session_avg IS NOT NULL AND m.session_avg > 0.01
        GROUP BY m.category
        ORDER BY avg_price DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    result = []
    for r in rows:
        result.append({
            "category": r["category"],
            "avg_price": float(r["avg_price"]) if r["avg_price"] else None,
            "items": r["items"],
        })
    return SafeJSONResponse(content=result)


@app.get("/api/charts/prices_by_capacity")
async def chart_prices_by_capacity(
    group: Optional[str] = Query(None, description="Filter group: flash | ram | (omit for all)"),
):
    chip_types = _resolve_chip_types(group)
    cap_expr = _capacity_sql_expr()
    query = f"""
        WITH extracted AS (
            SELECT
                price_usd,
                {cap_expr} AS capacity
            FROM prices
            WHERE price_usd > 0
              AND chip_type = ANY($1)
        )
        SELECT capacity, ROUND(AVG(price_usd)::numeric, 2) AS avg_price, COUNT(*) AS count
        FROM extracted
        WHERE capacity IS NOT NULL
        GROUP BY capacity
        ORDER BY count DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, chip_types)

    result = []
    for r in rows:
        result.append(
            {
                "capacity": r["capacity"],
                "avg_price": float(r["avg_price"]) if r["avg_price"] is not None else None,
                "count": r["count"],
            }
        )
    return SafeJSONResponse(content=result)


@app.get("/api/charts/stock_by_capacity")
async def chart_stock_by_capacity(
    group: Optional[str] = Query(None, description="Filter group: flash | ram | (omit for all)"),
):
    chip_types = _resolve_chip_types(group)
    cap_expr = _capacity_sql_expr()
    query = f"""
        WITH extracted AS (
            SELECT
                stock,
                {cap_expr} AS capacity
            FROM prices
            WHERE stock > 0
              AND chip_type = ANY($1)
        )
        SELECT capacity, SUM(stock) AS total_stock, COUNT(*) AS positions
        FROM extracted
        WHERE capacity IS NOT NULL
        GROUP BY capacity
        ORDER BY total_stock DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, chip_types)

    result = []
    for r in rows:
        result.append(
            {
                "capacity": r["capacity"],
                "total_stock": r["total_stock"],
                "positions": r["positions"],
            }
        )
    return SafeJSONResponse(content=result)


@app.get("/api/charts/deals")
async def chart_deals(
    group: Optional[str] = Query(None, description="Filter group: flash | ram | (omit for all)"),
    type: Optional[str] = Query(None, description="Filter by chip_type (comma-separated)"),
    brand: Optional[str] = Query(None, description="Filter by brand"),
    capacity: Optional[str] = Query(None, description="Capacity filter (e.g. 8GB, 256Mb)"),
    source: Optional[str] = Query(None, description="Filter by source"),
    search: Optional[str] = Query(None, description="ILIKE search"),
    in_stock: Optional[bool] = Query(None, description="Only items with stock > 0"),
    min_stock: int = Query(100, ge=0, description="Minimum stock quantity"),
):
    # Resolve chip types: explicit type param > group buttons > all
    if type is not None:
        chip_types = [t.strip() for t in type.split(",") if t.strip()]
    else:
        chip_types = _resolve_chip_types(group)
    cap_expr = _capacity_sql_expr()

    extra_where = ""
    params: list = [min_stock, chip_types]
    idx = 3

    if brand is not None:
        extra_where += f" AND brand = ${idx}"
        params.append(brand)
        idx += 1

    if source is not None:
        extra_where += f" AND source = ${idx}"
        params.append(source)
        idx += 1

    if search is not None:
        extra_where += f" AND (part_number ILIKE ${idx} OR description ILIKE ${idx} OR brand ILIKE ${idx})"
        params.append(f"%{search}%")
        idx += 1

    if capacity is not None:
        normalized = normalize_capacity_literal(capacity)
        if normalized:
            extra_where += f" AND {cap_expr} = ${idx}"
            params.append(normalized)
            idx += 1
        else:
            cap_pattern = re.sub(r"(?<=\d)(?=[A-Za-z])", lambda _: r"\s*", capacity)
            extra_where += f" AND (description ~ ${idx} OR part_number ~ ${idx})"
            params.append(f"(^|[^0-9A-Za-z]){cap_pattern}($|[^A-Za-z0-9])")
            idx += 1

    stock_cond = f"stock >= $1"
    if in_stock is True:
        stock_cond = f"stock > 0 AND stock >= $1"

    query = f"""
        WITH current_prices AS (
            SELECT
                part_number, source, chip_type, description, price_usd, stock,
                {cap_expr} AS capacity
            FROM prices
            WHERE price_usd > 0 AND {stock_cond}
              AND chip_type = ANY($2)
              {extra_where}
        ),
        hist_avg AS (
            SELECT
                part_number,
                ROUND(AVG(price_usd)::numeric, 2) AS avg_hist_price,
                COUNT(*) AS hist_points
            FROM history
            WHERE price_usd > 0
            GROUP BY part_number
            HAVING COUNT(*) >= 3
        )
        SELECT
            c.part_number, c.source, c.chip_type, c.capacity,
            c.price_usd, c.stock,
            h.avg_hist_price, h.hist_points,
            ROUND((1 - c.price_usd / h.avg_hist_price) * 100, 1) AS discount_pct
        FROM current_prices c
        JOIN hist_avg h ON c.part_number = h.part_number
        WHERE c.price_usd < h.avg_hist_price * 0.85
        ORDER BY discount_pct DESC
        LIMIT 50
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    result = []
    for r in rows:
        result.append(
            {
                "part_number": r["part_number"],
                "source": r["source"],
                "chip_type": r["chip_type"],
                "capacity": r["capacity"],
                "price_usd": float(r["price_usd"]) if r["price_usd"] is not None else None,
                "stock": r["stock"],
                "avg_hist_price": float(r["avg_hist_price"]) if r["avg_hist_price"] is not None else None,
                "hist_points": r["hist_points"],
                "discount_pct": float(r["discount_pct"]) if r["discount_pct"] is not None else None,
            }
        )
    return SafeJSONResponse(content=result)
