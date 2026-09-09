def format_solana_alert(event: dict, evaluation: dict, reasoning: dict) -> str:
    wallet = event.get("wallet_address", "")
    short_wallet = f"{wallet[:4]}...{wallet[-4:]}" if len(wallet) > 8 else wallet
    sig = event.get("signature", "")
    short_sig = f"{sig[:6]}...{sig[-4:]}" if len(sig) > 10 else sig
    val_usd = evaluation.get("calculated_value_usd", 0)
    classification = event.get("classification", "ACTIVITY")
    emoji = "🟢" if classification == "BUY" else ("🔴" if classification == "SELL" else "🔄")
    token_str = ""
    for t in evaluation.get("tokens", []):
        mint = t.get("mint", "")
        short_mint = f"{mint[:4]}...{mint[-4:]}" if len(mint) > 8 else mint
        token_str += f"• `{t.get('delta', 0):+,.2f}` [{short_mint}](https://dexscreener.com/solana/{mint}) (${t.get('usd_value', 0):,.2f})\n"
    msg = (
        f"{emoji} *SOLANA WHALE {classification}*\n\n"
        f"💰 *Total Value:* `${val_usd:,.2f}`\n"
        f"👤 *Wallet:* [`{short_wallet}`](https://solscan.io/account/{wallet})\n"
        f"🧭 *Action:* {event.get('dex', 'DEX Trade')}\n"
        f"🎯 *Conviction Score:* `{reasoning.get('conviction_score', 85)}/100`\n\n"
        f"*Token Flow:*\n{token_str}\n"
        f"💡 *Intelligence Analysis:*\n_{reasoning.get('summary', 'Smart money activity detected.')}_\n\n"
        f"🔗 [Solscan](https://solscan.io/tx/{sig}) | "
        f"[DexScreener](https://dexscreener.com/solana/{wallet}) | "
        f"[Photon](https://photon-sol.tinyastro.io/en/lp/{wallet})"
    )
    return msg
