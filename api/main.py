import os
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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


def _safe_sort(sort: str, order: str) -> str:
    col = sort if sort in ALLOWED_SORT_COLUMNS else "price_usd"
    direction = order.lower() if order.lower() in ALLOWED_ORDERS else "asc"
    return f"{col} {direction}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/prices")
async def get_prices(
    type: Optional[str] = Query(None, description="Filter by chip_type"),
    brand: Optional[str] = Query(None, description="Filter by brand"),
    capacity: Optional[str] = Query(None, description="Filter by capacity"),
    source: Optional[str] = Query(None, description="Filter by source"),
    search: Optional[str] = Query(
        None, description="ILIKE search on part_number, description, brand"
    ),
    sort: str = Query("price_usd", description="Sort column: price_usd | price_rub | part_number"),
    order: str = Query("asc", description="Sort direction: asc | desc"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows (1-1000)"),
    offset: int = Query(0, ge=0, description="Row offset"),
):
    conditions = []
    params = []
    idx = 1

    if type is not None:
        conditions.append(f"chip_type = ${idx}")
        params.append(type)
        idx += 1

    if brand is not None:
        conditions.append(f"brand = ${idx}")
        params.append(brand)
        idx += 1

    if capacity is not None:
        conditions.append(f"capacity = ${idx}")
        params.append(capacity)
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

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order_clause = _safe_sort(sort, order)

    params.append(limit)
    params.append(offset)

    query = f"""
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
            url,
            fetched_at
        FROM prices
        {where_clause}
        ORDER BY {order_clause}
        LIMIT ${idx} OFFSET ${idx + 1}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return JSONResponse(content=[dict(r) for r in rows])


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
    return JSONResponse(content=[dict(r) for r in rows])


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
    return JSONResponse(content=[dict(r) for r in rows])


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
    return JSONResponse(content=[dict(r) for r in rows])


@app.get("/api/stats")
async def get_stats():
    query = """
        SELECT
            COUNT(*)                                     AS total,
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
    return JSONResponse(content=result)


@app.get("/api/history/{part_number}")
async def get_history(part_number: str):
    query = """
        SELECT
            fetched_at::date AS date,
            source,
            price_usd
        FROM prices
        WHERE part_number = $1
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
    return JSONResponse(content=result)


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
    return JSONResponse(content=result)


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
    return JSONResponse(content=[dict(r) for r in rows])
