"""File storage behind one interface: Supabase Storage in normal use, local disk for tests/offline."""
from __future__ import annotations

from pathlib import Path

import httpx

from ..config import get_settings


class Storage:
    async def put(self, path: str, data: bytes, content_type: str | None = None) -> str: ...
    async def get(self, path: str) -> bytes: ...


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root)

    async def put(self, path: str, data: bytes, content_type: str | None = None) -> str:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return path

    async def get(self, path: str) -> bytes:
        return (self.root / path).read_bytes()


class StorageError(Exception):
    """Supabase Storage refused a request. `body` is Supabase's own explanation."""

    def __init__(self, status: int, body: str):
        self.status, self.body = status, body
        super().__init__(f"Supabase Storage error {status}: {body[:300]}")


def _auth_headers(key: str) -> dict[str, str]:
    """New-style Supabase keys (sb_secret_…) are not JWTs and go only in the `apikey` header; sending one as a
    Bearer token makes Storage reply 400. Legacy service_role keys are JWTs and need both headers."""
    if key.startswith("sb_"):
        return {"apikey": key}
    return {"apikey": key, "Authorization": f"Bearer {key}"}


class SupabaseStorage(Storage):
    def __init__(self, url: str, key: str, bucket: str):
        if not url or not key:
            raise StorageError(0, "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing from .env")
        self.base = f"{url.rstrip('/')}/storage/v1/object/{bucket}"
        self.headers = _auth_headers(key)

    @staticmethod
    def _check(r: httpx.Response) -> None:
        if r.status_code >= 400:
            raise StorageError(r.status_code, r.text)

    async def put(self, path: str, data: bytes, content_type: str | None = None) -> str:
        headers = {**self.headers, "x-upsert": "true", "Content-Type": content_type or "application/octet-stream"}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.base}/{path}", content=data, headers=headers)
            self._check(r)
        return path

    async def get(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{self.base}/{path}", headers=self.headers)
            self._check(r)
            return r.content


def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "local":
        return LocalStorage(s.local_storage_dir)
    return SupabaseStorage(s.supabase_url, s.supabase_service_role_key, s.storage_bucket)
