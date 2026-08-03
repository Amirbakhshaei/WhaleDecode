from unittest.mock import MagicMock

from whaledecode.evals.create_dataset import GOLDEN_CASES, push_golden_dataset


def test_golden_dataset_has_five_adversarial_cases() -> None:
    assert len(GOLDEN_CASES) == 5


def test_each_case_carries_event_and_reference() -> None:
    for case in GOLDEN_CASES:
        assert "event" in case["inputs"]
        assert "tool_outputs" in case["inputs"]
        assert "reference_output" in case["outputs"]


def test_timeout_case_expects_no_metrics() -> None:
    timeout = next(c for c in GOLDEN_CASES if c["name"] == "api_timeout")
    ref = timeout["outputs"]["reference_output"].lower()
    for forbidden in ["market cap", "fdv", "liquidity"]:
        assert forbidden not in ref


def test_push_creates_dataset_and_examples() -> None:
    client = MagicMock()
    dataset = MagicMock()
    client.create_dataset.return_value = dataset

    push_golden_dataset(client)

    client.create_dataset.assert_called_once()
    assert client.create_example.call_count == len(GOLDEN_CASES)


def test_mev_case_expects_zero_smc() -> None:
    mev = next(c for c in GOLDEN_CASES if c["name"] == "mev_sandwich")
    assert "sandwich" in mev["outputs"]["reference_output"].lower()
    assert "0% smc" in mev["outputs"]["reference_output"].lower()


def test_flash_loan_rejects_spot_buying() -> None:
    flash = next(c for c in GOLDEN_CASES if c["name"] == "flash_loan_liquidation")
    assert "flash loan" in flash["outputs"]["reference_output"].lower()
    assert "spot buying" not in flash["outputs"]["reference_output"].lower()
