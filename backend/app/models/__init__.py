"""Model registry. Importing this package imports every model module so
that `Base.metadata` is fully populated for Alembic autogenerate and for
`Base.metadata.create_all()` in tests.
"""
from app.models.api_key import ApiKey
from app.models.attendance_log import AttendanceLog
from app.models.audit_log import AuditLog
from app.models.backup import Backup
from app.models.base import Base, PkMixin, TimestampMixin
from app.models.employee import Employee
from app.models.face_embedding import FaceEmbedding
from app.models.system_log import SystemLog
from app.models.system_setting import SystemSetting
from app.models.webhook import Webhook, WebhookDelivery

__all__ = [
    "Base",
    "PkMixin",
    "TimestampMixin",
    # concrete models
    "SystemSetting",
    "ApiKey",
    "Employee",
    "FaceEmbedding",
    "AttendanceLog",
    "Webhook",
    "WebhookDelivery",
    "AuditLog",
    "SystemLog",
    "Backup",
]
