"""RPC failover router: round-robin over free public nodes with cooldown penalties.

Sole owner of transport concerns (HTTP, status codes, timeouts). Callers see a
single ``post()`` that either returns a JSON-RPC result or raises — network
volatility never leaks into chain adapters.

Demonstrates the Circuit Breaker pattern per node: a failing endpoint is
flagged with a temporary cooldown and skipped, then automatically retried
after the penalty expires. No health-check thread needed — real traffic is
the probe.
"""
import os
import time
from typing import Any, Dict, List, Optional

import httpx
import structlog

logger = structlog.get_logger("rpc_router")


def _parse_env_urls(env_var: str) -> List[str]:
    raw = os.getenv(env_var, "").strip()
    return [url.strip() for url in raw.split(",") if url.strip()]


# Status codes meaning "this node is unhealthy/rate-limited for us" → failover.
# 520-524: Cloudflare-origin failures (llamarpc et al. return bare 521s).
_FAILOVER_STATUS = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}

# JSON-RPC error codes meaning "this node won't/can't serve this request"
# (capacity, tier restriction, method gating, internal server failure) rather
# than "our params are wrong" → treat the node as unavailable for now and
# rotate. -32603 is the JSON-RPC spec's "server-side internal error".
# -32001: 1rpc.io usage limit exceeded (free tier)
_NODE_CAPACITY_CODES = {-32046, -32701, -32005, -32603, -32001}
_CAPACITY_MESSAGE_HINTS = (
    "cannot fulfill",
    "rate limit",
    "too many requests",
    "usage limit",
    "specify an address",
    "dedicated full node",
    "exceeded",
)


def _is_node_capacity_error(err: dict) -> bool:
    if err.get("code") in _NODE_CAPACITY_CODES:
        return True
    message = str(err.get("message", "")).lower()
    return any(hint in message for hint in _CAPACITY_MESSAGE_HINTS)


def to_int(val: Any) -> int:
    """Safe conversion of JSON-RPC scalars (hex str, decimal str, or int).

    Also handles dict responses (error payloads or wrapped results) by extracting
    the 'result' field or raising ConnectionError for error payloads.
    """
    if isinstance(val, bool):
        raise TypeError("Cannot convert bool to int")
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        try:
            return int(val, 16) if val.startswith("0x") else int(val)
        except ValueError:
            raise TypeError(f"Cannot convert string '{val}' to int")
    if isinstance(val, dict):
        # Handle cases where provider wraps data or returns error payload
        if "error" in val or "code" in val:
            raise ConnectionError(f"RPC returned error payload: {val}")
        if "result" in val:
            return to_int(val["result"])
    raise TypeError(f"Cannot convert {type(val)} to int")


class RpcNodesExhaustedError(RuntimeError):
    """Every node in the array failed or is cooling down."""


