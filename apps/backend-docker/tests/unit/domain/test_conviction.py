"""Module 3: conviction scorer — pool impact + coordinated accumulation."""
import pytest
from whaledecode.domain.policies.conviction import (
    COORDINATION_BADGE,
    Purchase,
    detect_coordinated_accumulation,
    evaluate_pool_impact,
    pool_impact_ratio,
    score_conviction,
)

NOW = 1_000_000.0


def test_pool_impact_ratio_basic():
    assert pool_impact_ratio(1500, 100_000) == pytest.approx(0.015)
    assert pool_impact_ratio(100, 0) == 0.0  # unknown TVL -> conservative 0


def test_pool_impact_flag_threshold():
    verdict = evaluate_pool_impact(1500, 100_000)
    assert verdict.flagged is True
    below = evaluate_pool_impact(1400, 100_000)
    assert below.flagged is False


def test_micro_cap_buy_flags_despite_small_usd():
    # $8k in a $400k pool absorbs 2% — flagged regardless of raw dollar size.
    assert evaluate_pool_impact(8_000, 400_000).flagged is True


def test_coordination_requires_two_smart_wallets_same_token():
    purchases = [
        Purchase("0xaaa", "0xTOK", "base", NOW - 60),
        Purchase("0xbbb", "0xTOK", "arbitrum", NOW - 120),
        Purchase("0xccc", "0xOTHER", "base", NOW - 30),
    ]
    smart = {"0xAAA", "0xBBB"}
    verdict = detect_coordinated_accumulation(purchases, NOW, smart_wallets=smart)
    assert verdict.coordinated is True
    assert verdict.distinct_wallets == 2
    assert verdict.badge == COORDINATION_BADGE


def test_coordination_ignores_stale_or_non_smart():
    stale = [
        Purchase("0xaaa", "0xTOK", "base", NOW - 3 * 3600),
        Purchase("0xbbb", "0xTOK", "base", NOW - 60),
    ]
    assert detect_coordinated_accumulation(stale, NOW).coordinated is False

    non_smart = [
        Purchase("0xddd", "0xTOK", "base", NOW - 10),
        Purchase("0xeee", "0xTOK", "base", NOW - 20),
    ]
    verdict = detect_coordinated_accumulation(non_smart, NOW, smart_wallets={"0xAAA"})
    assert verdict.coordinated is False


def test_score_conviction_critical_paths():
    coordinated = score_conviction(
        trade_usd=5_000,
        pool_tvl_usd=100_000,
        purchases=[
            Purchase("0xaaa", "0xtok", "base", NOW),
            Purchase("0xbbb", "0xtok", "base", NOW - 1),
        ],
        now_unix=NOW,
        smart_wallets={"0xaaa", "0xbbb"},
    )
    assert coordinated.priority == "CRITICAL"
    assert coordinated.badges and "Coordinated" in coordinated.badges[0]
    ctx = coordinated.to_context()
    assert ctx["coordinated_smart_wallets"] == 2

    solo = score_conviction(5_000, 100_000, [], NOW)
    assert solo.pool_impact_flagged is True
    assert solo.priority == "CRITICAL"
