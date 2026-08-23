from pydantic import BaseModel
from whaledecode.domain.value_objects.chain import Chain


class CuratedWallet(BaseModel):
    id: int | None = None
    address: str
    chain: Chain
    label: str = ""
    category: str = "Unknown"
    tags: list[str] = []
    quality_score: float = 0.5
    is_active: bool = True
    is_monitored_active: bool = False
    tx_count_30d: int = 0
    last_activity_at: str | None = None
    velocity_penalty: float = 1.0
