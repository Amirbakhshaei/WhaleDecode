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
