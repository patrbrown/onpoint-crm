"""Hosting safeguards: Outlook sign-ins survive restarts (encrypted in the database); dev mode can't run in production."""
import subprocess

import pytest
from cryptography.fernet import Fernet


def test_outlook_signin_survives_a_restart(api_client, database, tmp_path, monkeypatch):
    from app.config import get_settings
    from app.services import graph
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MS_TOKEN_CACHE_PATH", str(tmp_path / "secrets" / "cache.json"))
    get_settings.cache_clear()
    f = tmp_path / "secrets" / "msal_acct-1.json"
    f.parent.mkdir()
    f.write_text('{"RefreshToken": {"x": {"secret": "very-secret-refresh-token"}}}')

    api_client.portal.call(graph.backup_cache, "acct-1")
    stored = subprocess.run(["psql", database, "-Atc", "select ciphertext from public.mail_tokens where cache_key = 'acct-1'"],
                            capture_output=True, text=True).stdout
    assert stored and "very-secret" not in stored          # encrypted at rest

    f.unlink()                                                # the hosted server restarted: files are gone
    api_client.portal.call(graph.restore_cache, "acct-1")
    assert "very-secret-refresh-token" in f.read_text()
    get_settings.cache_clear()


def test_production_refuses_dev_login(monkeypatch, database):
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEV_USER_ID", "00000000-0000-0000-0000-00000000000a")
    monkeypatch.setenv("EMAIL_WORKER_ENABLED", "false")
    monkeypatch.setenv("PORTAL_WORKER_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app
    db._pool = None
    with pytest.raises(RuntimeError, match="DEV_USER_ID"):
        with TestClient(app):
            pass
    get_settings.cache_clear()
    db._pool = None
