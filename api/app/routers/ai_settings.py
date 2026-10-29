"""Settings → AI: what's configured, test a model, and Jev's control panel (status, test console, recent calls)."""
import time
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from ..agent.email_agent import ACTIONABLE, feedback_examples
from ..auth import CurrentUser, get_current_user
from ..config import get_settings
from ..db import user_tx
from ..errors import explain
from ..llm import get_provider
from ..llm.tenant import TASKS, build
from ..schemas import _Base
from ..services import jev

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["ai settings"])

MODEL_SUGGESTIONS = {
    "anthropic": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
    "openrouter": ["qwen/qwen-2.5-72b-instruct", "meta-llama/llama-3.3-70b-instruct", "mistralai/mistral-small-3.2-24b-instruct",
                   "deepseek/deepseek-chat"],
    "openai_compatible": ["llama3.3:70b", "qwen2.5:72b", "qwen2.5:14b", "llama3.1:8b"],
}


async def _member(conn, tenant_id: UUID) -> None:
    if not await conn.fetchval("select public.is_member($1)", tenant_id):
        raise HTTPException(403, "Not a member of this workspace")


@router.get("/ai/status")
async def status(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    s = get_settings()
    async with user_tx(user.id) as conn:
        await _member(conn, tenant_id)
        is_admin = await conn.fetchval("select public.is_tenant_admin($1)", tenant_id)
    return {
        "can_edit": bool(is_admin),
        "keys": {"anthropic": bool(s.anthropic_api_key), "openrouter": bool(s.openrouter_api_key),
                 "typesafe": bool(s.typesafe_api_key)},
        "local_base_url": s.openai_compatible_base_url,
        "tasks": TASKS,
        "suggestions": MODEL_SUGGESTIONS,
        "jev_defaults": jev.DEFAULT_CONFIG,
    }


class ModelTest(_Base):
    provider: Literal["anthropic", "openrouter", "openai_compatible"]
    model: str = Field(min_length=1)
    base_url: str | None = None


@router.post("/ai/test-model")
async def test_model(tenant_id: UUID, body: ModelTest, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Ask the model for a tiny JSON answer: proves the key, address and model name work, and how fast it is."""
    async with user_tx(user.id) as conn:
        await _member(conn, tenant_id)
    llm = build({"provider": body.provider, "model": body.model, "base_url": body.base_url})
    started = time.monotonic()
    try:
        data, _ = await llm.complete_json("You check that a connection works.",
                                          'Reply with {"ok": true, "candidate_first_name": "<first name>"} for: '
                                          '"Resume of Priya Shah, Epic Willow analyst"', 100)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": explain(exc)[1], "seconds": round(time.monotonic() - started, 1)}
    return {"ok": bool(data.get("ok")), "reads_json": True, "sample": data,
            "seconds": round(time.monotonic() - started, 1)}


@router.get("/jev/models")
async def jev_models(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        await _member(conn, tenant_id)
    try:
        return {"ok": True, "models": await jev.JevClient().models()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300], "models": []}


class JevTest(_Base):
    subject: str = ""
    sender: str = ""
    body: str = Field(min_length=1, max_length=60000)
    model: str | None = None
    config: dict[str, Any] | None = None    # unsaved edits from the panel, to try before saving


@router.post("/jev/test")
async def jev_test(tenant_id: UUID, body: JevTest, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Run Jev on a pasted email with the panel's current (possibly unsaved) settings."""
    async with user_tx(user.id) as conn:
        await _member(conn, tenant_id)
        st = await conn.fetchrow("select * from public.tenant_settings where tenant_id = $1", tenant_id)
        examples = await feedback_examples(conn, tenant_id, "classification")
    cfg = jev.merged_config({**(st.get("jev_config") or {}), **(body.config or {})})
    corrections = [f"{e['summary']}, but it was actually {e['correct']}" for e in examples]
    request = jev.build_request(cfg, body.model or st.get("jev_model") or "jev-latest", body.subject, body.sender,
                                body.body, [], corrections)
    started = time.monotonic()
    try:
        t = await jev.JevClient().classify(request)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}
    floor = float(st.get("review_below_confidence") or 0)
    unsure = t.classification not in ACTIONABLE and t.confidence < floor
    return {"ok": True, "classification": t.classification, "confidence": t.confidence, "probabilities": t.probabilities,
            "model": t.model, "seconds": round(time.monotonic() - started, 1),
            "would_review_anyway": unsure and max(t.probabilities.get(c, 0) for c in ACTIONABLE) >= 0.15}


@router.get("/jev/recent")
async def jev_recent(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """The latest emails and how they were sorted (with Jev's probabilities), for tuning."""
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select id, subject, from_address, received_at, classification, confidence, triage
               from public.email_messages where tenant_id = $1 and triage is not null
               order by received_at desc limit 25""", tenant_id)
    return [dict(r) for r in rows]
