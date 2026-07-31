from __future__ import annotations

import json
import re
from typing import Any


def extract_clean_json(content: Any) -> dict[str, Any]:
    """Parse LLM response content into a dict.

    Handles:
      - Plain JSON strings
      - Markdown code-fenced JSON (```json ... ```)
      - Gemini-style list-of-content-blocks: [{"type":"text","text":"..."}]
    Falls back to a safe default on parse failure.
    """
    # 0. Already a dict — pass through
    if isinstance(content, dict):
        return content

    # 1. Flatten content blocks
    if isinstance(content, list):
        text_parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        raw_str = "".join(text_parts)
    else:
        raw_str = str(content)

    # 2. Strip markdown code fences
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_str, re.DOTALL)
    if fence_match:
        clean_str = fence_match.group(1)
    else:
        clean_str = raw_str.strip()

    # 3. Parse
    try:
        parsed = json.loads(clean_str)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # 4. Fallback — return raw text as summary so downstream always has content
    return {
        "summary": raw_str,
        "risk_score": 0.5,
        "thesis": "Failed to parse structured output.",
        "evidence": [],
        "tool_calls": [],
        "disclaimer": "Not financial advice.",
    }
