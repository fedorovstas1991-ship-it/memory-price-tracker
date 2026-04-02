import os
import logging

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql://mpt:mpt_secure_2026@127.0.0.1:5432/memoryprices"

_PRICES_COLUMNS = [
    "chip_type",
    "part_number",
    "description",
    "brand",
    "capacity",
    "source",
    "distributor",
    "price_usd",
    "price_rub",
    "price_cny",
    "moq",
    "stock",
    "url",
]

_HISTORY_COLUMNS = [
    "part_number",
    "source",
    "price_usd",
]


async def get_pool() -> asyncpg.Pool:
    """Create and return an asyncpg connection pool.

    Reads DATABASE_URL from environment (defaults to local dev DSN).
    """
    dsn = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
    logger.info("DB pool created: %s", dsn)
    return pool


def _entry_to_prices_row(entry: dict) -> tuple:
    return (
        entry.get("chip_type") or "",
        entry.get("part_number") or "",
        entry.get("description") or "",
        entry.get("brand") or "",
        entry.get("capacity") or "",
        entry.get("source") or "",
        entry.get("distributor") or "",
        entry.get("price_usd"),
        entry.get("price_rub"),
        entry.get("price_cny"),
        entry.get("moq"),
        entry.get("stock"),
        entry.get("url") or "",
    )


def _entry_to_history_row(entry: dict) -> tuple:
    return (
        entry.get("part_number") or "",
        entry.get("source") or "",
        entry.get("price_usd"),
    )


async def write_prices(pool: asyncpg.Pool, entries: list[dict]) -> None:
    """TRUNCATE prices table then batch-insert all entries.

    Uses copy_records_to_table for maximum throughput.
    """
    if not entries:
        logger.warning("write_prices called with empty list — skipping")
        return

    rows = [_entry_to_prices_row(e) for e in entries]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE prices")
            await conn.copy_records_to_table(
                "prices",
                records=rows,
                columns=_PRICES_COLUMNS,
            )

    logger.info("write_prices: wrote %d rows to prices", len(rows))


async def append_history(pool: asyncpg.Pool, entries: list[dict]) -> None:
    """Append-only insert into history (part_number, source, price_usd).

    Uses copy_records_to_table for maximum throughput.
    """
    if not entries:
        return

    rows = [_entry_to_history_row(e) for e in entries]

    async with pool.acquire() as conn:
        await conn.copy_records_to_table(
            "history",
            records=rows,
            columns=_HISTORY_COLUMNS,
        )

    logger.info("append_history: inserted %d rows into history", len(rows))
