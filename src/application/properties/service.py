from uuid import UUID

from src.application.exceptions import AccessDeniedError
from src.application.interfaces import PropertyRepository
from src.domain.entities import Property


class PropertyService:
    def __init__(self, properties: PropertyRepository) -> None:
        self._properties = properties

    async def create(
        self,
        *,
        user_id: UUID,
        name: str,
        address: str | None = None,
    ) -> Property:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Property name cannot be empty")
        clean_address = address.strip() if address and address.strip() else None
        return await self._properties.add(
            Property(user_id=user_id, name=clean_name, address=clean_address),
            user_id,
        )

    async def get(self, *, user_id: UUID, property_id: UUID) -> Property:
        property_ = await self._properties.get_owned(property_id, user_id)
        if property_ is None:
            raise AccessDeniedError("Property not found or access denied")
        return property_

    async def list(self, *, user_id: UUID) -> list[Property]:
        return await self._properties.list_by_user(user_id)

