from datetime import datetime

from pydantic import BaseModel, Field


class AdminAuditLog(BaseModel):
    id: int | None = None
    admin_id: int
    action: str
    target_type: str
    target_id: int | None = None
    diff_json: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
