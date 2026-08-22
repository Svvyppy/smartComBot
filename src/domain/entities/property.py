from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True, kw_only=True)
class Property:
    user_id: UUID
    name: str
    address: str | None = None
    id: UUID | None = None
    created_at: datetime | None = None
