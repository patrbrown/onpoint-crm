"""Postgres can't store the NUL character (\\x00) in text or JSON, and some PDFs and emails contain it."""
from typing import Any


def nul_free(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {nul_free(k): nul_free(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(nul_free(v) for v in value)
    return value
