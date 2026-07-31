from __future__ import annotations

import json
import re
from typing import Any

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
