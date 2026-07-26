from typing import Any

import structlog

from whaledecode.domain.ports.chain_provider import ChainProviderPort


class MultiChainProvider(ChainProviderPort):
    def __init__(self, providers: list[ChainProviderPort]) -> None:
        self._providers = providers
        self._current = 0
        self._log = structlog.get_logger()

    async def get_logs(
        self, chain: str, addresses: list[str], from_block: int, to_block: int, topics: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return await self._try_all("get_logs", chain, addresses=addresses, from_block=from_block, to_block=to_block, topics=topics)

    async def get_block_number(self, chain: str) -> int:
        return await self._try_all("get_block_number", chain)

    async def get_token_metadata(self, chain: str, address: str) -> dict[str, Any]:
        result = await self._try_all("get_token_metadata", chain, address=address)
        return result if isinstance(result, dict) else {}

    async def trace_call(self, chain: str, tx_hash: str) -> dict[str, Any]:
        result = await self._try_all("trace_call", chain, tx_hash=tx_hash)
        return result if isinstance(result, dict) else {}

    async def close(self) -> None:
        for p in self._providers:
            if hasattr(p, "close"):
                await p.close()

    async def _try_all(self, method: str, chain: str, **kwargs: Any) -> Any:
        for i, provider in enumerate(self._providers):
            try:
                result = await getattr(provider, method)(chain, **kwargs)
                self._current = i
                return result
            except Exception as e:
                self._log.warning("provider_failover", method=method, provider_index=i, error=str(e))
                continue
        raise RuntimeError(f"All {len(self._providers)} providers failed for {method}")
