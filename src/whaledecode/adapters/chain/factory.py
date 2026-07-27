from whaledecode.adapters.chain.multi_provider import MultiChainProvider
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.config.settings import Settings
from whaledecode.domain.ports.chain_provider import ChainProviderPort


def create_chain_provider(settings: Settings) -> ChainProviderPort:
    if not settings.DRPC_API_KEY:
        return MockChainProvider()
    providers: list[ChainProviderPort] = []
    if settings.DRPC_API_KEY:
        from whaledecode.adapters.chain.providers.http_rpc import HttpRpcProvider
        providers.append(HttpRpcProvider(settings.DRPC_API_KEY.get_secret_value()))
    return MultiChainProvider(providers)
