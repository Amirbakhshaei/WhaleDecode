import pytest
from whaledecode.domain.value_objects.address import EVMAddress, InvalidAddressError, SolanaAddress
from whaledecode.domain.value_objects.chain import Chain
from whaledecode.domain.value_objects.hash import Hash
from whaledecode.domain.value_objects.money import Money


class TestHash:
    def test_valid(self):
        h = Hash("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert h.startswith("0x")
        assert len(h) == 66

    def test_invalid(self):
        with pytest.raises(ValueError):
            Hash("0xshort")

    def test_short_display(self):
        h = Hash("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert h.short() == "0xaaaaaa..."
        assert len(h.short()) == 11


class TestChain:
    def test_values(self):
        assert Chain.ETH == "ETH"
        assert Chain.BASE == "BASE"
        assert Chain.ARB == "ARB"

    def test_lower_never_raises(self):
        assert Chain.ETH.lower() == "eth"
        assert Chain.BASE.lower() == "base"
        assert Chain.ARB.lower() == "arb"

    def test_label(self):
        assert Chain.ETH.label() == "Ethereum"
        assert Chain.BASE.label() == "Base"
        assert Chain.ARB.label() == "Arbitrum"


class TestMoney:
    def test_str_small(self):
        m = Money(value=42.50)
        assert str(m) == "$42.50"

    def test_str_thousands(self):
        m = Money(value=1500)
        assert str(m) == "$1.50K"

    def test_str_millions(self):
        m = Money(value=2_500_000)
        assert str(m) == "$2.50M"

    def test_frozen(self):
        m = Money(value=100)
        with pytest.raises(Exception):
            m.value = 200


class TestEVMAddress:
    def test_valid(self):
        a = EVMAddress("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18")
        assert a == "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"
        assert a.startswith("0x")
        assert len(a) == 42

    def test_invalid(self):
        with pytest.raises(InvalidAddressError):
            EVMAddress("0x123")

    def test_invalid_subclass_of_value_error(self):
        with pytest.raises(ValueError):
            EVMAddress("0x123")


class TestSolanaAddress:
    def test_valid(self):
        a = SolanaAddress("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j")
        assert a == "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j"

    def test_invalid(self):
        with pytest.raises(InvalidAddressError):
            SolanaAddress("0x123")
