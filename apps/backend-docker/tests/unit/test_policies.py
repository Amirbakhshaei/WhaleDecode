from whaledecode.domain.policies.event_weights import EVENT_TYPE_WEIGHTS
from whaledecode.domain.policies.scoring import TIER_THRESHOLDS, calculate_alert_worthiness


class TestEventWeights:
    def test_known_types(self):
        assert EVENT_TYPE_WEIGHTS["LARGE_STABLECOIN_TRANSFER"] == 0.8
        assert EVENT_TYPE_WEIGHTS["NEW_TOKEN_DEPLOYMENT"] == 0.85
        assert EVENT_TYPE_WEIGHTS["DUST_SPAM"] == 0.05

    def test_unknown_type_default(self):
        assert EVENT_TYPE_WEIGHTS.get("UNKNOWN", 0.1) == 0.1


class TestScoring:
    def test_high_confidence(self):
        score = calculate_alert_worthiness(
            confidence=0.9,
            novelty_score=0.8,
            wallet_quality=0.9,
            event_type_weight=0.8,
        )
        assert 0.8 <= score <= 1.0

    def test_low_confidence(self):
        score = calculate_alert_worthiness(
            confidence=0.1,
            novelty_score=0.1,
            wallet_quality=0.1,
            event_type_weight=0.1,
        )
        assert 0.0 <= score <= 0.2

    def test_clamped(self):
        score = calculate_alert_worthiness(
            confidence=2.0,
            novelty_score=2.0,
            wallet_quality=2.0,
            event_type_weight=2.0,
        )
        assert score == 1.0

    def test_tier_thresholds(self):
        assert TIER_THRESHOLDS["free"] >= TIER_THRESHOLDS["pro"] >= TIER_THRESHOLDS["whale"]
