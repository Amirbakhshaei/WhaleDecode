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

# Solana-specific: these are valid "not found" responses, NOT node failures.
# -32020: Transaction not found
# -32011: Transaction history not available from this node
_NON_PENALTY_CODES = {-32020, -32011}


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
        # Backward-compat: accept old signature (name, urls, cooldown_seconds, timeout)
        # and new signature (name=..., urls=..., cooldown_seconds=..., timeout=...)
        self._name = kwargs.get("name") or (args[0] if args else "default")
        custom_urls = kwargs.get("urls") or (args[1] if len(args) > 1 else None)
        custom_cooldown = kwargs.get("cooldown_seconds") or (args[2] if len(args) > 2 else None)
        custom_timeout = kwargs.get("timeout") or (args[3] if len(args) > 3 else None)

        # 1. Load authenticated providers for each chain from environment
        eth_auth = _parse_env_urls("ETH_RPC_URLS") or _parse_env_urls("ETHEREUM_RPC_URL")
        base_auth = _parse_env_urls("BASE_RPC_URLS")
        arb_auth = _parse_env_urls("ARB_RPC_URLS")
        sol_auth = _parse_env_urls("SOL_RPC_URLS") or _parse_env_urls("SOLANA_RPC_URL")

        # 2. If custom URLs provided, use them for the router's chain (backward compat)
        #    Detect which chain the custom URLs belong to by name or default to ethereum
        chain_key = self._name.lower()
        custom_overrides_known_chain = False
        if custom_urls:
            # Replace the appropriate chain's pools with the custom URLs
            # Split into dedicated/public if possible, otherwise use as dedicated
            custom_nodes = [
                {"url": u, "failures": 0, "cooldown": 0.0, "name": f"{chain_key}_custom_{i}"}
                for i, u in enumerate(custom_urls)
            ]
            # Override the pool for this chain
            if chain_key in ("ethereum", "eth"):
                eth_auth = custom_urls
                custom_overrides_known_chain = True
            elif chain_key in ("base",):
                base_auth = custom_urls
                custom_overrides_known_chain = True
            elif chain_key in ("arbitrum", "arb"):
                arb_auth = custom_urls
                custom_overrides_known_chain = True
            elif chain_key in ("solana", "sol"):
                sol_auth = custom_urls
                custom_overrides_known_chain = True
            else:
                # Unknown chain - add as new pool
                pass

        # Build structured chain pools (dedicated = log-capable, public = fallback)
        self.pools: Dict[str, Dict[str, List[dict]]] = {
            "ethereum": {
                "dedicated": [
                    {"url": u, "failures": 0, "cooldown": 0.0, "name": f"eth_auth_{i}"}
                    for i, u in enumerate(eth_auth)
                ],
                "public": [
                    {"url": "https://rpc.mevblocker.io", "failures": 0, "cooldown": 0.0, "name": "eth_mevblocker"},
                    {"url": "https://rpc.ankr.com/eth", "failures": 0, "cooldown": 0.0, "name": "eth_ankr"},
                ],
            },
            "base": {
                "dedicated": [
                    {"url": u, "failures": 0, "cooldown": 0.0, "name": f"base_auth_{i}"}
                    for i, u in enumerate(base_auth)
                ],
                "public": [
                    {"url": "https://mainnet.base.org", "failures": 0, "cooldown": 0.0, "name": "base_foundation"},
                    {"url": "https://developer-access-mainnet.base.org", "failures": 0, "cooldown": 0.0, "name": "base_dev"},
                ],
            },
            "arbitrum": {
                "dedicated": [
                    {"url": u, "failures": 0, "cooldown": 0.0, "name": f"arb_auth_{i}"}
                    for i, u in enumerate(arb_auth)
                ],
                "public": [
                    {"url": "https://arb1.arbitrum.io/rpc", "failures": 0, "cooldown": 0.0, "name": "arb_foundation"},
                ],
            },
            "solana": {
                "dedicated": [
                    {"url": u, "failures": 0, "cooldown": 0.0, "name": f"sol_auth_{i}"}
                    for i, u in enumerate(sol_auth)
                ],
                "public": [
                    {"url": "https://api.mainnet-beta.solana.com", "failures": 0, "cooldown": 0.0, "name": "sol_foundation"},
                    {"url": "https://solana.api.pocket.network", "failures": 0, "cooldown": 0.0, "name": "sol_pocket"},
                ],
            },
        }

        # If custom URLs override a known chain, clear its public pool (tests expect only custom nodes)
        if custom_overrides_known_chain:
            self.pools[chain_key]["public"] = []

        # Add custom chain pool if needed (for backward compat with tests)
        if custom_urls and chain_key not in ("ethereum", "eth", "base", "arbitrum", "arb", "solana", "sol"):
            custom_nodes = [
                {"url": u, "failures": 0, "cooldown": 0.0, "name": f"{chain_key}_custom_{i}"}
                for i, u in enumerate(custom_urls)
            ]
            self.pools[chain_key] = {"dedicated": custom_nodes, "public": []}

        # Custom headers prevent Cloudflare 403/525 drops on public Solana nodes
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout_val = custom_timeout or 15.0
        self._client = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(timeout_val, connect=5.0))
        self._rr_indices = {chain: 0 for chain in self.pools}
        logger.info("rpc_router_initialized", chains=list(self.pools.keys()))

    def _get_eligible_nodes(self, chain: str, method: str) -> List[dict]:
        chain_pool = self.pools.get(chain.lower(), {})
        now = time.time()

        # EVM eth_getLogs requires dedicated indexers; Solana/basic EVM use both tiers
        if method == "eth_getLogs":
            candidates = chain_pool.get("dedicated", []) or chain_pool.get("public", [])
        else:
            # Solana and basic EVM calls can use both public and dedicated pools
            candidates = chain_pool.get("dedicated", []) + chain_pool.get("public", [])

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
                    elif err_code in _NON_PENALTY_CODES:
                        # Valid "not found" response — don't penalize the node
                        last_error = err_msg
                        continue
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

        raise RpcNodesExhaustedError(f"{chain}: all nodes failed for {method}. Last error: {last_error}")

    # Backward-compat properties for ResilientRPCManager
    @property
    def _urls(self) -> list[str]:
        """All URLs for this router's chain (for budget tracking)."""
        chain_pool = self.pools.get(self._name.lower(), {})
        urls = []
        for tier in chain_pool.values():
            urls.extend(n["url"] for n in tier)
        return urls

    @property
    def _cooldown_until(self) -> dict[str, float]:
        """Mapping of URL -> cooldown timestamp (for budget tracking)."""
        chain_pool = self.pools.get(self._name.lower(), {})
        result = {}
        for tier in chain_pool.values():
            for node in tier:
                if node["cooldown"] > time.time():
                    result[node["url"]] = node["cooldown"]
        return result

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
