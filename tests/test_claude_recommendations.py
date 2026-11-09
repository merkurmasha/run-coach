"""Exercises the Claude-calling code paths with a fake SDK client, so no
network call or real API key is ever needed to test them.
"""

from types import SimpleNamespace

from run_coach.recommendations import claude_client


class FakeToolUseBlock:
    def __init__(self, name, input_dict):
        self.type = "tool_use"
        self.name = name
        self.input = input_dict


class FakeMessages:
    def __init__(self, response_input):
        self._response_input = response_input
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[FakeToolUseBlock(kwargs["tool_choice"]["name"], self._response_input)])


class FakeAnthropic:
    def __init__(self, response_input, api_key=None):
        self.messages = FakeMessages(response_input)


def test_generate_recommendations_calls_forced_tool_and_parses_input(monkeypatch):
    fake_recs = {"recommendations": [{"text": "x", "evidence": "strong", "rationale": "y"}]}
    fake_client = FakeAnthropic(fake_recs)
    monkeypatch.setattr(claude_client.anthropic, "Anthropic", lambda api_key: fake_client)

    result = claude_client.generate_recommendations({"a": 1}, api_key="fake", model="fake-model")

    assert result == fake_recs["recommendations"]
    assert fake_client.messages.last_kwargs["model"] == "fake-model"
    assert fake_client.messages.last_kwargs["tool_choice"] == {"type": "tool", "name": "submit_recommendations"}


def test_generate_recommendations_returns_empty_list_when_no_tool_use(monkeypatch):
    class EmptyMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[])

    class EmptyClient:
        def __init__(self, **kwargs):
            self.messages = EmptyMessages()

    monkeypatch.setattr(claude_client.anthropic, "Anthropic", lambda api_key: EmptyClient())
    result = claude_client.generate_recommendations({"a": 1}, api_key="fake", model="fake-model")
    assert result == []
