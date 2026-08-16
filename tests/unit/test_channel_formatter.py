from whaledecode.adapters.telegram.formatters.channel_formatter import (
    build_alert_data,
    escape_markdown_v2,
    format_alert,
    format_channel_post_markdown,
    format_premium_event_post,
    truncate_hash,
)

EVENT = {
    "chain": "ethereum",
    "tx_hash": "0x" + "ab" * 32,
    "raw_json": {
        "token": "PEPE",
        "amount": "500000000",
        "from": "0x" + "00" * 20,
        "to": "0x" + "ff" * 20,
        "value_usd": 4250.0,
    },
}


class TestFormatPremiumEventPost:
    def test_header_present(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "WHALEDECODE" in html
        assert "PRO" in html

    def test_asset_line(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "500,000,000" in html
        assert "PEPE" in html

    def test_network_line(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "Ethereum" in html

    def test_value_line(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "$4,250.00" in html

    def test_low_risk(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.2})
        assert "🟢" in html
        assert "LOW" in html
        assert "20%" in html

    def test_moderate_risk(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.55})
        assert "🟡" in html
        assert "MODERATE" in html
        assert "55%" in html

    def test_high_risk(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.85})
        assert "🔴" in html
        assert "HIGH" in html
        assert "85%" in html

    def test_summary_in_blockquote(self):
        html = format_premium_event_post(EVENT, {"summary": "Whale moved tokens"})
        assert "<blockquote>Whale moved tokens</blockquote>" in html

    def test_thesis_in_blockquote(self):
        html = format_premium_event_post(EVENT, {"thesis": "Bearish signal"})
        assert "<blockquote>Bearish signal</blockquote>" in html

    def test_evidence_not_in_text(self):
        """Evidence moved to inline keyboard — formatter no longer renders it."""
        analysis = {
            "risk_score": 0.3,
            "evidence": [{"fact": "Moved to CEX", "source": "etherscan"}],
        }
        html = format_premium_event_post(EVENT, analysis)
        assert "EVIDENCE" not in html

    def test_no_evidence_section_when_empty(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3, "evidence": []})
        assert "EVIDENCE" not in html

    def test_html_escaped(self):
        analysis = {"summary": "<script>alert(1)</script>", "risk_score": 0.3}
        html = format_premium_event_post(EVENT, analysis)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_no_explorer_link_in_text(self):
        """Explorer link moved to inline keyboard — not in message body."""
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "etherscan.io" not in html

    def test_code_tags_used(self):
        html = format_premium_event_post(EVENT, {"risk_score": 0.3})
        assert "<code>" in html

    def test_blockquote_tags_used(self):
        html = format_premium_event_post(EVENT, {"summary": "test"})
        assert "<blockquote>" in html

    def test_missing_raw_json_fallback(self):
        event_no_raw = {"chain": "bsc", "tx_hash": "0x" + "cc" * 32}
        html = format_premium_event_post(event_no_raw, {"risk_score": 0.1})
        assert "Bsc" in html
        assert "UNKNOWN" in html

    def test_zero_value(self):
        event_zero = {**EVENT, "raw_json": {**EVENT["raw_json"], "value_usd": 0}}
        html = format_premium_event_post(event_zero, {"risk_score": 0.1})
        assert "$0.00" in html


class TestEscapeMarkdownV2:
    def test_escapes_periods_and_hyphens(self):
        out = escape_markdown_v2("Balance 1.5 ETH - net positive.")
        assert "1\\.5 ETH \\- net positive\\." in out

    def test_preserves_code_spans(self):
        out = escape_markdown_v2("Tx: `0xabc-123` end.")
        assert "`0xabc-123`" in out
        assert "\\." in out

    def test_preserves_blockquote_prefix(self):
        out = escape_markdown_v2("> **Intelligence**\n> Liquid pool.")
        assert out.startswith("> **Intelligence**\n> ")
        assert "\\." in out

    def test_escapes_brackets_and_parens(self):
        out = escape_markdown_v2("value (est.) [N/A]")
        assert "\\(" in out and "\\)" in out
        assert "\\[" in out and "\\]" in out

    def test_preserves_spoiler_tags(self):
        out = escape_markdown_v2("Tx: ||`0xabc-123`|| end.")
        assert "||`0xabc-123`||" in out
        assert "\\|" not in out

    def test_escapes_lone_pipe(self):
        out = escape_markdown_v2("a | b")
        assert "a \\| b" in out

    def test_roundtrip_template(self):
        tpl = (
            "✦ *High Value Transfer*\n"
            "`$150,000` · `100 USDC` · Ethereum\n"
            "Risk Score: 85%\n\n"
            "> **Intelligence**\n"
            "> Funds consolidated into a fresh address, hinting at accumulation.\n\n"
            "**Trace**\n"
            "Tx: `0x1234`"
        )
        out = escape_markdown_v2(tpl)
        assert "✦ *High Value Transfer*" in out
        assert "`$150,000`" in out
        assert "> **Intelligence**" in out
        assert "accumulation\\." in out


