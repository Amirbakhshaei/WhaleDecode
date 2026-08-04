from typing import Any, TypedDict


class InvestigationState(TypedDict):
    """Deterministic low-RPM investigation state.

    `raw_event`: the raw candidate event (chain, tx_hash, token, addresses).
    `gathered_context`: tool-derived context, summarized by the data gatherer.
    `final_thesis`: the SMC analyst's Telegram-ready markdown brief.
    """

    raw_event: dict[str, Any]
    gathered_context: str
    final_thesis: str
