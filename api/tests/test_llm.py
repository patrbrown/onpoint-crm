import pytest

from app.llm import FakeProvider, get_provider, parse_json_object
from app.llm.providers import AnthropicProvider, OpenAICompatibleProvider


def test_parse_json_handles_fences_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! Here it is: {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_provider_factory_is_swappable():
    assert isinstance(get_provider("anthropic", "claude-sonnet-5-5"), AnthropicProvider)
    local = get_provider("openai_compatible", "llama3.1:70b", "http://localhost:11434/v1")
    assert isinstance(local, OpenAICompatibleProvider) and local.model == "llama3.1:70b"
    with pytest.raises(ValueError):
        get_provider("nope")


async def test_complete_json_appends_json_instruction():
    fake = FakeProvider(['{"ok": true}'])
    data, result = await fake.complete_json("sys", "user")
    assert data == {"ok": True} and "valid JSON" in fake.calls[0][0]
