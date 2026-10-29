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


class SupabaseStorage(Storage):
    def __init__(self, url: str, key: str, bucket: str):
        self.base = f"{url.rstrip('/')}/storage/v1/object/{bucket}"
        self.headers = {"Authorization": f"Bearer {key}", "apikey": key}

    async def put(self, path: str, data: bytes, content_type: str | None = None) -> str:
        headers = {**self.headers, "x-upsert": "true", "Content-Type": content_type or "application/octet-stream"}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.base}/{path}", content=data, headers=headers)
            r.raise_for_status()
        return path

    async def get(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{self.base}/{path}", headers=self.headers)
            r.raise_for_status()
            return r.content


def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "local":
        return LocalStorage(s.local_storage_dir)
    return SupabaseStorage(s.supabase_url, s.supabase_service_role_key, s.storage_bucket)