class CapabilityAwareRpcRouter:
    """Method-aware RPC router with dedicated/public tier selection.

    * ``dedicated`` nodes (Alchemy/Infura/dRPC/Ankr from env) handle
      ``eth_getLogs`` so public nodes never return ``-32701``.
    * ``public`` nodes serve basic methods (``eth_blockNumber``,
      ``eth_getTransactionReceipt``) to preserve paid CU quotas.
    * Purged: all ``publicnode.com`` URLs.
    """

    def __init__(self, *args, **kwargs):
        # Backward-compat: swallow old (name, urls, ...) positional args
        self._name = kwargs.get("name") or (args[0] if args else "default")

        # 1. Load authenticated providers for Ethereum from environment
        eth_auth = _parse_env_urls("ETH_RPC_URLS") or _parse_env_urls("ETHEREUM_RPC_URL")

        # 2. Build structured chain pools (dedicated = log-capable, public = fallback)
        self.pools: Dict[str, Dict[str, List[dict]]] = {
            "ethereum": {
                "dedicated": [
                    {"url": u, "failures": 0, "cooldown": 0.0, "name": f"eth_auth_{i}"}
                    for i, u in enumerate(eth_auth)
                ],
                "public": [
                    {"url": "https://rpc.mevblocker.io", "failures": 0, "cooldown": 0.0, "name": "eth_mevblocker"},
                    {"url": "https://eth.llamarpc.com", "failures": 0, "cooldown": 0.0, "name": "eth_llama"},
                ],
            },
            "base": {
                "dedicated": [
                    {"url": u, "failures": 0, "cooldown": 0.0, "name": f"base_auth_{i}"}
                    for i, u in enumerate(_parse_env_urls("BASE_RPC_URLS"))
                ],
                "public": [
                    {"url": "https://mainnet.base.org", "failures": 0, "cooldown": 0.0, "name": "base_foundation"},
                    {"url": "https://base.drpc.org", "failures": 0, "cooldown": 0.0, "name": "base_drpc"},
                    {"url": "https://base.llamarpc.com", "failures": 0, "cooldown": 0.0, "name": "base_llama"},
                ],
            },
            "arbitrum": {
                "dedicated": [
                    {"url": u, "failures": 0, "cooldown": 0.0, "name": f"arb_auth_{i}"}
                    for i, u in enumerate(_parse_env_urls("ARB_RPC_URLS"))
                ],
                "public": [
                    {"url": "https://arb1.arbitrum.io/rpc", "failures": 0, "cooldown": 0.0, "name": "arb_foundation"},
                    {"url": "https://arbitrum.drpc.org", "failures": 0, "cooldown": 0.0, "name": "arb_drpc"},
                    {"url": "https://arbitrum.llamarpc.com", "failures": 0, "cooldown": 0.0, "name": "arb_llama"},
                ],
            },
        }

        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        self._rr_indices = {chain: 0 for chain in self.pools}

    def _get_eligible_nodes(self, chain: str, method: str) -> List[dict]:
        chain_pool = self.pools.get(chain.lower(), {})
        now = time.time()

        # eth_getLogs REQUIRES dedicated nodes if available to prevent -32701
        if method == "eth_getLogs":
            candidates = chain_pool.get("dedicated", [])
            # If no dedicated nodes configured for chain, fallback to public foundation nodes
            if not candidates:
                candidates = chain_pool.get("public", [])
        else:
            # Basic methods (eth_blockNumber) prioritize public nodes to preserve paid CUs
            candidates = chain_pool.get("public", []) + chain_pool.get("dedicated", [])

        # Filter out nodes currently in cooldown
        available = [n for n in candidates if n["cooldown"] <= now]
        if not available and candidates:
            # If all are cooling down, select the node that clears earliest
            earliest = min(candidates, key=lambda n: n["cooldown"])
            return [earliest]

        return available

    def _penalize_node(self, node: dict, reason: str):
        node["failures"] += 1
        # Exponential backoff capped at 5 minutes
        duration = min(300.0, 10.0 * (1.5 ** (node["failures"] - 1)))
        node["cooldown"] = time.time() + duration
        logger.warning("rpc_node_cooldown", node=node["name"], duration=duration, reason=reason)

    async def _post_impl(self, chain: str, method: str, params: list) -> Any:
        chain_key = chain.lower()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        nodes = self._get_eligible_nodes(chain_key, method)

        if not nodes:
            raise RuntimeError(f"{chain}: no operational nodes available for method {method}")

        last_error = None
        for _ in range(len(nodes)):
            # Weighted round-robin across available nodes
            idx = self._rr_indices[chain_key] % len(nodes)
            node = nodes[idx]
            self._rr_indices[chain_key] = (idx + 1) % len(nodes)

            try:
                resp = await self._client.post(node["url"], json=payload)
                if resp.status_code != 200:
                    self._penalize_node(node, f"HTTP {resp.status_code}")
                    last_error = f"HTTP {resp.status_code}"
                    continue

                data = resp.json()
                if "error" in data:
                    err = data["error"]
                    err_code = err.get("code")
                    err_msg = err.get("message", "")

                    # Reject nodes that require an address for log queries
                    if err_code == -32701:
                        self._penalize_node(node, "RPC -32701: Contract address required")
                    else:
                        self._penalize_node(node, f"RPC {err_code}: {err_msg}")

                    last_error = err_msg
                    continue

                # Successful execution: reset failure counter
                node["failures"] = 0
                return data.get("result")

            except Exception as e:
                self._penalize_node(node, type(e).__name__)
                last_error = str(e)

        raise RuntimeError(f"{chain}: all nodes failed for {method}. Last error: {last_error}")

    # Backward-compatible wrapper for existing pollers (payload dict interface)
    async def post(self, chain_or_payload, method=None, params=None) -> Any:
        if isinstance(chain_or_payload, dict):
            payload = chain_or_payload
            method = payload.get("method")
            params = payload.get("params", [])
            chain = getattr(self, "_name", None) or "ethereum"
            return await self._post_impl(chain, method, params)
        else:
            return await self._post_impl(str(chain_or_payload), method, params or [])

    # New explicit interface
    async def call(self, chain: str, method: str, params: list) -> Any:
        return await self._post_impl(chain, method, params)

    async def aclose(self):
        await self._client.aclose()


# Backward-compat alias for existing imports
RpcFailoverRouter = CapabilityAwareRpcRouter


def split_urls(raw: str | None) -> list[str]:
    """Comma-separated env string -> clean URL list."""
    return [u.strip() for u in (raw or "").split(",") if u.strip()]