TRACE_EVENT = {
    "chain": "ethereum",
    "event_type": "TRANSFER",
    "tx_hash": "0xf4a93fa84fef68a2daf2fcf02211c01a8d87338b26e402c14fc1be3d51cdb15a",
    "raw_json": {
        "token": "USDC",
        "amount": "124901",
        "value_usd": 124900.99,
        "from": "0xdfd5293d8e347dfe59e90efd55b2956a1343963d",
        "to": "0xd862cdcfeb856c32b3c4f7563f4811d8ddfd42e2",
    },
}

TRACE_ANALYSIS = {
    "risk_score": 0.72,
    "summary": (
        "**Action:** whale swept USDC toward a Binance-linked addr\n"
        "**Context:** consolidation of a liquidity node\n"
        "**Bias:** neutral, likely accumulation"
    ),
}


class TestTruncateHash:
    def test_long_hash_truncated(self):
        out = truncate_hash("0xf4a93fa84fef68a2daf2fcfb49")
        assert out == "0xf4a9…fb49"
        assert len(out) < 15

    def test_short_string_unchanged(self):
        assert truncate_hash("0x1234") == "0x1234"


class TestFormatChannelPostMarkdown:
    def test_hyperlinked_trace(self):
        md = format_channel_post_markdown(TRACE_EVENT, TRACE_ANALYSIS)
        from_addr = TRACE_EVENT["raw_json"]["from"]
        tx = TRACE_EVENT["tx_hash"]
        from_label = truncate_hash(from_addr)
        tx_label = truncate_hash(tx)
        assert f"[{from_label}](https://etherscan.io/address/{from_addr})" in md
        assert f"[{tx_label}](https://etherscan.io/tx/{tx})" in md

    def test_trace_no_full_hashes_in_plain_text(self):
        md = format_channel_post_markdown(TRACE_EVENT, TRACE_ANALYSIS)
        full = "0xf4a93fa84fef68a2daf2fcf02211c01a8d87338b26e4029fc1be3d51cdb15a"
        assert full not in md

    def test_smc_bullets_per_line(self):
        md = format_channel_post_markdown(TRACE_EVENT, TRACE_ANALYSIS)
        assert "• Action:" in md
        assert "• Context:" in md
        assert "• Bias:" in md

    def test_risk_badge_present(self):
        md = format_channel_post_markdown(TRACE_EVENT, {"risk_score": 0.85})
        assert "🔴 HIGH" in md

    def test_msg_valid_markdown_v2_escape(self):
        # Reconstitute a message with a dot and hyphen in a bullet body; assert they're escaped.
        md = format_channel_post_markdown(
            TRACE_EVENT,
            {"risk_score": 0.5, "summary": "**Bias:** neutral. - Not shaken."},
        )
        assert "neutral\\. \\- Not shaken\\." in md


