"""Exercises the Claude-calling code paths with a fake SDK client, so no
network call or real API key is ever needed to test them.
"""

import json
from types import SimpleNamespace

from run_coach.recommendations import claude_client


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeMessages:
    def __init__(self, response_json):
        self._response_json = response_json
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[FakeTextBlock(json.dumps(self._response_json))])


class FakeAnthropic:
    def __init__(self, response_json, api_key=None):
        self.messages = FakeMessages(response_json)


def test_generate_recommendations_uses_structured_output_not_forced_tool_choice(monkeypatch):
    fake_recs = {"recommendations": [{"text": "x", "evidence": "strong", "rationale": "y"}]}
    fake_client = FakeAnthropic(fake_recs)
    monkeypatch.setattr(claude_client.anthropic, "Anthropic", lambda api_key: fake_client)

    result = claude_client.generate_recommendations({"a": 1}, api_key="fake", model="fake-model")

    assert result == fake_recs["recommendations"]
    assert fake_client.messages.last_kwargs["model"] == "fake-model"
    # Forced tool_choice returns a 400 on Claude Sonnet 5.5 and newer -- must not be sent.
    assert "tool_choice" not in fake_client.messages.last_kwargs
    assert fake_client.messages.last_kwargs["output_config"]["format"]["type"] == "json_schema"


def test_generate_recommendations_returns_empty_list_when_no_text_block(monkeypatch):
    class EmptyMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[])

    class EmptyClient:
        def __init__(self, **kwargs):
            self.messages = EmptyMessages()

    monkeypatch.setattr(claude_client.anthropic, "Anthropic", lambda api_key: EmptyClient())
    result = claude_client.generate_recommendations({"a": 1}, api_key="fake", model="fake-model")
    assert result == []


def test_output_schema_requires_why_it_matters_field():
    item_schema = claude_client.OUTPUT_SCHEMA["properties"]["recommendations"]["items"]
    assert "why_it_matters" in item_schema["properties"]
    assert "why_it_matters" in item_schema["required"]
    assert "rationale" in item_schema["required"]


def test_system_prompt_has_three_good_and_three_bad_examples():
    assert claude_client.SYSTEM_PROMPT.count("BAD:") == 3
    assert claude_client.SYSTEM_PROMPT.count("GOOD:") == 3


def test_system_prompt_bans_jargon_in_user_facing_text():
    prompt = claude_client.SYSTEM_PROMPT
    assert "field name" in prompt.lower()
    assert "W42" in prompt  # the ISO-week-code example it tells Claude to avoid
    assert "s/km" in prompt  # named as the unit to avoid writing in user-facing text
