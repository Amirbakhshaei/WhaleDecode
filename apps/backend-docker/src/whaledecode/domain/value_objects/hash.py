import re

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class Hash(str):
    PATTERN = re.compile(r"^0x[a-fA-F0-9]{64}$")

    def __new__(cls, value: str):
        if not cls.PATTERN.match(value):
            raise ValueError(f"Invalid 32-byte hash: {value}")
        return super().__new__(cls, value)

    def short(self, prefix: int = 8) -> str:
        return f"{self[:prefix]}..."

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: type, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
        )

    @classmethod
    def _validate(cls, v: str) -> "Hash":
        return cls(v)
