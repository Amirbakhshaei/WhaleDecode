from datetime import datetime

from pydantic import BaseModel


class Alert(BaseModel):
    id: int | None = None
    user_id: int
    event_id: int
    status: str = "pending"
    priority: str = "normal"
    dedupe_key: str = ""
    sent_at: datetime | None = None
    # Edge Intelligence enrichment (nullable).
    win_rate: float | None = None
    pool_impact_percentage: float | None = None
    cluster_origin: str | None = None
    hop_count: int | None = None
    coordinated_flag: bool = False
