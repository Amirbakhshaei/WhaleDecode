import re

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema


class Address(str):
    PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")

    def __new__(cls, value: str):
        if not cls.PATTERN.match(value):
            raise ValueError(f"Invalid EVM address: {value}")
        return super().__new__(cls, value)

    def short(self, prefix: int = 6, suffix: int = 4) -> str:
        return f"{self[:prefix]}...{self[-suffix:]}"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: type, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
        )

    @classmethod
    def _validate(cls, v: str) -> "Address":
        return cls(v)
