from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True, kw_only=True)
class User:
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    id: UUID | None = None
    created_at: datetime | None = None
