from whaledecode.jobs.poll_wallets import bounded_from_block


class TestBoundedFromBlock:
    def test_clamps_oversized_range(self) -> None:
        assert bounded_from_block(100, 200, 50) == 150

    def test_keeps_range_within_limit(self) -> None:
        assert bounded_from_block(150, 180, 50) == 150

    def test_exact_boundary_unchanged(self) -> None:
        assert bounded_from_block(150, 200, 50) == 150

    def test_from_block_below_to_block(self) -> None:
        assert bounded_from_block(190, 200, 50) == 190
