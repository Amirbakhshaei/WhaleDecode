import pytest

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
        assert Chain.ETH == 1
        assert Chain.BASE == 8453
        assert Chain.ARB == 42161

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
