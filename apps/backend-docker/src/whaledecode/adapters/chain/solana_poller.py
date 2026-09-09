"""Solana ingestion: targeted signature polling → parsed transaction delta accounting."""
from typing import Any, Dict, List, Optional
import structlog

from whaledecode.adapters.chain.poller import TargetedChainPoller
from whaledecode.domain.entities.curated_wallet import CuratedWallet

logger = structlog.get_logger("solana_poller")

SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL = 1_000_000_000


class SolanaTargetedPoller(TargetedChainPoller):
    def __init__(self, rpc_router, max_tx_per_poll: int = 15):
        self.router = rpc_router
        self.max_tx_per_poll = max_tx_per_poll
        self.last_signatures: Dict[str, str] = {}

    async def _rpc(self, method: str, params: list) -> Any:
        return await self.router.post("solana", method, params)

    async def fetch_wallet_activity(self, wallet_address: str) -> List[Dict[str, Any]]:
        last_sig = self.last_signatures.get(wallet_address)
        params = [wallet_address, {"limit": self.max_tx_per_poll, "commitment": "confirmed"}]
        if last_sig:
            params[1]["until"] = last_sig

        try:
            signatures_info = await self._rpc("getSignaturesForAddress", params)
        except Exception as e:
            logger.warning("solana_signature_fetch_failed", address=wallet_address[:10], error=str(e))
            return []

        if not signatures_info:
            return []

        self.last_signatures[wallet_address] = signatures_info[0]["signature"]

        activities: List[Dict[str, Any]] = []
        for sig_obj in signatures_info:
            sig = sig_obj.get("signature")
            if sig_obj.get("err"):
                continue
            tx_data = await self._fetch_parsed_transaction(sig)
            if not tx_data:
                continue
            parsed = self._parse_deltas(wallet_address, sig, tx_data)
            if parsed:
                activities.append(parsed)
        return activities

    async def fetch_recent_activity(self, targets: list[CuratedWallet]) -> list[dict[str, Any]]:
        # ponytail: reuse per-wallet fetch; map to interface contract.
        all_activities: list[dict[str, Any]] = []
        for wallet in targets:
            if wallet.id is None:
                continue
            wallet_acts = await self.fetch_wallet_activity(wallet.address)
            for act in wallet_acts:
                all_activities.append({
                    "wallet_id": wallet.id,
                    "wallet_address": wallet.address,
                    "chain": "SOL",
                    "tx_hash": act.get("signature"),
                    "log_index": 0,
                    "block_number": int(act.get("slot") or 0),
                    "event_type": act.get("classification", "TRANSFER"),
                    "value_usd": 0.0,
                    "raw_json": {
                        "signature": act.get("signature"),
                        "sol_delta": act.get("sol_delta"),
                        "token_deltas": act.get("token_deltas"),
                        "classification": act.get("classification"),
                        "slot": act.get("slot"),
                    },
                    "score": 0.0,
                    "dedupe_key": f"{wallet.id}:{act.get('signature')}:0",
                })
        return all_activities

    async def _fetch_parsed_transaction(self, signature: str) -> Optional[Dict[str, Any]]:
        params = [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0,
            },
        ]
        try:
            return await self._rpc("getTransaction", params)
        except Exception as e:
            logger.warning("solana_tx_fetch_failed", signature=signature, error=str(e))
            return None

    def _parse_deltas(self, wallet: str, signature: str, tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        meta = tx.get("meta")
        transaction = tx.get("transaction", {})
        if not meta or not transaction:
            return None

        account_keys = transaction.get("message", {}).get("accountKeys", [])
        pubkeys = [k.get("pubkey") if isinstance(k, dict) else k for k in account_keys]
        if wallet not in pubkeys:
            return None

        wallet_idx = pubkeys.index(wallet)
        pre_lamports = meta.get("preBalances", [])[wallet_idx] if wallet_idx < len(meta.get("preBalances", [])) else 0
        post_lamports = meta.get("postBalances", [])[wallet_idx] if wallet_idx < len(meta.get("postBalances", [])) else 0
        fee = meta.get("fee", 0) if wallet_idx == 0 else 0
        sol_delta = (post_lamports - pre_lamports + fee) / LAMPORTS_PER_SOL

        pre_tokens = {
            t["mint"]: float(t["uiTokenAmount"]["uiAmount"] or 0)
            for t in meta.get("preTokenBalances", [])
            if t.get("owner") == wallet
        }
        post_tokens = {
            t["mint"]: float(t["uiTokenAmount"]["uiAmount"] or 0)
            for t in meta.get("postTokenBalances", [])
            if t.get("owner") == wallet
        }

        all_mints = set(pre_tokens.keys()).union(post_tokens.keys())
        token_deltas = {}
        for mint in all_mints:
            delta = post_tokens.get(mint, 0.0) - pre_tokens.get(mint, 0.0)
            if abs(delta) > 1e-9:
                token_deltas[mint] = delta

        classification = "TRANSFER"
        if sol_delta != 0 and token_deltas:
            classification = "BUY" if sol_delta < 0 else "SELL"
        elif len(token_deltas) >= 2:
            classification = "SWAP"

        return {
            "chain": "SOL",
            "signature": signature,
            "wallet_address": wallet,
            "block_time": tx.get("blockTime"),
            "slot": tx.get("slot"),
            "sol_delta": sol_delta,
            "token_deltas": token_deltas,
            "classification": classification,
            "log_messages": meta.get("logMessages", []),
        }
