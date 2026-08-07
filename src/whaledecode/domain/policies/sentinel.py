from typing import Any

WHALE_TRANSFER_THRESHOLD_USD = 100_000
WHALE_SWAP_THRESHOLD_USD = 50_000
ACCUMULATION_WINDOW_SECONDS = 300
SUPER_WHALE_TRANSFER_THRESHOLD_USD = 50_000_000
CURATED_WALLET_BONUS = 10


class SentinelEngine:
    def score(
        self,
        event: dict[str, Any],
        recent_events: list[dict[str, Any]] | None = None,
        curated_wallet_ids: set[int] | None = None,
    ) -> float:
        score = 0.0
        score += self._whale_transfer(event)
        score += self._whale_swap(event)
        score += self._new_contract_interaction(event)
        score += self._large_approval(event)
        if curated_wallet_ids and event.get("wallet_id") in curated_wallet_ids:
            # Tracked wallets get a small boost so a lone whale transfer (40) can
            # cross the 50 gate even without accumulation history nearby.
            score += CURATED_WALLET_BONUS
        if recent_events:
            score += self._accumulation_burst(event, recent_events)
            score += self._multi_wallet_confluence(event, recent_events)
        return min(score, 100.0)

    def _whale_transfer(self, event: dict[str, Any]) -> float:
        if event.get("event_type") == "TRANSFER" and event.get("value_usd", 0) >= WHALE_TRANSFER_THRESHOLD_USD:
            # Ultra-massive transfers base-score above the 50% gate on their own,
            # so a single trade that must cross the on-chain reporting limit is
            # not silently swallowed for want of accumulation history.
            if event.get("value_usd", 0) >= SUPER_WHALE_TRANSFER_THRESHOLD_USD:
                return 60.0
            return 40.0
        return 0.0

    def _whale_swap(self, event: dict[str, Any]) -> float:
        if event.get("event_type") == "SWAP" and event.get("value_usd", 0) >= WHALE_SWAP_THRESHOLD_USD:
            return 35.0
        return 0.0

    def _new_contract_interaction(self, event: dict[str, Any]) -> float:
        if event.get("event_type") == "CONTRACT_INTERACTION":
            return 20.0
        return 0.0

    def _large_approval(self, event: dict[str, Any]) -> float:
        if event.get("event_type") == "APPROVE" and event.get("value_usd", 0) >= 1_000_000:
            return 15.0
        return 0.0

    def _accumulation_burst(self, event: dict[str, Any], recent_events: list[dict[str, Any]]) -> float:
        wallet_id = event.get("wallet_id")
        if not wallet_id:
            return 0.0
        count = sum(1 for e in recent_events if e.get("wallet_id") == wallet_id)
        if count >= 3:
            return 25.0
        if count >= 2:
            return 10.0
        return 0.0

    def _multi_wallet_confluence(self, event: dict[str, Any], recent_events: list[dict[str, Any]]) -> float:
        tx_hash = event.get("tx_hash")
        if not tx_hash:
            return 0.0
        wallets_in_tx = {e.get("wallet_id") for e in recent_events if e.get("tx_hash") == tx_hash}
        if len(wallets_in_tx) >= 2:
            return 30.0
        return 0.0
