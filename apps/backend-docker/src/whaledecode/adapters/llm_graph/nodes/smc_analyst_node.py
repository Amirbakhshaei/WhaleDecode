"""SMC analyst: turns raw_event + gathered_context into a Telegram-ready brief.

Uses deterministic SMC analysis from PriceOracle (DexScreener data) instead of
pure LLM reasoning. NO tools and exactly ONE LLM invocation for narrative formatting.
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from whaledecode.adapters.pricing.oracle import SMCAnalysisResult

SMC_SYSTEM_PROMPT = """You are a Smart Money Concepts (SMC) blockchain analyst.
Analyze the whale event below using ONLY the provided on-chain and market context.
Produce a Telegram-ready markdown brief following this EXACT template:

🕵️ *WHALEDECODE | SYNDICATE ACCUMULATION*

*Asset:* `${token_symbol}` on *{chain}*
*Total Coordinated Volume:* `${total_usd}` ({wallets_count} Wallets)
*Action:* Aggressive Market Accumulation

🧩 *Cluster Graph Forensics:*
• *Parent Funding:* `{parent_label}` ({funding_time_ago})
• *Execution:* Coordinated across {block_span} blocks
• *Syndicate Type:* `{cluster_type}`

📈 *Market Structure (SMC):*
• *Regime:* `{smc_regime}`
• *Location:* `{discount_status}` ({ote_status})
• *Invalidation Floor:* `${invalidation_price}`

📊 *Entity Profile:*
• *Cluster Win-Rate:* `{cluster_win_rate}%`
• *Average Hold Duration:* `{avg_hold_duration}`

🔗 [DexScreener]({dex_url}) | [BlockExplorer]({explorer_url})

RULES:
1. Every address and hash inside Telegram spoiler tags: ||`0x...`||.
2. Base every number ONLY on the context provided. Missing data reads '[ N/A ]'.
3. Do NOT invent wallet addresses, token amounts, or USD values.
4. Format numbers with commas."""  # noqa: E501


def _format_smc_analysis(smc: SMCAnalysisResult | None) -> dict[str, str]:
    """Convert SMCAnalysisResult to template variables."""
    if smc is None:
        return {
            "smc_regime": "UNKNOWN",
            "discount_status": "Unknown",
            "ote_status": "Unknown",
            "invalidation_price": "N/A",
        }

    discount_status = "Discount Zone" if smc.is_discount_zone else "Premium Zone"
    ote_status = "OTE Confluence ✅" if smc.ote_confluence else "Outside OTE"
    invalidation_price = f"${smc.invalidation_level:,.4f}"

    return {
        "smc_regime": smc.market_regime,
        "discount_status": discount_status,
        "ote_status": ote_status,
        "invalidation_price": invalidation_price,
    }


def create_smc_analyst_node(llm: BaseChatModel):
    async def smc_analyst(state: dict) -> dict:
        event = state.get("raw_event") or {}
        context = state.get("gathered_context", "")
        smc_analysis = state.get("smc_analysis")

        # Format SMC data for template
        smc_vars = _format_smc_analysis(smc_analysis)

        # Build template variables from event + context + SMC
        raw = event.get("raw_json", {})
        token_symbol = raw.get("token") or raw.get("symbol") or raw.get("asset") or "UNKNOWN"
        chain = event.get("chain", "Unknown")
        total_usd = raw.get("value_usd") or event.get("value_usd") or 0
        wallets_count = raw.get("cluster_wallets_count") or event.get("cluster_wallets_count") or 1
        cluster_type = raw.get("cluster_type") or event.get("cluster_type") or "UNKNOWN"
        parent_label = raw.get("cluster_origin") or raw.get("funding_attribution") or "Unknown"
        funding_time_ago = "recent"  # Would compute from timestamps
        block_span = raw.get("block_span") or "N/A"
        cluster_win_rate = raw.get("win_rate") or event.get("win_rate") or 0
        avg_hold_duration = raw.get("avg_hold_duration") or "N/A"
        tx_hash = event.get("tx_hash", "")
        dex_url = f"https://dexscreener.com/{chain.lower()}/{raw.get('address', '')}" if raw.get("address") else "#"
        explorer_url = f"https://etherscan.io/tx/{tx_hash}" if chain.lower() in ("eth", "ethereum") else "#"

        template_vars = {
            "token_symbol": token_symbol,
            "chain": chain,
            "total_usd": f"{float(total_usd):,.2f}",
            "wallets_count": wallets_count,
            "parent_label": parent_label,
            "funding_time_ago": funding_time_ago,
            "block_span": block_span,
            "cluster_type": cluster_type,
            "cluster_win_rate": f"{float(cluster_win_rate):.1f}" if cluster_win_rate else "N/A",
            "avg_hold_duration": str(avg_hold_duration),
            "dex_url": dex_url,
            "explorer_url": explorer_url,
            **smc_vars,
        }

        # Format the prompt with variables
        formatted_prompt = SMC_SYSTEM_PROMPT.format(**template_vars)

        result = await llm.ainvoke(
            [
                SystemMessage(content=formatted_prompt),
                HumanMessage(content=f"Event:\n{event}\n\nGathered context:\n{context}"),
            ]
        )
        return {"final_thesis": result.content}

    return smc_analyst
