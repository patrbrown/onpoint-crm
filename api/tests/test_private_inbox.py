"""The inbox is private: only the person who connected a mailbox, and people they share it with, see its email."""
import subprocess
from contextlib import contextmanager

from conftest import TENANT_A, USER_A

A = f"/tenants/{TENANT_A}"
USER_C = "00000000-0000-0000-0000-00000000000c"   # a second recruiter at OnPoint
ADMIN_D = "00000000-0000-0000-0000-00000000000d"  # an admin at OnPoint
PLATFORM_E = "00000000-0000-0000-0000-00000000000e"  # platform owner, not a member of OnPoint


def sql(db, q):
    return subprocess.run(["psql", db, "-Atq", "-v", "ON_ERROR_STOP=1", "-c", q], check=True,
                          capture_output=True, text=True).stdout.strip()


@contextmanager
def as_user(monkeypatch, user_id):
    from app.config import get_settings
    monkeypatch.setenv("DEV_USER_ID", user_id)
    get_settings.cache_clear()
    try:
        yield
    finally:
        monkeypatch.setenv("DEV_USER_ID", USER_A)
        get_settings.cache_clear()


def test_inbox_is_private_to_its_owner_and_people_they_share_with(api_client, database, monkeypatch):
    c = api_client
    sql(database, f"""
        insert into auth.users (id, email) values ('{USER_C}', 'cam@onpoint.test'), ('{ADMIN_D}', 'dee@onpoint.test'),
                                                  ('{PLATFORM_E}', 'platform@onpoint.test') on conflict do nothing;
        insert into public.memberships values ('{TENANT_A}', '{USER_C}', 'recruiter'), ('{TENANT_A}', '{ADMIN_D}', 'admin')
            on conflict do nothing;
        update public.profiles set is_platform_admin = true where id = '{PLATFORM_E}';
        delete from public.mail_accounts where tenant_id = '{TENANT_A}';
        insert into public.mail_accounts (id, tenant_id, user_id, mailbox_address)
            values ('20000000-0000-0000-0000-000000000001', '{TENANT_A}', '{USER_A}', 'patty@onpoint.example');
        insert into public.email_messages (id, tenant_id, mail_account_id, provider_message_id, subject, from_address,
                                           received_at)
            values ('30000000-0000-0000-0000-000000000001', '{TENANT_A}', '20000000-0000-0000-0000-000000000001',
                    'msg-private', 'Confidential: offer details', 'client@example.com', now());
        insert into public.inbox_items (tenant_id, email_id, item_type, extracted)
            values ('{TENANT_A}', '30000000-0000-0000-0000-000000000001', 'job_requisition', '{{"title": "Secret role"}}');
    """)
    acct = "20000000-0000-0000-0000-000000000001"

    # Patty (who connected it) sees everything.
    me = next(t for t in c.get("/me").json()["tenants"] if t["id"] == TENANT_A)
    assert me["inbox_access"] is True
    assert any(i["extracted"]["title"] == "Secret role" for i in c.get(f"{A}/inbox").json()["items"])

    # Another recruiter: no Inbox tab, no items, no emails, can't scan, can't see the mailbox at all.
    with as_user(monkeypatch, USER_C):
        assert next(t for t in c.get("/me").json()["tenants"] if t["id"] == TENANT_A)["inbox_access"] is False
        assert c.get(f"{A}/inbox").json()["items"] == []
        assert c.get(f"{A}/mail").json()["accounts"] == []
        assert c.post(f"{A}/mail/accounts/{acct}/scan").status_code == 404
        assert c.patch(f"{A}/mail/accounts/{acct}", params={"enabled": False}).status_code == 403
        assert c.post(f"{A}/mail/accounts/{acct}/access", json={"user_id": USER_C}).status_code == 403  # can't let themselves in
        assert c.get(f"{A}/jev/recent").json() == []

    # A workspace admin can see that the mailbox exists, but not its email.
    with as_user(monkeypatch, ADMIN_D):
        accounts = c.get(f"{A}/mail").json()["accounts"]
        assert [a["mailbox_address"] for a in accounts] == ["patty@onpoint.example"] and accounts[0]["can_read"] is False
        assert c.get(f"{A}/inbox").json()["items"] == []
        assert c.post(f"{A}/mail/accounts/{acct}/access", json={"user_id": ADMIN_D}).status_code == 403

    # The platform owner (cross-workspace admin) doesn't get anyone's email either.
    with as_user(monkeypatch, PLATFORM_E):
        assert c.get(f"{A}/inbox").json()["items"] == []

    # Patty shares with the recruiter: they now see the inbox, but can't change who else sees it.
    people = c.get(f"{A}/mail/people").json()
    assert {p["user_id"] for p in people} >= {USER_C, ADMIN_D}
    assert c.post(f"{A}/mail/accounts/{acct}/access", json={"user_id": USER_C}).status_code == 200
    assert [s["user_id"] for s in c.get(f"{A}/mail").json()["accounts"][0]["shared_with"]] == [USER_C]
    with as_user(monkeypatch, USER_C):
        assert next(t for t in c.get("/me").json()["tenants"] if t["id"] == TENANT_A)["inbox_access"] is True
        assert any(i["extracted"]["title"] == "Secret role" for i in c.get(f"{A}/inbox").json()["items"])
        assert c.post(f"{A}/mail/accounts/{acct}/access", json={"user_id": ADMIN_D}).status_code == 403
        assert c.patch(f"{A}/mail/accounts/{acct}", params={"enabled": False}).status_code == 403

    # Sharing only with people in the workspace; and access can be taken away again.
    assert c.post(f"{A}/mail/accounts/{acct}/access",
                  json={"user_id": "00000000-0000-0000-0000-00000000000b"}).status_code == 422
    assert c.delete(f"{A}/mail/accounts/{acct}/access/{USER_C}").status_code == 200
    with as_user(monkeypatch, USER_C):
        assert c.get(f"{A}/inbox").json()["items"] == []

    # Even straight database queries as the recruiter return nothing (Row Level Security, not just the API).
    rows = sql(database, f"""begin; set local role authenticated; set local request.jwt.claim.sub = '{USER_C}';
        select count(*) from public.email_messages; select count(*) from public.inbox_items where email_id is not null;
        commit;""")
    assert rows.split() == ["0", "0"]
