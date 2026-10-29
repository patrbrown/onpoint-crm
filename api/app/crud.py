"""Small generic CRUD layer. Column names come only from Pydantic models (never from user input),
and RLS in the database enforces tenant isolation on every query."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException
from pydantic import BaseModel


def _record(r: asyncpg.Record | None) -> dict[str, Any] | None:
    if r is None:
        return None
    out = dict(r)
    out.pop("embedding", None)
    return out


async def list_rows(conn: asyncpg.Connection, table: str, tenant_id: UUID, *, where: dict[str, Any] | None = None,
                    order: str = "created_at desc", limit: int = 200, offset: int = 0) -> list[dict]:
    clauses, args = ["tenant_id = $1"], [tenant_id]
    for col, val in (where or {}).items():
        args.append(val)
        clauses.append(f"{col} = ${len(args)}")
    args += [limit, offset]
    sql = (f"select * from public.{table} where {' and '.join(clauses)} order by {order} "
           f"limit ${len(args) - 1} offset ${len(args)}")
    return [_record(r) for r in await conn.fetch(sql, *args)]


async def get_row(conn: asyncpg.Connection, table: str, tenant_id: UUID, row_id: UUID) -> dict:
    r = await conn.fetchrow(f"select * from public.{table} where tenant_id = $1 and id = $2", tenant_id, row_id)
    if r is None:
        raise HTTPException(404, f"{table[:-1]} not found")
    return _record(r)


async def insert_row(conn: asyncpg.Connection, table: str, tenant_id: UUID, data: BaseModel | dict) -> dict:
    values = data.model_dump(exclude_unset=True) if isinstance(data, BaseModel) else dict(data)
    values["tenant_id"] = tenant_id
    cols = list(values)
    placeholders = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    sql = f"insert into public.{table} ({', '.join(cols)}) values ({placeholders}) returning *"
    try:
        return _record(await conn.fetchrow(sql, *values.values()))
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(409, f"Duplicate: {exc.detail or exc}") from exc
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(422, f"Invalid reference: {exc.detail or exc}") from exc


async def update_row(conn: asyncpg.Connection, table: str, tenant_id: UUID, row_id: UUID, data: BaseModel) -> dict:
    values = data.model_dump(exclude_unset=True)
    if not values:
        return await get_row(conn, table, tenant_id, row_id)
    sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(values, start=3))
    sql = f"update public.{table} set {sets} where tenant_id = $1 and id = $2 returning *"
    r = await conn.fetchrow(sql, tenant_id, row_id, *values.values())
    if r is None:
        raise HTTPException(404, f"{table[:-1]} not found")
    return _record(r)


async def delete_row(conn: asyncpg.Connection, table: str, tenant_id: UUID, row_id: UUID) -> None:
    result = await conn.execute(f"delete from public.{table} where tenant_id = $1 and id = $2", tenant_id, row_id)
    if result.endswith(" 0"):
        raise HTTPException(404, f"{table[:-1]} not found")
