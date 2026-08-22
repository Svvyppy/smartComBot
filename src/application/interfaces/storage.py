from typing import Protocol
from uuid import UUID


class ImageStorage(Protocol):
    async def save_meter_photo(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
        meter_id: UUID,
        content: bytes,
    ) -> str: ...

