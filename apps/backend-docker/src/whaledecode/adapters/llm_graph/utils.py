from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

# ponytail: stripped-down parser — the old fence_match regex missed nested
# objects and edge cases. This version strips all markdown cruft first,
# then finds the outermost JSON object boundaries.
_CLEANUP_RE = re.compile(r"```(?:json)?|```")


def extract_clean_json(content: Any) -> dict[str, Any]:
    """Parse LLM response content into a dict.

    Handles plain JSON, markdown-fenced JSON, Gemini content blocks,
    and arbitrary surrounding text. Falls back to a safe default.
    """
    if isinstance(content, dict):
        return content

    # Flatten content blocks
    if isinstance(content, list):
        raw_str = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    else:
        raw_str = str(content)

    # Strip ALL markdown backticks and 'json' identifiers
    clean = _CLEANUP_RE.sub("", raw_str).strip()

    # Find the first '{' and last '}' to isolate the JSON object
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start : end + 1]

    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "summary": raw_str,
        "risk_score": 0.5,
        "thesis": "Failed to parse structured output.",
        "evidence": [],
        "tool_calls": [],
        "disclaimer": "Not financial advice.",
    }


def trim_history(messages: list[BaseMessage], max_tokens: int = 3000) -> list[BaseMessage]:
    """Cap ReAct loop history to the most recent max_tokens.

    LangGraph's `add_messages` appends every turn to state, so a long tool loop can
    inflate the context window. The callers prepend the system prompt themselves,
    so history trimming keeps only the tail. The opening user turn is always kept:
    Gemini rejects a conversation whose first message is a tool call.
    """
    if not messages:
        return []
    # Keep the opening user turn separate — it is the seed of the ReAct loop.
    opening = [messages[0]] if isinstance(messages[0], HumanMessage) else []
    tail = messages[len(opening):]

    from langchain_core.messages import trim_messages

    trimmed = trim_messages(
        tail,
        max_tokens=max_tokens,
        token_counter="approximate",
        strategy="last",
        include_system=False,
    )
    # trim_messages drops from the front; if that cut lands inside a tool_call/
    # tool_result pair, a leading ToolMessage survives without its AI call.
    while trimmed and isinstance(trimmed[0], ToolMessage):
        trimmed = trimmed[1:]
    return opening + trimmed
