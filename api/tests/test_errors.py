import httpx
from conftest import TENANT_A

from app.llm import FakeProvider
from app.routers import uploads
from app.services.storage import get_storage


class BrokenStorage:
    async def put(self, path, data, content_type=None):
        from app.services.storage import StorageError
        raise StorageError(400, '{"statusCode":"404","error":"Bucket not found","message":"Bucket not found"}')


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


def test_new_style_keys_are_not_sent_as_bearer_tokens():
    from app.services.storage import _auth_headers
    assert _auth_headers("sb_secret_abc") == {"apikey": "sb_secret_abc"}
    assert _auth_headers("eyJhbGciOi.x.y")["Authorization"] == "Bearer eyJhbGciOi.x.y"
