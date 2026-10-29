from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import close_pool, get_pool
from .errors import FriendlyErrors
from .agent import worker
from .routers import account, crm, inbox, job_descriptions, uploads


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    worker.start()
    yield
    worker.stop()
    await close_pool()


app = FastAPI(title="OnPoint CRM API", version="0.1.0", lifespan=lifespan)
app.add_middleware(FriendlyErrors)   # added first = inner, so CORS headers still wrap its responses
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
@app.exception_handler(asyncpg.InsufficientPrivilegeError)
async def rls_denied(request: Request, exc: asyncpg.InsufficientPrivilegeError) -> JSONResponse:
    # Row Level Security refused the write: the user is not a member of that tenant.
    return JSONResponse(status_code=403, content={"detail": "Not permitted for this tenant"})


@app.exception_handler(asyncpg.CheckViolationError)
async def check_failed(request: Request, exc: asyncpg.CheckViolationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": f"Invalid value: {exc.constraint_name}"})


app.include_router(account.router)
app.include_router(crm.router)
app.include_router(uploads.router)
app.include_router(inbox.router)
app.include_router(job_descriptions.router)


@app.get("/health")
async def health() -> dict:
    async with (await get_pool()).acquire() as conn:
        await conn.fetchval("select 1")
    return {"ok": True}
