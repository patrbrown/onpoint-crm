"""Inviting people: creates their login (via Supabase Auth, faked here), gives them access, roles, removal."""
import subprocess
import uuid

from conftest import TENANT_A, USER_A

from app.services.auth_admin import AuthAdminError, get_auth_admin

A = f"/tenants/{TENANT_A}"


def sql(db, q):
    return subprocess.run(["psql", db, "-Atq", "-v", "ON_ERROR_STOP=1", "-c", q], check=True,
                          capture_output=True, text=True).stdout.strip()


class FakeAuth:
    """Behaves like Supabase: creating a login adds an auth.users row (which makes a profile)."""
    def __init__(self, db, smtp_ok=False):
        self.db, self.smtp_ok, self.sent = db, smtp_ok, []

    def _user(self, email, name):
        existing = sql(self.db, f"select id from auth.users where lower(email) = lower('{email}')")
        if existing:
            return existing
        uid = str(uuid.uuid4())
        meta = f'{{"full_name": "{name}"}}' if name else "{}"
        sql(self.db, f"insert into auth.users (id, email, raw_user_meta_data) values ('{uid}', '{email}', '{meta}')")
        return uid

    async def invite_link(self, email, full_name, redirect_to):
        assert redirect_to.endswith("/welcome")
        return self._user(email, full_name), f"https://example.supabase.co/auth/v1/verify?token=t-{email}&redirect_to={redirect_to}"

    async def send_invite(self, email, full_name, redirect_to):
        if not self.smtp_ok:
            raise AuthAdminError(400, "Email address not authorized")
        self.sent.append(email)
        return self._user(email, full_name)


def test_invite_roles_and_removal(api_client, database):
    c = api_client
    fake = FakeAuth(database)
    c.app.dependency_overrides[get_auth_admin] = lambda: fake

    r = c.post(f"{A}/team/invites", json={"email": "Riley.Chen@Example.com", "full_name": "Riley Chen", "role": "recruiter"})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["email"] == "riley.chen@example.com" and inv["link"].startswith("https://") and inv["emailed"] is False
    members = {m["email"]: m for m in c.get(f"{A}/team/members").json()}
    riley = members["riley.chen@example.com"]
    assert riley["role"] == "recruiter" and riley["name"] == "Riley Chen" and riley["last_sign_in_at"] is None
    # They're on the Users list (taggable on uploads) and can now be given access to a mailbox.
    assert any(t["full_name"] == "Riley Chen" and t["has_login"] for t in c.get(f"{A}/team").json())
    assert any(p["user_id"] == riley["user_id"] for p in c.get(f"{A}/mail/people").json())

    # Inviting the same person again is refused; a fresh link is available instead.
    assert c.post(f"{A}/team/invites", json={"email": "riley.chen@example.com"}).status_code == 409
    assert c.post(f"{A}/team/members/{riley['user_id']}/link").json()["link"].startswith("https://")

    # "Email it for me" without an email service in Supabase falls back to a link, with a note.
    r2 = c.post(f"{A}/team/invites", json={"email": "sam.k@example.com", "send_email": True}).json()
    assert r2["emailed"] is False and r2["link"] and "couldn’t send" in r2["note"]
    fake.smtp_ok = True
    r3 = c.post(f"{A}/team/invites", json={"email": "ali.m@example.com", "send_email": True, "role": "admin"}).json()
    assert r3["emailed"] is True and r3["link"] is None and fake.sent == ["ali.m@example.com"]

    # Someone already known from the Users list gets linked, not duplicated.
    c.post(f"{A}/team", json={"full_name": "Jordan Price", "email": "jordan.p@example.com"})
    c.post(f"{A}/team/invites", json={"email": "jordan.p@example.com"})
    assert len([t for t in c.get(f"{A}/team").json() if t["email"] == "jordan.p@example.com"]) == 1

    # Roles: change, and the last owner is protected.
    assert c.patch(f"{A}/team/members/{riley['user_id']}", json={"role": "admin"}).json()["role"] == "admin"
    assert c.patch(f"{A}/team/members/{USER_A}", json={"role": "recruiter"}).status_code == 422
    assert c.delete(f"{A}/team/members/{USER_A}").status_code == 422          # can't remove yourself

    # Removing access: gone from members, mailbox shares revoked, name kept (inactive) on the Users list.
    acct = sql(database, f"""insert into public.mail_accounts (tenant_id, user_id, mailbox_address)
        values ('{TENANT_A}', '{USER_A}', 'share-test@onpoint.example') returning id""")
    c.post(f"{A}/mail/accounts/{acct}/access", json={"user_id": riley["user_id"]})
    assert c.delete(f"{A}/team/members/{riley['user_id']}").status_code == 200
    assert "riley.chen@example.com" not in {m["email"] for m in c.get(f"{A}/team/members").json()}
    assert sql(database, f"select count(*) from public.mailbox_access where user_id = '{riley['user_id']}'") == "0"
    assert any(t["full_name"] == "Riley Chen" and not t["is_active"]
               for t in c.get(f"{A}/team", params={"include_inactive": True}).json())
    sql(database, f"delete from public.mail_accounts where id = '{acct}'")


def test_only_admins_invite(api_client, database, monkeypatch):
    c = api_client
    rec = "00000000-0000-0000-0000-0000000000f1"
    sql(database, f"""insert into auth.users (id, email) values ('{rec}', 'rec@onpoint.test') on conflict do nothing;
        insert into public.memberships values ('{TENANT_A}', '{rec}', 'recruiter') on conflict do nothing;""")
    c.app.dependency_overrides[get_auth_admin] = lambda: FakeAuth(database)
    from app.config import get_settings
    monkeypatch.setenv("DEV_USER_ID", rec); get_settings.cache_clear()
    try:
        assert c.post(f"{A}/team/invites", json={"email": "x@example.com"}).status_code == 403
        assert c.delete(f"{A}/team/members/{USER_A}").status_code == 403
        assert len(c.get(f"{A}/team/members").json()) >= 2       # can still see who's in the workspace
    finally:
        monkeypatch.setenv("DEV_USER_ID", USER_A); get_settings.cache_clear()
