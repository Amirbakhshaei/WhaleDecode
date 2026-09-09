import time
from typing import Dict, Optional, Tuple, Any
import httpx
import structlog

logger = structlog.get_logger("solana_valuation")

WSOL_MINT = "So11111111111111111111111111111111111111112"

class SolanaValuationService:
    def __init__(self, floor_usd: float = 50_000.0):
        self.floor_usd = floor_usd
        self.price_cache: Dict[str, Tuple[float, float]] = {}
        self._http = httpx.AsyncClient(timeout=5.0)

    async def get_token_price_usd(self, mint: str) -> float:
        now = time.time()
        if mint in self.price_cache:
            price, expiry = self.price_cache[mint]
            if now < expiry:
                return price
        try:
            url = f"https://api.jup.ag/price/v2?ids={mint}"
            resp = await self._http.get(url)
            if resp.status_code == 200:
                data = resp.json()
                price_str = data.get("data", {}).get(mint, {}).get("price")
                if price_str:
                    price = float(price_str)
                    self.price_cache[mint] = (price, now + 60.0)
                    return price
        except Exception as e:
            logger.debug("jupiter_price_failed", mint=mint[:8], error=str(e))
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            resp = await self._http.get(url)
            if resp.status_code == 200:
                pairs = resp.json().get("pairs", [])
                if pairs:
                    price = float(pairs[0].get("priceUsd", 0.0))
                    self.price_cache[mint] = (price, now + 60.0)
                    return price
        except Exception as e:
            logger.debug("dexscreener_price_failed", mint=mint[:8], error=str(e))
        return 0.0

    async def evaluate_activity(self, activity: dict) -> Tuple[bool, float, Dict[str, Any]]:
        sol_price = await self.get_token_price_usd(WSOL_MINT)
        sol_volume_usd = abs(activity.get("sol_delta", 0)) * sol_price
        tokens_volume_usd = 0.0
        token_details = []
        for mint, delta in (activity.get("token_deltas") or {}).items():
            t_price = await self.get_token_price_usd(mint)
            usd_val = abs(delta) * t_price
            tokens_volume_usd += usd_val
            token_details.append({"mint": mint, "delta": delta, "price_usd": t_price, "usd_value": usd_val})
        calculated_value_usd = max(sol_volume_usd, tokens_volume_usd)
        gate_passed = calculated_value_usd >= self.floor_usd
        meta = {
            "sol_price": sol_price,
            "calculated_value_usd": round(calculated_value_usd, 2),
            "floor_usd": self.floor_usd,
            "gate_passed": gate_passed,
            "tokens": token_details,
        }
        return gate_passed, calculated_value_usd, meta
