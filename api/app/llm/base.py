from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..services.clean import nul_free


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


class LLMProvider(ABC):
    """The one interface the rest of the app uses. Swap Claude for a local model without touching callers."""

    name: str = "base"

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult: ...

    async def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> tuple[dict[str, Any], LLMResult]:
        """Ask for JSON and parse it robustly (local models often wrap JSON in prose or code fences)."""
        system = system + "\n\nRespond with a single valid JSON object only. No prose, no code fences."
        result = await self.complete(system, user, max_tokens)
        return nul_free(parse_json_object(result.text)), result


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError(f"Model did not return JSON: {text[:200]}")
