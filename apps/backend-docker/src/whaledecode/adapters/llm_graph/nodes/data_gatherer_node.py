"""Data gatherer: runs deterministic tools + attribution/liquidity enrichment, then summarizes.

Exactly ONE LLM invocation. Tool selection is decided in Python from the
raw_event fields (never by the LLM), so the run is bounded and deterministic —
this is what keeps a full graph run at exactly 2 LLM calls.

Wallet attribution comes from a reverse lookup against the curated-wallet DB
(optional; skipped when no session factory is wired in), and live DEX liquidity
comes from DexScreener — no dRPC/Alchemy quota spent on it.
"""
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from whaledecode.adapters.db.repositories.curated_wallet import CuratedWalletRepository
from whaledecode.adapters.llm_graph.tools.data_gatherer_tools import DEXSCREENER_API

GATHER_PROMPT = """You are a data gatherer. Summarize the factual on-chain and market
context for the whale event below using ONLY the tool results and enriched context provided.
Do NOT invent addresses, amounts, or prices. If a fact is missing, state it is unavailable.
Output a concise, structured summary to hand off to the SMC analyst."""  # noqa: E501


async def enrich_event_context(
    from_addr: str,
    to_addr: str,
    token_addr: str | None,
    chain: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Wallet attribution (reverse curated-DB lookup) + live DEX liquidity for an event.

    Attribution is best-effort: unknown parties stay "Unlabeled" and a DexScreener
    failure keeps the liquidity slots as None — the node degrades, never crashes.
    """
    enriched: dict[str, Any] = {
        "from_label": "Unlabeled Entity",
        "to_label": "Unlabeled EOA",
        "pool_liquidity_usd": None,
        "token_24h_change": None,
    }

    if session_factory is not None and (from_addr or to_addr):
        async with session_factory() as session:
            repo = CuratedWalletRepository(session)
            wallets = await repo.find_by_addresses([from_addr, to_addr])
            for wallet in wallets:
                if wallet.address.lower() == from_addr.lower():
                    enriched["from_label"] = wallet.label or enriched["from_label"]
                if wallet.address.lower() == to_addr.lower():
                    enriched["to_label"] = wallet.label or enriched["to_label"]

    if token_addr and token_addr.startswith("0x"):
        own_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=5.0)
        try:
            resp = await client.get(DEXSCREENER_API.format(address=token_addr))
            if resp.status_code == 200:
                pairs = resp.json().get("pairs", [])
                if pairs:
                    main_pair = pairs[0]
                    enriched["pool_liquidity_usd"] = (main_pair.get("liquidity") or {}).get("usd")
                    enriched["token_24h_change"] = (main_pair.get("priceChange") or {}).get("h24")
        except Exception:
            pass
        finally:
            if own_client:
                await client.aclose()

    return enriched


def create_data_gatherer_node(
    llm: BaseChatModel,
    tools: list[BaseTool],
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    http_client: httpx.AsyncClient | None = None,
):
    name_to_tool = {t.name: t for t in tools}

    async def _call_tool(tool_name: str, kwargs: dict) -> str:
        t = name_to_tool.get(tool_name)
        if t is None:
            return ""
        result = await t.ainvoke(kwargs)
        return result if isinstance(result, str) else str(result)

    async def data_gatherer(state: dict) -> dict:
        event = state.get("raw_event") or {}
        chain = event.get("chain", "ETH")

        enriched = await enrich_event_context(
            _counterparty(event, "from"),
            _counterparty(event, "to"),
            _token_address(event),
            chain,
            session_factory=session_factory,
            http_client=http_client,
        )

        # Deterministic tool dispatch based on the event's fields — no LLM routing.
        calls: list[str] = []
        if event.get("tx_hash"):
            calls.append(await _call_tool("etherscan_tool", {"tx_hash": event["tx_hash"], "chain": chain}))
        if token_address := _token_address(event):
            calls.append(await _call_tool("dexscreener_tool", {"token_address": token_address, "chain": chain}))

        tool_text = "\n\n".join(calls) or "No tool data could be gathered for this event."
        enriched_text = "\n".join(f"{key}: {value if value is not None else 'N/A'}" for key, value in enriched.items())
        result = await llm.ainvoke(
            [
                SystemMessage(content=GATHER_PROMPT),
                HumanMessage(
                    content=(
                        f"Event:\n{event}\n\n"
                        f"Enriched attribution & liquidity:\n{enriched_text}\n\n"
                        f"Tool results:\n{tool_text}"
                    )
                ),
            ]
        )
        return {
            "gathered_context": (
                f"Enriched attribution & liquidity:\n{enriched_text}\n\n"
                f"Tool results:\n{tool_text}\n\nSummary:\n{result.content}"
            )
        }

    return data_gatherer


def _counterparty(event: dict, side: str) -> str:
    """Best-effort extraction of the from/to address from webhook or RPC-log payloads."""
    raw = event.get("raw_json") if isinstance(event.get("raw_json"), dict) else {}
    keys = ("from", "fromAddress") if side == "from" else ("to", "toAddress")
    for key in keys:
        addr = raw.get(key) or event.get(key)
        if addr:
            return _unpad(str(addr))
    topics = raw.get("topics") or event.get("topics") or []
    idx = 1 if side == "from" else 2
    if len(topics) > idx and topics[idx]:
        return _unpad(str(topics[idx]))
    return ""


def _unpad(address: str) -> str:
    """Normalize a log-topics padded address (64 hex chars) to a 20-byte 0x string."""
    body = address[2:] if address.lower().startswith("0x") else address
    body = body.lower()
    return "0x" + body[-40:] if len(body) >= 40 else body


def _token_address(event: dict) -> str | None:
    for key in ("token_address", "token", "tokenAddress"):
        value = event.get(key)
        if value:
            return str(value)
    raw = event.get("raw_json") or {}
    for key in ("token_address", "token", "tokenAddress"):
        value = raw.get(key)
        if value:
            return str(value)
    return None
