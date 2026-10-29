import httpx
from conftest import TENANT_A

from app.llm import FakeProvider
from app.routers import uploads
from app.services.storage import get_storage


class BrokenStorage:
    async def put(self, path, data, content_type=None):
        req = httpx.Request("POST", "https://x.supabase.co/storage/v1/object/documents/" + path)
        raise httpx.HTTPStatusError("bad", request=req,
                                    response=httpx.Response(400, request=req, text='{"error":"Bucket not found"}'))


def test_unexpected_errors_reach_the_browser_with_a_reason(api_client):
    c = api_client
    c.app.dependency_overrides[uploads.llm_dep] = lambda: FakeProvider(['{"first_name": "Err", "email": "err@example.com"}'])
    c.app.dependency_overrides[get_storage] = lambda: BrokenStorage()
    r = c.post(f"/tenants/{TENANT_A}/candidates/upload", files={"file": ("e.txt", b"Err")},
               headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 502
    assert "bucket" in r.json()["detail"].lower()
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"   # browser can read it


def test_ai_errors_are_explained():
    from app.errors import explain

    class AuthenticationError(Exception):
        pass
    AuthenticationError.__module__ = "anthropic"
    assert "API key" in explain(AuthenticationError("401"))[1]
