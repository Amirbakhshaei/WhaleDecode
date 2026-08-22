from whaledecode.adapters.chain.providers.http_rpc import HttpRpcProvider
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.config.settings import Settings
from whaledecode.domain.ports.chain_provider import ChainProviderPort


def create_chain_provider(settings: Settings) -> ChainProviderPort:
    urls = {
        "ETH": settings.ETH_RPC_URL,
        "ARB": settings.ARB_RPC_URL,
        "BASE": settings.BASE_RPC_URL,
    }
    urls = {chain: url for chain, url in urls.items() if url}
    if not urls:
        return MockChainProvider()
    return HttpRpcProvider(urls)
