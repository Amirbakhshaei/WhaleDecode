from typing import Any

from whaledecode.domain.ports.chain_provider import ChainProviderPort


class MockChainProvider(ChainProviderPort):
    async def get_logs(
        self, chain: str, addresses: list[str], from_block: int, to_block: int, topics: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                "address": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
                "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"],
                "data": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "blockNumber": hex(from_block + 1),
                "transactionHash": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "logIndex": "0x0",
            },
            {
                "address": "0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503",
                "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"],
                "data": "0x0000000000000000000000000000000000000000000000000000000000000000",
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