class TestFormatAlert:
    def test_template_a_header_and_asset(self):
        # TRACE_EVENT chain is "ethereum" -> Template A (L1 Mainnet).
        html = format_alert(build_alert_data(TRACE_EVENT, TRACE_ANALYSIS))
        assert "🐋" in html
        assert "STRATEGIC TRANSFER | Ethereum" in html
        assert "USDC" in html

    def test_template_a_value_score(self):
        html = format_alert(build_alert_data(TRACE_EVENT, TRACE_ANALYSIS))
        assert "$124,900.99 USD" in html
        assert "Conviction Score:</b> 72/100" in html

    def test_template_a_synthesis_bullets(self):
        html = format_alert(build_alert_data(TRACE_EVENT, TRACE_ANALYSIS))
        assert "🧠 <b>Agentic Synthesis:</b>" in html
        assert "<b>Entity:</b> whale swept USDC toward a Binance-linked addr" in html
        assert "<b>Context:</b> consolidation of a liquidity node" in html
        assert "<b>Impact:</b> neutral, likely accumulation" in html

    def test_template_a_flow_line(self):
        html = format_alert(build_alert_data(TRACE_EVENT, TRACE_ANALYSIS))
        assert "<code>0xdfd5…963d</code> ➔ <code>0xd862…42e2</code>" in html

    def test_template_a_footer_links(self):
        data = build_alert_data(TRACE_EVENT, TRACE_ANALYSIS)
        html = format_alert(data)
        raw = TRACE_EVENT["raw_json"]
        tx = TRACE_EVENT["tx_hash"]
        assert "WhaleDecode Platform Actions" in html
        assert "Track This Entity" in html
        assert "Ask AI About Tx" in html
        assert data["track_link"] == f"https://t.me/whaledecodebot?start=track_{raw['from']}"
        assert data["analyze_link"] == f"https://t.me/whaledecodebot?start=analyze_{tx}"

    def test_template_b_l2_velocity(self):
        event_l2 = {**TRACE_EVENT, "chain": "base"}
        html = format_alert(build_alert_data(event_l2, TRACE_ANALYSIS))
        assert "⚡" in html
        assert "SMART MONEY TRANSFER | Base" in html
        assert "🛣️ <b>Flow:</b>" not in html  # L2 omits the flow line
        assert "<b>Profile:</b>" in html
        assert "<b>Impact:</b>" in html
        assert "Auto-Track Wallet" in html
        assert "Deep Dive Tx" in html

    def test_html_escaping(self):
        analysis = {"risk_score": 0.3, "summary": "**Action:** <script>alert(1)</script>"}
        html = format_alert(build_alert_data(TRACE_EVENT, analysis))
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_chain_id_normalized_to_template_a(self):
        data = build_alert_data({**TRACE_EVENT, "chain": 1}, {"risk_score": 0.735})
        html = format_alert(data)
        assert "STRATEGIC" in html
        assert "Conviction Score:</b> 74/100" in html

    def test_zero_value_renders_zero(self):
        event_zero = {**TRACE_EVENT, "raw_json": {**TRACE_EVENT["raw_json"], "value_usd": 0}}
        html = format_alert(build_alert_data(event_zero, {"risk_score": 0.1}))
        assert "$0.00" in html

    def test_long_paragraph_shortened_to_one_sentence(self):
        report = {
            "risk_score": 0.5,
            "fundamental_summary": "Whale swept a large USDC block. It landed on a Binance-linked address. Clear CEX inflow.",
            "technical_summary": "Broke the daily support zone. Volume confirmed the move. Momentum is fading.",
            "bias_summary": "Bullish accumulation. Favor long setups. Invalidated below support.",
        }
        html = format_alert(build_alert_data(TRACE_EVENT, report))
        assert html.count("It landed") == 0
        assert "Whale swept a large USDC block." in html
        assert "Broke the daily support zone." in html
        assert "Bullish accumulation." in html

    def test_na_sentinel_normalized_to_neutral_fallback(self):
        # LLM returned literal "N/A" / "[ N/A ]" for some synthesis fields.
        report = {
            "risk_score": 0.8,
            "fundamental_summary": "N/A",
            "technical_summary": "[ N/A ]",
            "bias_summary": "Neutral rebalancing between unlabeled wallets.",
        }
        html = format_alert(build_alert_data(TRACE_EVENT, report))
        assert "N/A" not in html
        assert "Entity under analysis." in html
        assert "Market context unavailable." in html
        assert "Neutral rebalancing between unlabeled wallets." in html

    def test_empty_fields_use_neutral_fallback_not_na(self):
        # Empty structured fields AND a summary with no Action/Context/Bias bullets.
        report = {"risk_score": 0.8, "summary": "Whale moved USDT between two unlabeled wallets."}
        data = build_alert_data(TRACE_EVENT, report)
        html = format_alert(data)
        assert "N/A" not in html
        assert data["profile"] == "Entity under analysis."
        assert data["context"] == "Market context unavailable."
        assert data["impact"] == "Impact under assessment."

    def test_na_variants_all_treated_as_missing(self):
        from whaledecode.adapters.telegram.formatters.channel_formatter import (
            _is_missing,
            parse_synthesis_points,
        )
        for token in ["N/A", "n/a", "[ N/A ]", "none", "NULL", "-", "", None]:
            assert _is_missing(token), token
        out = parse_synthesis_points({"fundamental_summary": "none", "technical_summary": "-", "bias_summary": "n/a"})
        assert out["profile"] == "Entity under analysis."
        assert out["context"] == "Market context unavailable."
        assert out["impact"] == "Impact under assessment."

    def test_fenced_json_with_preamble_is_parsed(self):
        from whaledecode.adapters.telegram.formatters.channel_formatter import parse_synthesis_points
        raw = (
            "Here is my analysis:\n"
            "```json\n"
            "{\"entity_profile\": \"Fresh Accumulator -> CEX\", "
            "\"context\": \"CEX Outflow timing\", "
            "\"impact\": \"Supply shock\"}\n"
            "```"
        )
        out = parse_synthesis_points(raw)
        assert out["profile"] == "Fresh Accumulator -> CEX."
        assert out["context"] == "CEX Outflow timing."
        assert out["impact"] == "Supply shock."
        assert out["profile"] != "Entity under analysis."


