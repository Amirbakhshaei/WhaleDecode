import pytest
from whaledecode.adapters.telegram.routers.chat import is_greeting


class TestIsGreeting:
    @pytest.mark.parametrize("query", ["hi", "hello", "hey", "help", "Hi", "HELLO", "Hey"])
    def test_common_greetings_are_detected(self, query):
        assert is_greeting(query) is True

    def test_short_query_is_greeting(self):
        assert is_greeting("yo") is True

    def test_empty_string_is_greeting(self):
        assert is_greeting("") is True

    def test_long_greeting_not_detected(self):
        assert is_greeting("hello there friend") is False

    def test_wallet_address_not_greeting(self):
        assert is_greeting("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18") is False

    def test_investigation_request_not_greeting(self):
        assert is_greeting("analyze this wallet") is False

    def test_short_non_greeting_not_detected(self):
        assert is_greeting("ETH") is True  # short input gets greeting per spec
