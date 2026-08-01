from whaledecode.jobs.poll_wallets import bounded_from_block, max_block_range_for

MAX_RANGES = {"Ethereum": 5, "Base": 30, "Arbitrum": 100}


class TestBoundedFromBlock:
    def test_clamps_oversized_range(self) -> None:
        assert bounded_from_block(100, 200, 50) == 150

    def test_keeps_range_within_limit(self) -> None:
        assert bounded_from_block(150, 180, 50) == 150

    def test_exact_boundary_unchanged(self) -> None:
        assert bounded_from_block(150, 200, 50) == 150

    def test_from_block_below_to_block(self) -> None:
        assert bounded_from_block(190, 200, 50) == 190


class TestMaxBlockRangeFor:
    def test_ethereum_limit(self) -> None:
        assert max_block_range_for("Ethereum", MAX_RANGES) == 5

    def test_base_limit(self) -> None:
        assert max_block_range_for("Base", MAX_RANGES) == 30

    def test_arbitrum_limit(self) -> None:
        assert max_block_range_for("Arbitrum", MAX_RANGES) == 100

    def test_unknown_chain_falls_back(self) -> None:
        assert max_block_range_for("Solana", MAX_RANGES) == 5
