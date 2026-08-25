import json

from sqlalchemy.ext.asyncio import AsyncSession
from whaledecode.adapters.db.models.admin_audit_log import AdminAuditLogModel
from whaledecode.domain.entities.admin_audit_log import AdminAuditLog


class AdminAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, log_entry: AdminAuditLog) -> AdminAuditLog:
        model = AdminAuditLogModel(
            admin_id=log_entry.admin_id,
            action=log_entry.action,
            target_type=log_entry.target_type,
            target_id=log_entry.target_id,
            diff_json=json.dumps(log_entry.diff_json),
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    def _to_domain(self, model: AdminAuditLogModel) -> AdminAuditLog:
        return AdminAuditLog(
            id=model.id,
            admin_id=model.admin_id,
            action=model.action,
            target_type=model.target_type,
            target_id=model.target_id,
            diff_json=json.loads(model.diff_json) if isinstance(model.diff_json, str) else {},
            created_at=model.created_at,
        )
