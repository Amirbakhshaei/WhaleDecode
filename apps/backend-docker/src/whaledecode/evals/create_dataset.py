"""LangSmith golden dataset for SMC-thesis regression testing.

Pushes a fixed set of adversarial on-chain scenarios as dataset examples.
Each example carries the simulated event payload, the simulated tool outputs
the agent would receive, and the expected SMC thesis as the reference.
"""

from typing import Any

from langsmith import Client

DATASET_NAME = "WhaleDecode Golden Dataset"
DATASET_DESCRIPTION = (
    "Adversarial SMC edge cases: MEV, flash loans, wash trading, token taxes, and tool timeouts."
)

# Simulated provider responses, keyed by ChainProviderPort method name. These are
# what the graph's tools would return for each case, so the judge can check the
# thesis against ground truth. "Error: Timeout" simulates a tool failure.
GOLDEN_CASES: list[dict[str, Any]] = [
    {
        "name": "mev_sandwich",
        "inputs": {
            "event": {
                "chain": "ETH",
                "tx_hash": "0xMEV1",
                "block_number": 19500000,
                "event_type": "LARGE_TRANSFER",
                "raw_json": {
                    "from": "0xmev_contract",
                    "to": "0xmev_contract",
                    "token": "WETH",
                    "amount": 500,
                    "value_usd": 1500000,
                    "trace": "500 ETH buy then 500 ETH sell by the same contract in the same block",
                },
            },
            "tool_outputs": {
                "trace_call": {
                    "from": "0xmev_contract",
                    "to": "0xmev_contract",
                    "value": hex(int(500 * 10**18)),
                    "type": "CALL",
                },
                "get_token_metadata": {"name": "WETH", "symbol": "WETH", "decimals": 18},
            },
        },
        "outputs": {
            "reference_output": (
                "MEV/Sandwich attack: a single contract bought 500 ETH then sold 500 ETH "
                "in the same block, extracting value around a victim's trade. 0% SMC significance — "
                "this is a bot strategy, not directional smart money."
            ),
        },
    },
    {
        "name": "flash_loan_liquidation",
        "inputs": {
            "event": {
                "chain": "ETH",
                "tx_hash": "0xFL1",
                "block_number": 19510000,
                "event_type": "LARGE_TRANSFER",
                "raw_json": {
                    "from": "0xflash_loan",
                    "to": "0xaave_router",
                    "token": "USDC",
                    "amount": 100000000,
                    "value_usd": 100000000,
                    "trace": "borrow 100M USDC from Aave flash loan, repaid in the same block",
                },
            },
            "tool_outputs": {
                "trace_call": {
                    "from": "0xaave_router",
                    "to": "0xflash_loan",
                    "value": hex(100000000 * 10**6),
                    "type": "CALL",
                },
                "get_token_metadata": {"name": "USD Coin", "symbol": "USDC", "decimals": 6},
            },
        },
        "outputs": {
            "reference_output": (
                "Flash Loan Arbitrage: the $100M USDC transfer is wrapped inside an Aave flash loan "
                "borrow/repay loop, not an institutional spot purchase. No directional SMC — the position "
                "is closed within the same block."
            ),
        },
    },
    {
        "name": "circular_wash_trading",
        "inputs": {
            "event": {
                "chain": "ETH",
                "tx_hash": "0xWASH1",
                "block_number": 19520000,
                "event_type": "LARGE_TRANSFER",
                "raw_json": {
                    "from": "0xA",
                    "to": "0xB",
                    "token": "SHIT",
                    "amount": 10000,
                    "value_usd": 1000,
                    "trace": "transfers route A -> B -> C -> A within one block, circular routing",
                },
            },
            "tool_outputs": {
                "trace_call": {
                    "from": "0xB",
                    "to": "0xC",
                    "value": hex(10000 * 10**18),
                    "type": "CALL",
                },
                "get_token_metadata": {"name": "Shitcoin", "symbol": "SHIT", "decimals": 18},
            },
        },
        "outputs": {
            "reference_output": (
                "Circular wash trading flagged: the token transfers route A -> B -> C -> A within "
                "one block, inflating apparent volume. No genuine SMC — treat volume as fake."
            ),
        },
    },
    {
        "name": "deflationary_token_tax",
        "inputs": {
            "event": {
                "chain": "ETH",
                "tx_hash": "0xTAX1",
                "block_number": 19530000,
                "event_type": "LARGE_TRANSFER",
                "raw_json": {
                    "from": "0xbuyer",
                    "to": "0xseller",
                    "token": "TAX",
                    "amount": 10000,
                    "value_usd": 5000,
                    "trace": "transfer initiated for 10000 tokens, final event shows 9000 received",
                },
            },
            "tool_outputs": {
                "trace_call": {
                    "from": "0xbuyer",
                    "to": "0xseller",
                    "value": hex(int(9000 * 10**18)),
                    "type": "CALL",
                },
                "get_token_metadata": {"name": "TaxToken", "symbol": "TAX", "decimals": 18},
            },
        },
        "outputs": {
            "reference_output": (
                "Fee-on-transfer mechanism: the transfer initiated for 10,000 tokens but the receiver "
                "got 9,000 — a 10% discrepancy. This is a token tax, not missing funds. Low SMC."
            ),
        },
    },
    {
        "name": "api_timeout",
        "inputs": {
            "event": {
                "chain": "ETH",
                "tx_hash": "0xTIMEOUT1",
                "block_number": 19540000,
                "event_type": "LARGE_TRANSFER",
                "raw_json": {
                    "from": "0xwhale",
                    "to": "0xexchange",
                    "token": "WETH",
                    "amount": 2000,
                    "value_usd": 6000000,
                },
            },
            "tool_outputs": {
                "trace_call": "Error: Timeout",
                "get_token_metadata": "Error: Timeout",
            },
        },
        "outputs": {
            "reference_output": (
                "External metrics are unavailable (tool timeout). Base the thesis strictly on the base "
                "blockchain event: a 2000 WETH transfer from a whale to an exchange. Report no external "
                "valuation figures."
            ),
        },
    },
]


def push_golden_dataset(
    client: Client | None = None,
    dataset_name: str = DATASET_NAME,
    description: str = DATASET_DESCRIPTION,
) -> Any:
    """Create the dataset and upload all golden examples via the LangSmith client."""
    client = client or Client()
    client.create_dataset(dataset_name, description=description)
    for case in GOLDEN_CASES:
        client.create_example(
            inputs=case["inputs"],
            outputs=case["outputs"],
            dataset_name=dataset_name,
            metadata={"name": case["name"]},
        )
    return dataset_name


def main() -> None:
    """CLI entrypoint: push the golden dataset to LangSmith."""
    from whaledecode.config.settings import Settings

    Settings().inject_langsmith_env()
    name = push_golden_dataset()
    print(f"Pushed {len(GOLDEN_CASES)} examples to dataset '{name}'")


if __name__ == "__main__":
    main()
