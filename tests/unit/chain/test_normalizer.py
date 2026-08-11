from whaledecode.adapters.chain.normalizer import (
    TRANSFER_EVENT_SIGNATURE,
    pad_address_to_topic,
    parse_token_amount,
    transfer_amount,
    wallet_id_from_transfer_topics,
)


class TestPadAddressToTopic:
    def test_pads_20_byte_address_to_32_bytes(self) -> None:
        assert (
            pad_address_to_topic("0x1234567890abcdef0123456789abcdef01234567")
            == "0x0000000000000000000000001234567890abcdef0123456789abcdef01234567"
        )

    def test_output_is_64_hex_chars(self) -> None:
        topic = pad_address_to_topic("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18")
        assert topic.startswith("0x")
        assert len(topic) == 66

    def test_lowercases_mixed_case_address(self) -> None:
        topic = pad_address_to_topic("0xAbCdEf1234567890AbCdEf1234567890AbCdEf12")
        assert topic == "0x000000000000000000000000ABCDEF1234567890ABCDEF1234567890ABCDEF12".lower()


class TestWalletIdFromTransferTopics:
    def test_matches_from_side(self) -> None:
        padded = pad_address_to_topic("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18")
        topics = [TRANSFER_EVENT_SIGNATURE, padded, None]
        assert wallet_id_from_transfer_topics(topics, {padded: 7}) == 7

    def test_matches_to_side(self) -> None:
        padded = pad_address_to_topic("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18")
        topics = [TRANSFER_EVENT_SIGNATURE, None, padded]
        assert wallet_id_from_transfer_topics(topics, {padded: 3}) == 3

    def test_returns_none_when_no_tracked_wallet(self) -> None:
        topics = [TRANSFER_EVENT_SIGNATURE, "0x0000000000000000000000000000000000000000000000000000000000112233", None]
        assert wallet_id_from_transfer_topics(topics, {"0x" + "00" * 64: 1}) is None


class TestParseTokenAmount:
    def test_scales_by_contract_decimals(self) -> None:
        # 10,000,000 raw units of a 6-decimal token = 10.0 (USDT/USDC), not 10^12× more.
        assert parse_token_amount("0x989680", 6) == 10.0
        assert parse_token_amount("0x989680", 18) == 10_000_000.0 / 1e18

    def test_handles_empty_and_zero_hex(self) -> None:
        assert parse_token_amount("", 6) == 0.0
        assert parse_token_amount("0x", 18) == 0.0
        assert parse_token_amount("0x0", 6) == 0.0

    def test_garbage_returns_zero(self) -> None:
        assert parse_token_amount("not-hex", 18) == 0.0

    def test_transfer_amount_uses_parse_with_default_18(self) -> None:
        raw_log = {"data": hex(int(1.5 * 10**18))}
        assert transfer_amount(raw_log) == 1.5
        assert transfer_amount(raw_log, decimals=18) == 1.5
