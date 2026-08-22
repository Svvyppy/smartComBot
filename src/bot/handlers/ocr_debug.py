import logging
from io import BytesIO
from uuid import UUID

from aiogram import Bot, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.application.ocr import OCRDebugCapture, OCRDebugService
from src.bot.filters import HasPhoto, TextEquals
from src.bot.keyboards import main_menu_keyboard
from src.bot.keyboards.common import cancel_keyboard
from src.bot.presentation import format_decimal
from src.bot.states import OCRDebugForm
from src.bot.texts import MenuButton
from src.domain.entities import User

logger = logging.getLogger(__name__)


def _received_summary(capture: OCRDebugCapture) -> str:
    lines: list[str] = []
    result = capture.current_result
    if result is None:
        lines.append("• результат: не получен")
    else:
        reading = "не найден" if result.reading is None else format_decimal(result.reading)
        lines.extend(
            [
                f"• показание: {reading}",
                f"• уверенность: {result.confidence * 100:.0f}%",
            ]
        )
        if result.serial_number:
            lines.append(f"• серийный номер: {result.serial_number}")
        if result.raw_text:
            raw_text = " | ".join(result.raw_text)
            if len(raw_text) > 600:
                raw_text = f"{raw_text[:597]}…"
            lines.append(f"• сырой текст: {raw_text}")
    if capture.error:
        error = capture.error if len(capture.error) <= 700 else f"{capture.error[:697]}…"
        lines.append(f"• ошибка: {error}")
    return "\n".join(lines)


def _capture_summary(capture: OCRDebugCapture) -> str:
    return (
        "Первичная попытка OCR завершена.\n\n"
        f"Получено OCR:\n{_received_summary(capture)}\n\n"
        "Ожидается:\n• пока не указано\n\n"
        "Теперь напишите, что именно должно быть распознано на этом фото. "
        "Можно указать несколько значений.\n"
        "Например: T1=00123.4, T2=00456.7, T3=00890.1"
    )


def create_ocr_debug_router(
    ocr_debug: OCRDebugService,
    *,
    max_photo_bytes: int = 10_000_000,
) -> Router:
    router = Router(name="ocr_debug")

    @router.message(Command("ocr_debug"))
    @router.message(TextEquals(MenuButton.OCR_DEBUG))
    async def start_debug(message: Message, state: FSMContext) -> None:
        await state.clear()
        await state.set_state(OCRDebugForm.photo)
        await message.answer(
            "Отправьте проблемную фотографию счётчика.\n\n"
            "Фото и результат первичного OCR сохранятся в закрытом техническом "
            "хранилище проекта для настройки распознавания. После фото я попрошу "
            "указать ожидаемый результат.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(StateFilter(OCRDebugForm.photo), HasPhoto())
    async def capture_photo(
        message: Message,
        state: FSMContext,
        current_user: User,
        bot: Bot,
    ) -> None:
        assert message.photo
        photo = message.photo[-1]
        if photo.file_size is not None and photo.file_size > max_photo_bytes:
            await message.answer(
                "Файл слишком большой. Отправьте фото размером до "
                f"{max_photo_bytes // 1_000_000} МБ.",
                reply_markup=cancel_keyboard(),
            )
            return

        await message.answer("Фото получено. Выполняю первичное распознавание…")
        destination = BytesIO()
        await bot.download(photo, destination=destination)
        image_content = destination.getvalue()
        if len(image_content) > max_photo_bytes:
            await message.answer(
                "Файл слишком большой. Отправьте другое фото.",
                reply_markup=cancel_keyboard(),
            )
            return

        assert current_user.id is not None
        try:
            capture = await ocr_debug.capture(
                user_id=current_user.id,
                telegram_id=current_user.telegram_id,
                image_content=image_content,
                captured_at=message.date,
            )
        except Exception:
            logger.exception(
                "Could not persist OCR debug sample telegram_id=%s",
                current_user.telegram_id,
            )
            await message.answer(
                "Не удалось сохранить отладочный образец. Попробуйте отправить фото ещё раз.",
                reply_markup=cancel_keyboard(),
            )
            return

        await state.update_data(
            ocr_debug_sample_id=str(capture.sample_id),
            ocr_debug_received=_received_summary(capture),
        )
        await state.set_state(OCRDebugForm.goal)
        await message.answer(_capture_summary(capture), reply_markup=cancel_keyboard())

    @router.message(StateFilter(OCRDebugForm.photo))
    async def photo_expected(message: Message) -> None:
        await message.answer(
            "Нужно отправить фотографию как изображение.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(StateFilter(OCRDebugForm.goal))
    async def save_goal(message: Message, state: FSMContext, current_user: User) -> None:
        if not message.text:
            await message.answer(
                "Опишите ожидаемый результат текстом.",
                reply_markup=cancel_keyboard(),
            )
            return
        data = await state.get_data()
        try:
            sample_id = UUID(str(data["ocr_debug_sample_id"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer(
                "Сценарий устарел. Запустите отладку OCR заново.",
                reply_markup=main_menu_keyboard(),
            )
            return

        assert current_user.id is not None
        try:
            await ocr_debug.set_goal(
                sample_id=sample_id,
                user_id=current_user.id,
                goal=message.text,
            )
        except ValueError as exc:
            await message.answer(str(exc), reply_markup=cancel_keyboard())
            return

        await state.clear()
        logger.info(
            "OCR debug sample is ready telegram_id=%s sample_id=%s",
            current_user.telegram_id,
            sample_id,
        )
        received = str(data.get("ocr_debug_received", "• результат недоступен"))
        expected = message.text.strip()
        await message.answer(
            "Отладочный образец готов.\n\n"
            f"Получено OCR:\n{received}\n\n"
            f"Ожидается:\n{expected}\n\n"
            f"ID: {sample_id}\n"
            "Напишите в рабочем чате: «образец готов» — я найду его и начну "
            "настраивать распознавание.",
            reply_markup=main_menu_keyboard(),
        )

    return router
