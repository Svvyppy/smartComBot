from aiogram.filters import Filter
from aiogram.types import Message


class TextEquals(Filter):
    """Async exact text filter that does not use aiogram's thread-offloaded MagicFilter."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def __call__(self, message: Message) -> bool:
        return message.text == self._text


class HasPhoto(Filter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.photo)
