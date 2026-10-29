import json

from conftest import TENANT_A, TENANT_B

from app.llm import FakeProvider
from app.routers import uploads

A = f"/tenants/{TENANT_A}"


def test_me_lists_only_my_tenants(api_client):
    body = api_client.get("/me").json()
    assert body["profile"]["email"] == "patty@onpoint.test"
    assert [t["portal_slug"] for t in body["tenants"]] == ["onpoint"]
    assert body["tenants"][0]["role"] == "owner"


def test_settings_toggle(api_client):
    c = api_client
    assert c.get(f"{A}/settings").json()["inbox_mode"] == "review"
    out = c.patch(f"{A}/settings", json={"ai_scoring_enabled": True, "inbox_mode": "auto",
                                           "auto_approve_threshold": 0.95}).json()
    assert out["ai_scoring_enabled"] and out["inbox_mode"] == "auto"
    assert c.patch(f"{A}/settings", json={"inbox_mode": "yolo"}).status_code == 422
    assert c.get(f"/tenants/{TENANT_B}/settings").status_code == 404   # hidden by RLS
    c.patch(f"{A}/settings", json={"inbox_mode": "review", "ai_scoring_enabled": False})


def test_documents_list_and_download(api_client):
    c = api_client
    fake = FakeProvider([json.dumps({"first_name": "Doc", "last_name": "Test", "email": "doc@example.com"})])
    c.app.dependency_overrides[uploads.llm_dep] = lambda: fake
    cand = c.post(f"{A}/candidates/upload", files={"file": ("doc.txt", b"Doc Test resume body")}).json()["candidate"]
    docs = c.get(f"{A}/candidates/{cand['id']}/documents").json()
    assert docs[0]["file_name"] == "doc.txt" and "resume body" in docs[0]["extracted_text"]
    r = c.get(f"{A}/documents/{docs[0]['id']}/download")
    assert r.status_code == 200 and r.content == b"Doc Test resume body"
    assert c.get(f"/tenants/{TENANT_B}/documents/{docs[0]['id']}/download").status_code == 404
