from src.application.interfaces import UserRepository
from src.domain.entities import User


class UserService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def register(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
    ) -> User:
        return await self._users.save(
            User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
            )
        )

    async def resolve(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
    ) -> User:
        existing = await self._users.get_by_telegram_id(telegram_id)
        if (
            existing is not None
            and existing.username == username
            and existing.first_name == first_name
        ):
            return existing
        return await self.register(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
        )
