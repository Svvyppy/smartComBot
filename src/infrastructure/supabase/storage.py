import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


class SupabaseImageStorage:
    """Store original meter photos in a private Supabase Storage bucket."""

    def __init__(self, client: Any, bucket: str = "meter-photos") -> None:
        self._client = client
        self._bucket = bucket

    async def save_meter_photo(
        self,
        *,
        user_id: UUID,
        property_id: UUID,
        meter_id: UUID,
        content: bytes,
    ) -> str:
        if not content:
            raise ValueError("Photo content cannot be empty")
        now = datetime.now(UTC)
        path = (
            f"{user_id}/{property_id}/{meter_id}/"
            f"{now.year:04d}/{now.month:02d}/{uuid4()}.jpg"
        )
        await asyncio.to_thread(
            lambda: self._client.storage.from_(self._bucket).upload(
                path=path,
                file=content,
                file_options={
                    "content-type": "image/jpeg",
                    "cache-control": "3600",
                    "upsert": "false",
                },
            )
        )
        return path

    async def delete_files(self, paths: list[str]) -> None:
        unique_paths = list(dict.fromkeys(path for path in paths if path))
        for offset in range(0, len(unique_paths), 100):
            batch = unique_paths[offset : offset + 100]
            await asyncio.to_thread(
                self._client.storage.from_(self._bucket).remove,
                batch,
            )