class TestBuildAlertData:
    def test_extracts_smc_fields_from_summary(self):
        data = build_alert_data(TRACE_EVENT, TRACE_ANALYSIS)
        assert data["fundamental_summary"] == "whale swept USDC toward a Binance-linked addr"
        assert data["technical_summary"] == "consolidation of a liquidity node"
        assert data["bias_summary"] == "neutral, likely accumulation"

    def test_structured_summaries_override_parsed_bullets(self):
        report = {
            "risk_score": 0.72,
            "summary": "**Action:** echo of raw metrics\n**Context:** echo\n**Bias:** echo",
            "fundamental_summary": "CEX Outflow ($15.2M SHIB: Binance 16 ➔ Cold Storage).",
            "technical_summary": "Executed at the $0.00001820 daily support zone.",
            "bias_summary": "Bullish Accumulation. Favor long setups; invalidated below $0.00001780.",
        }
        data = build_alert_data(TRACE_EVENT, report)
        assert data["fundamental_summary"] == report["fundamental_summary"]
        assert data["technical_summary"] == report["technical_summary"]
        assert data["bias_summary"] == report["bias_summary"]

    def test_raw_hex_always_stripped_from_summaries(self):
        report = {
            "risk_score": 0.72,
            "fundamental_summary": (
                "Transferred 9,728,356 SHIB from ||0xdfd5293d8e347dfe59e90efd55b2956a1343963d|| "
                "to 0x545a4655...e2f4: CEX Outflow."
            ),
            "technical_summary": "Support zone 0x000000000000000000000000000000000000FFaa.",
            "bias_summary": "Bullish Accumulation at 0xdeadbeef.",
        }
        data = build_alert_data(TRACE_EVENT, report)
        assert "0x" not in data["fundamental_summary"]
        assert "0x" not in data["technical_summary"]
        assert "0x" not in data["bias_summary"]
        assert "Binance 16 ➔ Cold Storage".split(" ➔ ")[0] == "Binance 16"
        assert data["fundamental_summary"] == "Transferred 9,728,356 SHIB from to : CEX Outflow."
        assert data["bias_summary"] == "Bullish Accumulation at ."

    def test_hex_strip_preserves_trader_content(self):
        from whaledecode.adapters.telegram.formatters.channel_formatter import _strip_hex

        out = _strip_hex("CEX Outflow ($15.2M SHIB: Binance 16 ➔ Cold Storage). ~3.8% of supply.")
        assert out == "CEX Outflow ($15.2M SHIB: Binance 16 ➔ Cold Storage). ~3.8% of supply."
        out = _strip_hex("Executed at $0.00001820 daily support zone.")
        assert out == "Executed at $0.00001820 daily support zone."

    def test_explorer_urls_built(self):
        data = build_alert_data(TRACE_EVENT, TRACE_ANALYSIS)
        raw = TRACE_EVENT["raw_json"]
        tx = TRACE_EVENT["tx_hash"]
        assert data["tx_url"] == f"https://etherscan.io/tx/{tx}"
        assert data["from_url"] == f"https://etherscan.io/address/{raw['from']}"
        assert data["to_url"] == f"https://etherscan.io/address/{raw['to']}"
