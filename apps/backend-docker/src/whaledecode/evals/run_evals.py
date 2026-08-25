"""Run the golden dataset against the compiled reasoner and print the LangSmith URL."""

import json
import sys
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langsmith import Client, evaluate
from whaledecode.adapters.chain.providers.mock import MockChainProvider
from whaledecode.adapters.llm.factory import LLMFactory
from whaledecode.adapters.llm_graph.graphs.investigation_graph import build_investigation_graph
from whaledecode.config.settings import Settings
from whaledecode.domain.ports.chain_provider import ChainProviderPort
from whaledecode.evals.create_dataset import DATASET_NAME
from whaledecode.evals.evaluators import heuristic_formatting_evaluator, make_smc_judge


class ScriptedChainProvider:
    """Serves canned per-case provider responses so the model sees the simulated tool outputs."""

    def __init__(self, tool_outputs: dict[str, Any]) -> None:
        self._tool_outputs = tool_outputs

    def _get(self, method: str, default: Any) -> Any:
        value = self._tool_outputs.get(method, default)
        if isinstance(value, str) and value.startswith("Error:"):
            raise TimeoutError(value)
        return value

    async def get_logs(
        self, chain: str, addresses: list[str], from_block: int, to_block: int, topics: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def get_block_number(self, chain: str) -> int:
        return 20_000_000

    async def get_balance(self, chain: str, address: str) -> str:
        return str(self._get("get_balance", "0x0"))

    async def get_transaction_count(self, chain: str, address: str) -> int:
        return int(self._get("get_transaction_count", 0))

    async def get_token_metadata(self, chain: str, address: str) -> dict[str, Any]:
        return self._get("get_token_metadata", {})

    async def trace_call(self, chain: str, tx_hash: str) -> dict[str, Any]:
        return self._get("trace_call", {})

    async def close(self) -> None:
        pass


def build_target(llm: BaseChatModel, provider: ChainProviderPort | None = None):
    """Wrap the compiled investigation graph as a LangSmith target taking example inputs."""
    default_provider = provider or MockChainProvider()

    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        event = inputs.get("event", {})
        provider_for_case = (
            ScriptedChainProvider(inputs.get("tool_outputs", {})) if inputs.get("tool_outputs") else default_provider
        )
        graph = build_investigation_graph(llm, provider_for_case)
        state = await graph.ainvoke(
            {
                "event_data": event,
                "messages": [HumanMessage(content=json.dumps(event, default=str))],
            }
        )
        return {
            "summary": state.get("summary", ""),
            "thesis": state.get("thesis", ""),
            "risk_score": state.get("risk_score", 0.0),
            "is_safe": state.get("is_safe", True),
        }

    return target


def collect_failures(results) -> list[dict[str, Any]]:
    """Return every evaluator score below the full-mark threshold (1.0)."""
    failures = []
    for row in results:
        for r in row["evaluation_results"]["results"]:
            score = r.score
            if score is not None and score < 1.0:
                failures.append({"key": r.key, "score": score})
    return failures


def run_evals(client: Client | None = None, llm: BaseChatModel | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Run the golden dataset against the compiled reasoner.

    Returns the experiment URL and any evaluator scores below the full-mark
    threshold, so callers can strictly block on a 100% pass.
    """
    client = client or Client()
    llm = llm or LLMFactory(Settings()).get_heavy_reasoning_llm()
    results = evaluate(
        build_target(llm),
        data=DATASET_NAME,
        evaluators=[
            heuristic_formatting_evaluator,
            make_smc_judge(llm),
        ],
        client=client,
        experiment_prefix="smc-golden",
    )
    url = results.url
    failures = collect_failures(results)
    print(f"Experiment URL: {url}")
    if failures:
        print("Evaluation FAILED — scores below threshold:")
        for f in failures:
            print(f"  - {f['key']}: {f['score']}")
    return url, failures


def main() -> None:
    """CLI entrypoint for running the evals. Exits non-zero on any sub-100% score."""
    settings = Settings()
    settings.inject_langsmith_env()
    _, failures = run_evals()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
