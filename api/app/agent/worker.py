"""Runs the email agent on a schedule inside the API process (every minute it checks which connected
mailboxes are due, based on each workspace's 'check email every N minutes' setting)."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import get_settings
from ..db import service_tx
from ..llm.tenant import llm_for_task
from ..services.graph import GraphAuthError, GraphMailbox
from ..services.storage import get_storage
from .email_agent import ScanResult, scan_account

log = logging.getLogger("email_worker")
_last_run: dict[UUID, float] = {}
_locks: dict[UUID, asyncio.Lock] = {}
_scheduler: AsyncIOScheduler | None = None


async def scan_now(account_id: UUID) -> ScanResult:
    lock = _locks.setdefault(account_id, asyncio.Lock())
    if lock.locked():
        raise RuntimeError("A scan of this mailbox is already running")
    async with lock:
        _last_run[account_id] = time.monotonic()
        async with service_tx() as conn:
            account = await conn.fetchrow("select * from public.mail_accounts where id = $1", account_id)
            llm = await llm_for_task(conn, account["tenant_id"], "email_extraction")
            triage_llm = await llm_for_task(conn, account["tenant_id"], "email_triage")
        mailbox = GraphMailbox(str(account_id))
        # Per-message transactions live inside scan_account; this outer connection is only for the scan itself.
        from ..db import get_pool

        async with (await get_pool()).acquire() as conn:
            try:
                return await scan_account(conn, get_storage(), llm, mailbox, account, triage_llm=triage_llm)
            except GraphAuthError as exc:
                await conn.execute("update public.mail_accounts set last_error = $2 where id = $1", account_id, str(exc))
                raise


async def tick() -> None:
    async with service_tx() as conn:
        due = await conn.fetch(
            """select a.id, s.email_scan_minutes from public.mail_accounts a
               join public.tenant_settings s on s.tenant_id = a.tenant_id
               join public.tenants t on t.id = a.tenant_id and t.status = 'active'
               where a.is_enabled and s.email_agent_enabled""")
    now = time.monotonic()
    for row in due:
        if now - _last_run.get(row["id"], 0) < row["email_scan_minutes"] * 60:
            continue
        try:
            r = await scan_now(row["id"])
            if r.new:
                log.info("mailbox %s: %s new, %s queued, %s auto-saved, %s ignored, %s errors",
                         row["id"], r.new, r.queued, r.auto_approved, r.ignored, r.errors)
        except Exception as exc:  # noqa: BLE001 — keep the scheduler alive
            log.warning("mailbox %s scan failed: %s", row["id"], exc)


def start() -> None:
    global _scheduler
    s = get_settings()
    if not s.email_worker_enabled or not (s.ms_client_id and s.ms_tenant_id):
        log.info("email worker not started (disabled or Microsoft IDs missing)")
        return
    _scheduler = AsyncIOScheduler()
    first = datetime.now(timezone.utc) + timedelta(seconds=15)   # first check shortly after start-up
    _scheduler.add_job(tick, "interval", seconds=60, max_instances=1, coalesce=True, next_run_time=first)
    _scheduler.start()


def stop() -> None:
    if _scheduler:
        _scheduler.shutdown(wait=False)
