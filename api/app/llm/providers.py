from __future__ import annotations

from .base import LLMProvider, LLMResult


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str, api_key: str):
        super().__init__(model)
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        msg = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        return LLMResult(text=text, provider=self.name, model=self.model)


class OpenAICompatibleProvider(LLMProvider):
    """Works with Ollama, vLLM, LM Studio, llama.cpp server, or any on-prem / sovereign model
    that exposes the OpenAI chat-completions API."""

    name = "openai_compatible"

    def __init__(self, model: str, base_url: str, api_key: str = "not-needed", extra_headers: dict | None = None):
        super().__init__(model)
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "not-needed", default_headers=extra_headers,
                                   timeout=180)

    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        resp = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return LLMResult(text=resp.choices[0].message.content or "", provider=self.name, model=self.model)


class FakeProvider(LLMProvider):
    """Deterministic provider for tests: returns canned responses in order."""

    name = "fake"

    def __init__(self, responses: list[str]):
        super().__init__("fake")
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        self.calls.append((system, user))
        return LLMResult(text=self.responses.pop(0), provider=self.name, model=self.model)


class FallbackProvider(LLMProvider):
    """Use the chosen model; if it errors or returns something unreadable, ask the fallback (normally Claude).
    `last_used` says which one actually answered."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        super().__init__(primary.model)
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.last_used: LLMProvider = primary

    async def complete(self, system: str, user: str, max_tokens: int = 2000) -> LLMResult:
        try:
            self.last_used = self.primary
            return await self.primary.complete(system, user, max_tokens)
        except Exception:  # noqa: BLE001
            self.last_used = self.fallback
            return await self.fallback.complete(system, user, max_tokens)

    async def complete_json(self, system: str, user: str, max_tokens: int = 4000):
        try:
            self.last_used = self.primary
            return await self.primary.complete_json(system, user, max_tokens)
        except Exception:  # noqa: BLE001 — includes unreadable JSON from smaller open models
            self.last_used = self.fallback
            return await self.fallback.complete_json(system, user, max_tokens)
