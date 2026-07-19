"""Async connection pool shared by the routers."""
from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import database_url

_pool: AsyncConnectionPool | None = None


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            database_url(), min_size=1, max_size=10, open=False,
            kwargs={"row_factory": dict_row},
        )
        await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("pool not open")
    return _pool


async def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    async with pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


async def fetch_one(sql: str, params: tuple = ()) -> dict | None:
    async with pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def execute(sql: str, params: tuple = ()) -> None:
    async with pool().connection() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
