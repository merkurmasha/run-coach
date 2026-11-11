"""_describe_claude_error turns an Anthropic SDK exception into a short,
redacted message safe to show in the dashboard -- never the raw key.
"""

import anthropic
import httpx2

from run_coach.web.app import _describe_claude_error


def _request():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def test_authentication_error_is_rewritten_without_echoing_detail():
    exc = anthropic.AuthenticationError(
        "invalid x-api-key sk-ant-totallyrealkeyvalue123", response=httpx2.Response(401, request=_request()), body=None
    )
    message = _describe_claude_error(exc)
    assert "ANTHROPIC_API_KEY" in message
    assert "sk-ant-" not in message


def test_connection_error_is_rewritten():
    exc = anthropic.APIConnectionError(message="Connection refused", request=_request())
    message = _describe_claude_error(exc)
    assert "network" in message.lower() or "reach" in message.lower()


def test_redacts_a_key_shaped_string_in_any_message():
    message = _describe_claude_error(ValueError("something went wrong with key sk-ant-shouldnotappear9999"))
    assert "sk-ant-" not in message
    assert "[REDACTED]" in message
