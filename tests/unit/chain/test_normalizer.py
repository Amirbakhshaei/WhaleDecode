from whaledecode.adapters.chain.normalizer import (
    TRANSFER_EVENT_SIGNATURE,
    pad_address_to_topic,
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
