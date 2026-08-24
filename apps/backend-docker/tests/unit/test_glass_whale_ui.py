from whaledecode.adapters.llm_graph.state.investigation_result import InvestigationResult
from whaledecode.adapters.telegram.formatters.channel_formatter import escape_markdown_v2


def test_briefing_description_uses_spoiler_template() -> None:
    desc = InvestigationResult.model_fields["briefing_markdown"].description or ""
    assert "||`0x...`||" in desc
    assert "**Trace Metrics**" in desc
    assert "> **🧠 SMC Intelligence**" in desc
    assert "Tx: ||`[tx_hash]`||" in desc
    assert "From: ||`[from_address]`||" in desc
    assert "To: ||`[to_address]`||" in desc


def test_escape_roundtrip_premium_briefing() -> None:
    briefing = (
        "🫧 *Whale Accumulation*\n"
        "💎 **Value:** `$150,000` PEPE\n"
        "🌐 **Chain:** Ethereum\n"
        "🎯 **Risk:** 85%\n\n"
        "> **🧠 SMC Intelligence**\n"
        "> Funds consolidated into a fresh address, hinting at accumulation.\n\n"
        "**Trace Metrics**\n"
        "Tx: ||`0xabc`||\n"
        "From: ||`0xdead`||\n"
        "To: ||`0xbeef`||"
    )
    out = escape_markdown_v2(briefing)
    assert "||`0xabc`||" in out
    assert "||`0xdead`||" in out
    assert "||`0xbeef`||" in out
    assert "\\|" not in out
    assert "> **🧠 SMC Intelligence**" in out
    assert out.startswith("🫧 *Whale Accumulation*")


def test_cta_keyboard_deep_links() -> None:
    from whaledecode.adapters.telegram.keyboards import get_channel_alert_keyboard

    kb = get_channel_alert_keyboard("ethereum", "0xabc123", "0xdead")
    rows = kb.inline_keyboard
    # Phase 3 spec: Hub row, then Track Cluster + View Graph.
    assert rows[0][0].url == "https://t.me/whaledecodebot?start=tx_ETH_0xabc123"
    track_row = next(r for r in rows if r[0].text == "🕵️ Track Cluster")
    graph_btn = next(b for r in rows for b in r if b.text == "🔍 View Graph")
    assert track_row[0].url == "https://t.me/whaledecodebot?start=wallet_ETH_0xdead"
    assert graph_btn.url == "https://etherscan.io/tx/0xabc123"

    # Token present -> 1-Click Swap deep link in spec order (row 1).
    kb_swap = get_channel_alert_keyboard("base", "0xabc123", "0xdead", token_address="0xtoken")
    swap_rows = [r for r in kb_swap.inline_keyboard if r[0].text == "🛒 1-Click Swap"]
    assert len(swap_rows) == 1
    assert swap_rows[0][0].url == "https://t.me/whaledecodebot?start=swap_0xtoken"
    # No token -> no swap button (e.g. plain transfers).
    assert all(r[0].text != "🛒 1-Click Swap" for r in kb.inline_keyboard)

    kb_arb = get_channel_alert_keyboard("arbitrum", "0xabc123", "0xdead")
    graph_arb = next(b for r in kb_arb.inline_keyboard for b in r if b.text == "🔍 View Graph")
    assert graph_arb.url == "https://arbiscan.io/tx/0xabc123"

    kb_custom = get_channel_alert_keyboard("base", "0xabc123", "0xdead", bot_username="custombot")
    hub_custom = next(
        b for r in kb_custom.inline_keyboard for b in r if b.text == "⚡ Open Intelligence Hub"
    )
    assert hub_custom.url == "https://t.me/custombot?start=tx_BASE_0xabc123"
