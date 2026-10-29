"""Database access.

Every request runs inside a transaction that adopts the caller's identity the same way Supabase's
own API does (`role authenticated` + JWT `sub`). That means Row Level Security in the database, not
application code, decides what each user can see. A bug in a query cannot leak another agency's data.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

import asyncpg

from .config import get_settings

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            get_settings().database_url, min_size=1, max_size=10, init=_init_conn,
            statement_cache_size=0,  # required for Supabase's transaction pooler
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def user_tx(user_id: UUID | str) -> AsyncIterator[asyncpg.Connection]:
    """A transaction in which RLS applies as `user_id`."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("set local role authenticated")
            await conn.execute("select set_config('request.jwt.claim.sub', $1, true)", str(user_id))
            await conn.execute(
                "select set_config('request.jwt.claims', $1, true)",
                json.dumps({"sub": str(user_id), "role": "authenticated"}),
            )
            yield conn


@asynccontextmanager
async def service_tx() -> AsyncIterator[asyncpg.Connection]:
    """A transaction that bypasses RLS. Only for the background agent and the portal intake,
    and every query must filter by tenant_id explicitly."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
