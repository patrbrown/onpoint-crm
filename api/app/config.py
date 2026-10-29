from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database: the Supabase Postgres connection string (Settings → Database → Connection string).
    database_url: str = "postgresql://postgres:postgres@localhost:5432/postgres"

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    storage_bucket: str = "documents"
    storage_backend: str = "supabase"  # "supabase" or "local" (tests / offline)
    local_storage_dir: str = "./.storage"

    # Local development: skip JWT checks and act as this user. Never set in the cloud.
    dev_user_id: str | None = None

    # LLM defaults (a tenant can override in tenant_settings)
    llm_provider: str = "anthropic"            # "anthropic" | "openai_compatible"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str = ""
    openai_compatible_base_url: str = "http://localhost:11434/v1"  # e.g. Ollama
    openai_compatible_api_key: str = "not-needed"
    openrouter_api_key: str = ""

    # TypeSafe Jev (email triage). Keys live here, never in the database.
    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://api.typesafe.ai/v1"

    # Microsoft Graph (email agent)
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_token_cache_path: str = "./.secrets/msal_cache.json"
    email_worker_enabled: bool = True   # set false in tests or to pause the agent

    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
