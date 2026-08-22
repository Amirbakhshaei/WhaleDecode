"""LangSmith evaluators for the golden dataset.

Two evaluators:
- heuristic_formatting_evaluator: deterministic formatting checks on the output.
- make_smc_judge(llm): LLM-as-a-judge grading hallucination / factual consistency.
"""

import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith.schemas import Example, Run

SPOILER_RE = re.compile(r"\|\|.*?\|\|")
JSON_LIKE_RE = re.compile(r'\{\s*"[A-Za-z_]+"\s*:')
# The repo's briefing format (consolidated_report SYSTEM_PROMPT) uses emoji + **bold**
# section lines and `>` blockquote Intelligence lines, plus ||spoiler|| tags.
HEADER_RE = re.compile(r"(?m)^(?:\*\*[^*\n]+\*\*|>)")

JUDGE_SYSTEM_PROMPT = """You are a strict hallucination judge for blockchain SMC theses.
Grade the analyst's thesis on factual consistency with the provided blockchain event and tool outputs.
Return ONLY a single digit: 1 if every metric in the thesis matches the event/tool data, 0 if any
number, address, or claim is fabricated or inconsistent with the data."""


def heuristic_formatting_evaluator(run: Run, example: Example) -> dict[str, Any]:
    """Check the output for the repo's Telegram briefing format: **bold**/blockquote headers,
    || spoiler tags, no raw JSON leaked."""
    output = str((run.outputs or {}).get("summary", ""))
    checks = {
        "has_markdown_header": bool(HEADER_RE.search(output)),
        "has_spoiler_tags": bool(SPOILER_RE.search(output)),
        "no_raw_json_leak": not JSON_LIKE_RE.search(output),
    }
    passed = sum(checks.values())
    return {
        "key": "formatting",
        "score": passed / len(checks),
        "comment": f"{passed}/{len(checks)} checks passed: {checks}",
    }


def make_smc_judge(llm: BaseChatModel):
    """Return an async LangSmith evaluator grading SMC factual consistency (0/1)."""

    async def smc_judge(run: Run, example: Example) -> dict[str, Any]:
        prediction = str((run.outputs or {}).get("summary", ""))
        event = example.inputs.get("event", {})
        tool_outputs = example.inputs.get("tool_outputs", {})
        prompt = (
            f"Event: {json.dumps(event, default=str)}\n"
            f"Tool outputs:\n{json.dumps(tool_outputs, indent=2, default=str)}\n"
            f"Analyst thesis:\n{prediction}"
        )
        response = await llm.ainvoke([SystemMessage(content=JUDGE_SYSTEM_PROMPT), HumanMessage(content=prompt)])
        text = response.content if isinstance(response.content, str) else str(response.content)
        score = 1 if re.fullmatch(r"\s*1[\s.].*", text) or text.strip() == "1" else 0
        return {"key": "smc_soundness", "score": score, "comment": f"judge verdict: {text.strip()[:200]}"}

    return smc_judge
