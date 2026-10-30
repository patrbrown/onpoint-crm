"""API tests run against a real Postgres with the real migrations applied (Supabase auth stubbed),
so Row Level Security is exercised exactly as in production.

Requires TEST_DATABASE_URL pointing at a throwaway database, e.g.
  postgresql://postgres:postgres@localhost:5432/crm_test
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEST_DB = os.environ.get("TEST_DATABASE_URL")

TENANT_A = "10000000-0000-0000-0000-000000000001"
TENANT_B = "10000000-0000-0000-0000-000000000002"
USER_A = "00000000-0000-0000-0000-00000000000a"
USER_B = "00000000-0000-0000-0000-00000000000b"


def pytest_collection_modifyitems(config, items):
    if TEST_DB:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "api_client" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    files = [ROOT / "supabase/tests/supabase_stub.sql", *sorted((ROOT / "supabase/migrations").glob("*.sql"))]
    reset = "drop schema if exists public cascade; drop schema if exists auth cascade; create schema public;"
    subprocess.run(["psql", TEST_DB, "-q", "-v", "ON_ERROR_STOP=1", "-c", reset], check=True)
    for f in files:
        subprocess.run(["psql", TEST_DB, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(f)], check=True,
                       capture_output=True)
    seed = f"""
      insert into auth.users (id, email) values ('{USER_A}', 'patty@onpoint.test'), ('{USER_B}', 'b@other.test');
      update public.profiles set is_platform_admin = false;
      insert into public.tenants (id, name, portal_slug) values ('{TENANT_A}', 'OnPoint Personnel', 'onpoint'),
                                                                ('{TENANT_B}', 'Other Agency', 'other');
      insert into public.memberships values ('{TENANT_A}', '{USER_A}', 'owner'), ('{TENANT_B}', '{USER_B}', 'owner');
      grant all on all tables in schema public to authenticated;
    """
    subprocess.run(["psql", TEST_DB, "-q", "-v", "ON_ERROR_STOP=1", "-c", seed], check=True)
    return TEST_DB


@pytest.fixture
def api_client(database, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("DEV_USER_ID", USER_A)
    monkeypatch.setenv("EMAIL_WORKER_ENABLED", "false")
    monkeypatch.setenv("BULK_IMPORT_CONCURRENCY", "1")   # deterministic order for the fake AI
    from app.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    db._pool = None
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
