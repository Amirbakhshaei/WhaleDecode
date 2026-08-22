import re

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class InvalidAddressError(ValueError):
    """Raised when an address does not match its network family's shape."""


class EVMAddress(str):
    """A checksum-agnostic 20-byte EVM address (0x + 40 hex), lowercased on construction."""

    PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")

    def __new__(cls, value: str) -> "EVMAddress":
        if not cls.PATTERN.match(value):
            raise InvalidAddressError(f"Invalid EVM address: {value}")
        return super().__new__(cls, value.lower())

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: type, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
        )

    @classmethod
    def _validate(cls, v: str) -> "EVMAddress":
        return cls(v)


class SolanaAddress(str):
    """A base58 Solana address (32-44 chars, no ambiguous chars), preserved as-is."""

    PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

    def __new__(cls, value: str) -> "SolanaAddress":
        if not cls.PATTERN.match(value):
            raise InvalidAddressError(f"Invalid Solana address: {value}")
        return super().__new__(cls, value)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: type, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
        )

    @classmethod
    def _validate(cls, v: str) -> "SolanaAddress":
        return cls(v)
