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
    from whaledecode.adapters.telegram.keyboards import (
        build_tx_action_hub,
        get_channel_alert_keyboard,
    )

    # Channel is a single-CTA hook: one button, id-based payload (<=64 bytes).
    kb = get_channel_alert_keyboard("ethereum", "0xabc123", "0xdead", event_id=7)
    rows = kb.inline_keyboard
    assert len(rows) == 1 and len(rows[0]) == 1
    assert rows[0][0].text == "⚡ Open Intelligence Hub"
    assert rows[0][0].url == "https://t.me/whaledecodebot?start=tx_ETH_7"
    assert len(rows[0][0].url.split("?start=")[1]) <= 64

    # Legacy callers without an event id keep the raw-hash link.
    kb_legacy = get_channel_alert_keyboard("ethereum", "0xabc123", "0xdead")
    assert kb_legacy.inline_keyboard[0][0].url == (
        "https://t.me/whaledecodebot?start=tx_ETH_0xabc123"
    )

    # Private hub renders the full action suite; all payloads <=64 bytes.
    hub = build_tx_action_hub(
        "BASE", "0x" + "a" * 64, event_id=42,
        from_addr="0x" + "b" * 40, token_address="0xtoken",
    )
    by_text = {b.text: b.url for row in hub.inline_keyboard for b in row}
    assert by_text["💬 Ask AI About This"].endswith("?start=analyze_BASE_42")
    assert by_text["📊 View Entity Dossier"].endswith("?start=wallet_BASE_" + "0x" + "b" * 40)
    assert by_text["🛒 1-Click Mirror Trade"].endswith("?start=swap_BASE_0xtoken")
    assert by_text["🔍 Block Explorer"] == "https://basescan.org/tx/" + "0x" + "a" * 64
    for url in by_text.values():
        if "?start=" in url:
            assert len(url.split("?start=")[1]) <= 64

    # Sparse events: dossier/mirror rows omitted when context missing.
    hub_sparse = build_tx_action_hub("ETH", "0xabc123", event_id=9)
    texts = [b.text for row in hub_sparse.inline_keyboard for b in row]
    assert "📊 View Entity Dossier" not in texts
    assert "🛒 1-Click Mirror Trade" not in texts
    assert "🔍 Block Explorer" in texts
