from uuid import UUID

from . import LLMProvider, get_provider


async def llm_for_tenant(conn, tenant_id: UUID) -> LLMProvider:
    """The LLM this workspace has chosen in Settings (Claude or a local model)."""
    st = await conn.fetchrow(
        "select llm_provider, llm_model, llm_base_url from public.tenant_settings where tenant_id = $1", tenant_id)
    return get_provider(st["llm_provider"], st["llm_model"], st["llm_base_url"]) if st else get_provider()
