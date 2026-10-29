"""Which model does which job, per workspace (Settings → AI models).

Tasks:
  default           — anything without its own choice
  email_triage      — deciding what kind of email it is (when not using Jev)
  email_extraction  — reading job reqs, resumes and interview feedback from email
  resume_parsing    — resumes uploaded by hand or in bulk

Each task's route: {"provider": "anthropic"|"openrouter"|"openai_compatible", "model": str,
"base_url": str|null, "fallback": bool}. A missing or empty route uses the default.
"""
from uuid import UUID

from . import LLMProvider, get_provider
from .providers import FallbackProvider

TASKS = {
    "default": "Default model",
    "email_triage": "Sorting emails (when not using Jev)",
    "email_extraction": "Reading job reqs, resumes and feedback from email",
    "resume_parsing": "Reading uploaded resumes",
}


def _norm(r: dict) -> dict:
    return {"provider": r["provider"], "model": r["model"], "base_url": r.get("base_url") or None,
            "fallback": bool(r.get("fallback"))}


def route_for(settings, task: str) -> dict:
    """The task's own choice if it has one, else the workspace default, else the .env default."""
    if settings is None:
        return {}
    routes = settings.get("model_routes") or {}
    base = {"provider": settings.get("llm_provider"), "model": settings.get("llm_model"),
            "base_url": settings.get("llm_base_url"), "fallback": False}
    d = routes.get("default") or {}
    if d.get("provider") and d.get("model"):
        base = _norm(d)
    if task == "default":
        return base
    r = routes.get(task) or {}
    return _norm(r) if r.get("provider") and r.get("model") else base


def build(route: dict) -> LLMProvider:
    primary = get_provider(route.get("provider"), route.get("model"), route.get("base_url"))
    if route.get("fallback") and route.get("provider") != "anthropic":
        return FallbackProvider(primary, get_provider("anthropic"))
    return primary


async def _settings(conn, tenant_id: UUID):
    return await conn.fetchrow("select * from public.tenant_settings where tenant_id = $1", tenant_id)


async def llm_for_task(conn, tenant_id: UUID, task: str) -> LLMProvider:
    st = await _settings(conn, tenant_id)
    return build(route_for(st, task)) if st else get_provider()


async def llm_for_tenant(conn, tenant_id: UUID) -> LLMProvider:
    """The workspace's default model."""
    return await llm_for_task(conn, tenant_id, "default")
