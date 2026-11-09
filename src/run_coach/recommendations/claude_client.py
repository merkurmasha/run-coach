"""Turns the aggregated stats JSON into worded recommendations via Claude.

Claude never sees raw activity rows -- only the dict build_stats() produces.
Structure is forced through tool use (a single required tool call) so the
response is always well-formed JSON, never prose to parse.
"""

from __future__ import annotations

import json

import anthropic

SYSTEM_PROMPT = """You are a running-data analyst writing short, careful notes for one \
runner, based only on the aggregated statistics JSON you are given. You never see \
raw activity data, only computed summaries.

Rules, no exceptions:
1. Every number you write must come from the JSON you were given. Never compute, \
estimate, or round a new number yourself -- quote the JSON's own values and its own \
pre-formatted strings (paces, dates, percentages) exactly.
2. Never diagnose a condition and never give medical advice. If the "special \
conditions" text describes something that sounds like pain, injury, or a medical \
symptom, one of your recommendations should suggest seeing a qualified professional \
-- as a suggestion, not an instruction.
3. Never state a generic rule about training and menstrual cycle phases (e.g. \
textbook claims about what phase is "best" for what kind of training). Only describe \
a pattern if it is actually present in this user's own cycle_phase data, and always \
cite its own n. If a phase's data says "not enough data yet", do not draw a \
conclusion about it.
4. Every recommendation needs an evidence tag: "strong" for well-established \
training science applied correctly to this user's numbers, "moderate" for a \
reasonable inference with some uncertainty, or "hypothesis" for a pattern that is \
merely suggestive, especially anything from a small n. State honestly which tier \
a recommendation belongs to.
5. Every recommendation needs a one-line rationale naming the specific method or \
training principle behind it (e.g. "progressive overload", "the pace-at-HR trend \
for month over month", "Riegel extrapolation"). Never invent a citation, study, or \
statistic that isn't in the provided JSON.
6. If goals.follows_watch_plan is true, frame every recommendation as an adjustment \
to the user's existing watch-generated plan -- never as a replacement plan.
7. If data_gaps is non-empty, you may reference it to explain why a section is \
thin, but don't apologize at length.
8. Write 3 to 6 recommendations. Each should be one to three sentences.

Call submit_recommendations exactly once with your result."""

TOOL_SCHEMA = {
    "name": "submit_recommendations",
    "description": "Submit the finished set of recommendations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "evidence": {"type": "string", "enum": ["strong", "moderate", "hypothesis"]},
                        "rationale": {"type": "string"},
                    },
                    "required": ["text", "evidence", "rationale"],
                },
                "minItems": 1,
                "maxItems": 6,
            }
        },
        "required": ["recommendations"],
    },
}


def generate_recommendations(stats: dict, api_key: str, model: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "submit_recommendations"},
        messages=[
            {
                "role": "user",
                "content": f"Here is the aggregated stats JSON:\n\n{json.dumps(stats, default=str)}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_recommendations":
            return block.input.get("recommendations", [])
    return []
