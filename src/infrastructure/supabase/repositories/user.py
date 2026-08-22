from typing import Any

from src.domain.entities import User
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import user_from_row


class SupabaseUserRepository(SupabaseRepository):
    async def save(self, user: User) -> User:
        payload: dict[str, Any] = {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
        }
        if user.id is not None:
            payload["id"] = str(user.id)
        response = await self._run(
            lambda: self._client.table("users")
            .upsert(payload, on_conflict="telegram_id")
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the saved user")
        return user_from_row(row)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        response = await self._run(
            lambda: self._client.table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        row = self._first(response)
        return None if row is None else user_from_row(row)

