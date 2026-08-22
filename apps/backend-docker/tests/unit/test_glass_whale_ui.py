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
    assert rows[0][0].url == "https://t.me/whaledecodebot?start=deepdive_ETH_0xabc123"
    assert rows[0][1].url == "https://t.me/whaledecodebot?start=ask_ETH_0xabc123"
    assert rows[1][0].url == "https://t.me/whaledecodebot?start=track_ETH_0xdead"
    assert rows[1][1].url == "https://etherscan.io/tx/0xabc123"

    kb_arb = get_channel_alert_keyboard("arbitrum", "0xabc123", "0xdead")
    assert kb_arb.inline_keyboard[1][1].url == "https://arbiscan.io/tx/0xabc123"

    kb_custom = get_channel_alert_keyboard("base", "0xabc123", "0xdead", )
    assert kb_custom.inline_keyboard[0][0].url == "https://t.me/whaledecodebot?start=deepdive_BASE_0xabc123"
