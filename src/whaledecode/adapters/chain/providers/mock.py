from typing import Any

from whaledecode.adapters.chain.normalizer import TRANSFER_EVENT_SIGNATURE, pad_address_to_topic
from whaledecode.domain.ports.chain_provider import ChainProviderPort

_TOKENS = ["0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503"]

# Wallet at the center of the mock: padding is what topic-based search matches.
_WALLET = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"


class MockChainProvider(ChainProviderPort):
    async def get_logs(
        self, chain: str, addresses: list[str], from_block: int, to_block: int, topics: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                "address": _TOKENS[0],
                "topics": [TRANSFER_EVENT_SIGNATURE, pad_address_to_topic(_WALLET), None],
                "data": "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000",
                "blockNumber": hex(from_block + 1),
                "transactionHash": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "logIndex": "0x0",
            },
            {
                "address": _TOKENS[0],
                "topics": [TRANSFER_EVENT_SIGNATURE, None, pad_address_to_topic(_TOKENS[0])],
                "data": "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000",
                "blockNumber": hex(to_block),
                "transactionHash": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "logIndex": "0x1",
            },
        ]

    async def get_block_number(self, chain: str) -> int:
        return 20_000_000

    async def get_balance(self, chain: str, address: str) -> str:
        return "0x0"

    async def get_transaction_count(self, chain: str, address: str) -> int:
        return 0

    async def get_token_metadata(self, chain: str, address: str) -> dict[str, Any]:
        return {
            "name": "MockToken",
            "symbol": "MCK",
            "decimals": 18,
            "totalSupply": "1000000000000000000000000",
        }

    async def get_token_balances(self, chain: str, address: str, token_addresses: list[str]) -> dict[str, int]:
        # 1 token (1e18 wei) of each requested token.
        return {token.lower(): 10**18 for token in token_addresses}

    async def trace_call(self, chain: str, tx_hash: str) -> dict[str, Any]:
        return {
            "type": "CALL",
            "from": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
            "to": "0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503",
            "value": "0x56bc75e2d63100000",
            "input": "0x",
            "gas": "0x5208",
            "gasUsed": "0x5208",
        }

    async def close(self) -> None:
        pass
