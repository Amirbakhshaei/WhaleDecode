from whaledecode.config.tiers import PlanTier, get_limits


class TestPlanTier:
    def test_from_str_free(self) -> None:
        assert PlanTier.from_str("free") == PlanTier.FREE

    def test_from_str_paid(self) -> None:
        assert PlanTier.from_str("paid") == PlanTier.PAID

    def test_from_str_unknown_defaults_to_free(self) -> None:
        assert PlanTier.from_str("unknown") == PlanTier.FREE

    def test_from_str_empty_string(self) -> None:
        assert PlanTier.from_str("") == PlanTier.FREE


class TestGetLimits:
    def test_free_limits(self) -> None:
        limits = get_limits("free")
        assert limits.chat_per_day == 5
        assert limits.max_tracked_wallets == 3
        assert limits.alert_immediacy == "batch"
        assert limits.briefing_on_demand is False

    def test_paid_limits(self) -> None:
        limits = get_limits("paid")
        assert limits.chat_per_day == 50
        assert limits.max_tracked_wallets == 100
        assert limits.alert_immediacy == "instant"
        assert limits.briefing_on_demand is True

    def test_unknown_plan_gets_free_limits(self) -> None:
        limits = get_limits("unknown")
        assert limits.chat_per_day == 5
