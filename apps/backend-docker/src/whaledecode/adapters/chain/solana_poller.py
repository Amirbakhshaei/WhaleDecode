"""Solana targeted poller: getSignaturesForAddress per curated wallet.

Public Solana RPCs are strict (400ms blocks, low rate ceilings), so requests
are paced with an inter-call sleep and rely on the router's cooldown for 429s
(asynchronous backoff without a bespoke retry ladder).
"""
from typing import Any

import structlog
from whaledecode.adapters.chain.poller import TargetedChainPoller, backoff_sleep
from whaledecode.domain.entities.curated_wallet import CuratedWallet
from whaledecode.infrastructure.rpc_router import RpcFailoverRouter

log = structlog.get_logger()

# Signatures per address per pass — one whale rarely does more in 30s.
_SIGNATURES_PER_ADDRESS = 25
# Pace between per-address calls: well above Solana's slot time, far below
# any public node's per-second ceiling.
_REQUEST_PACE_SECONDS = 0.5

# Base58 pubkey charset: no 0/O/I/l. Guards against corrupt seed rows (EVM
# 0x… addresses stored under chain='SOL') wasting an RPC call each pass.
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {ch: i for i, ch in enumerate(_BASE58_ALPHABET)}


def _base58_decoded_length(address: str) -> int:
    """Byte length of the base58 payload; -1 when any char is invalid."""
    num = 0
    for ch in address:
        idx = _B58_INDEX.get(ch)
        if idx is None:
            return -1
        num = num * 58 + idx
    leading_zeros = len(address) - len(address.lstrip("1"))
    body_len = (num.bit_length() + 7) // 8 if num else 0
    return leading_zeros + body_len


def is_valid_solana_address(address: str) -> bool:
    """True only for well-formed 32-byte base58 pubkeys."""
    if not address or not 32 <= len(address) <= 44:
        return False
    return _base58_decoded_length(address) == 32


class SolanaTargetedPoller(TargetedChainPoller):
    def __init__(self, router: RpcFailoverRouter) -> None:
        self._router = router
        # ponytail: seen-signature sets live in memory only — a restart
        # re-emits the most recent window; dedupe_key absorbs the duplicates.
        self._seen: dict[str, set[str]] = {}

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        return await self._router.post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    async def fetch_recent_activity(self, targets: list[CuratedWallet]) -> list[dict[str, Any]]:
        activities: list[dict[str, Any]] = []
        for wallet in targets:
            if wallet.id is None:
                continue
            if not is_valid_solana_address(wallet.address):
                log.warning("solana_invalid_address_skipped", extra={"address": wallet.address[:10]})
                continue
            try:
                sigs = await self._rpc(
                    "getSignaturesForAddress",
                    [wallet.address, {"limit": _SIGNATURES_PER_ADDRESS}],
                )
            except Exception as e:  # noqa: BLE001 - one dead address must not kill the pass
                log.warning("solana_poll_address_failed", extra={"address": wallet.address[:10], "error": str(e)})
                continue

            seen = self._seen.setdefault(wallet.address, set())
            # getSignaturesForAddress returns newest-first.
            new = [s for s in (sigs or []) if s.get("err") is None and s["signature"] not in seen]
            for entry in new:
                signature = entry["signature"]
                seen.add(signature)
                if len(seen) > 512:  # bound RAM: keep the newest half when the cap is hit
                    seen = set(list(seen)[:256])
                    self._seen[wallet.address] = seen
                activities.append({
                    "wallet_id": wallet.id,
                    "chain": "Solana",
                    "tx_hash": signature,
                    "log_index": 0,
                    "block_number": int(entry.get("slot") or 0),
                    # ponytail: no tx decoding yet — value_usd stays 0 so these
                    # rows score below the alert gate until a decoder lands.
                    # Upgrade path: fetchTransaction → parse SPL transfers → price.
                    "event_type": "ACTIVITY",
                    "raw_json": {"signature": signature, "slot": entry.get("slot")},
                    "score": 0.0,
                    "dedupe_key": f"{wallet.id}:{signature}:0",
                })
            await backoff_sleep(_REQUEST_PACE_SECONDS)

        if targets:
            log.info("solana_poll_complete", extra={"targets": len(targets), "found": len(activities)})
        return activities
