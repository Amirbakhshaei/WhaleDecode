from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.chain.providers.resilient import ResilientChainProvider
from whaledecode.config.settings import Settings
from whaledecode.domain.ports.chain_provider import ChainProviderPort
from whaledecode.infrastructure.rpc_router import split_urls
from whaledecode.pools.rpc.manager import ResilientRPCManager

# ponytail: 15 req / 60 s = 0.25 req/s — same ceiling as the old HttpRpcProvider.
_RATE_LIMIT_PER_SECOND = 15 / 60


def build_resilient_rpc(settings: Settings) -> ResilientRPCManager:
    """Build a ResilientRPCManager from free public RPC URLs in Settings."""
    rpc = ResilientRPCManager(
        breaker_threshold=3,
        cooldown_seconds=settings.TARGETED_RPC_COOLDOWN_SECONDS,
        rate_limit_per_second=_RATE_LIMIT_PER_SECOND,
    )
    for chain_name, attr in [
        ("ethereum", "ETH_PUBLIC_RPC_URLS"),
        ("arbitrum", "ARB_PUBLIC_RPC_URLS"),
        ("base", "BASE_PUBLIC_RPC_URLS"),
    ]:
        raw = getattr(settings, attr, None)
        urls = split_urls(raw)
        if urls:
            rpc.register_chain(chain_name, urls)
    return rpc


def create_chain_provider(
    settings: Settings,
    rpc: ResilientRPCManager | None = None,
) -> ChainProviderPort:
    """Build a ResilientChainProvider from free public RPC URLs.

    If ``rpc`` is provided, reuse it (shared manager). Otherwise create one.
    Falls back to MockChainProvider when no URLs are configured (dev/test).
    """
    if rpc is None:
        rpc = build_resilient_rpc(settings)

    if not rpc.chains():
        return MockChainProvider()

    return ResilientChainProvider(rpc)
