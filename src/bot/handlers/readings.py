import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from src.application.exceptions import (
    ActiveTariffNotFoundError,
    OCRReadingNotFoundError,
    ReadingRejectedError,
    SuspiciousReadingError,
)
from src.application.interfaces import OCRResult
from src.application.meters import MeterService
from src.application.properties import PropertyService
from src.application.readings import (
    ManualReadingResult,
    PhotoMeterIdentification,
    PhotoReadingResult,
    PhotoReadingService,
    ReadingService,
)
from src.bot.filters import HasPhoto, TextEquals
from src.bot.keyboards import main_menu_keyboard
from src.bot.keyboards.callbacks import MeterCallback, PropertyCallback, ReadingCallback
from src.bot.keyboards.common import (
    cancel_keyboard,
    meters_keyboard,
    photo_album_confirmation_keyboard,
    photo_confirmation_keyboard,
    photo_meter_selection_keyboard,
    properties_keyboard,
    reading_meters_keyboard,
    reading_method_keyboard,
    suspicious_reading_keyboard,
)
from src.bot.presentation import format_decimal, format_money, parse_decimal
from src.bot.states import ReadingForm
from src.bot.texts import MenuButton, unit_label, utility_label
from src.domain.entities import Meter, User

logger = logging.getLogger(__name__)


def create_readings_router(
    properties: PropertyService,
    meters: MeterService,
    readings: ReadingService,
    photo_readings: PhotoReadingService,
    *,
    max_photo_bytes: int = 10_000_000,
) -> Router:
    router = Router(name="readings")
    album_lock = asyncio.Lock()

    async def choose_property(
        message: Message,
        current_user: User,
        *,
        action: str,
        prompt: str,
    ) -> None:
        assert current_user.id is not None
        items = await properties.list(user_id=current_user.id)
        if not items:
            await message.answer(
                "Сначала добавьте объект.",
                reply_markup=properties_keyboard([], action="view", with_add=True),
            )
            return
        await message.answer(prompt, reply_markup=properties_keyboard(items, action=action))

    @router.message(Command("readings"))
    @router.message(TextEquals(MenuButton.READINGS))
    async def reading_menu(message: Message, current_user: User) -> None:
        await choose_property(
            message,
            current_user,
            action="reading",
            prompt="Выберите объект:",
        )

    @router.message(Command("history"))
    @router.message(TextEquals(MenuButton.HISTORY))
    async def history_menu(message: Message, current_user: User) -> None:
        await choose_property(
            message,
            current_user,
            action="history",
            prompt="История какого объекта вас интересует?",
        )

    async def choose_meter(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
        *,
        action: str,
        empty_text: str,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_id = UUID(callback_data.property_id)
        await properties.get(user_id=current_user.id, property_id=property_id)
        items = await meters.list(user_id=current_user.id, property_id=property_id)
        if not items:
            await callback.message.answer(empty_text)
            return
        await callback.message.answer(
            "Выберите счётчик:",
            reply_markup=meters_keyboard(items, action=action),
        )

    @router.callback_query(PropertyCallback.filter(F.action == "reading"))
    async def choose_reading_meter(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_id = UUID(callback_data.property_id)
        await properties.get(user_id=current_user.id, property_id=property_id)
        items = await meters.list(user_id=current_user.id, property_id=property_id)
        if not items:
            await callback.message.answer("У объекта нет активных счётчиков.")
            return
        await callback.message.answer(
            "Выберите счётчик или отправьте фото для автоматического определения:",
            reply_markup=reading_meters_keyboard(callback_data.property_id, items),
        )

    @router.callback_query(PropertyCallback.filter(F.action == "photo_meter"))
    async def start_unassigned_photo(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_id = UUID(callback_data.property_id)
        await properties.get(user_id=current_user.id, property_id=property_id)
        items = await meters.list(user_id=current_user.id, property_id=property_id)
        if not items:
            await callback.message.answer("У объекта нет активных счётчиков.")
            return
        await state.clear()
        await state.update_data(property_id=callback_data.property_id)
        await state.set_state(ReadingForm.unassigned_photo)
        await callback.message.answer(
            "Отправьте фотографию счётчика. Я попробую найти серийный номер, "
            "а если его не будет — предложу счётчик по прошлым показаниям.",
            reply_markup=cancel_keyboard(),
        )

    @router.callback_query(PropertyCallback.filter(F.action == "photo_album"))
    async def start_photo_album(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        property_id = UUID(callback_data.property_id)
        await properties.get(user_id=current_user.id, property_id=property_id)
        items = await meters.list(user_id=current_user.id, property_id=property_id)
        if len(items) < 2 or any(not meter.serial_number for meter in items):
            await callback.message.answer(
                "Альбом станет доступен, когда у всех активных счётчиков "
                "будут привязаны серийные номера."
            )
            return
        meter_ids = [str(meter.id) for meter in items if meter.id is not None]
        if len(meter_ids) != len(items):
            raise RuntimeError("Persisted meter does not have an id")
        await state.clear()
        await state.update_data(
            property_id=callback_data.property_id,
            album_expected_meter_ids=meter_ids,
            album_items=[],
            album_received_count=0,
            album_errors=[],
            album_media_group_id=None,
        )
        await state.set_state(ReadingForm.photo_album)
        names = "\n".join(f"• {meter.name}" for meter in items)
        await callback.message.answer(
            f"Выберите ровно {len(items)} фото в Telegram и отправьте их одним "
            f"альбомом. Порядок не важен — я сопоставлю счётчики по номерам.\n\n"
            f"Ожидаются:\n{names}",
            reply_markup=cancel_keyboard(),
        )

    @router.callback_query(PropertyCallback.filter(F.action == "history"))
    async def choose_history_meter(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        current_user: User,
    ) -> None:
        await choose_meter(
            callback,
            callback_data,
            current_user,
            action="history",
            empty_text="У объекта пока нет счётчиков.",
        )

    @router.callback_query(MeterCallback.filter(F.action == "reading"))
    async def start_reading_form(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        meter = await meters.get(
            user_id=current_user.id,
            meter_id=UUID(callback_data.meter_id),
        )
        await state.clear()
        await state.update_data(meter_id=callback_data.meter_id)
        await state.set_state(ReadingForm.method)
        await callback.message.answer(
            f"Как передать показание счётчика «{meter.name}»?",
            reply_markup=reading_method_keyboard(callback_data.meter_id),
        )

    async def selected_meter_id(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
    ) -> UUID | None:
        data = await state.get_data()
        if data.get("meter_id") != callback_data.meter_id:
            await state.clear()
            await callback.answer("Сценарий устарел", show_alert=True)
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    "Начните передачу показаний заново.",
                    reply_markup=main_menu_keyboard(),
                )
            return None
        return UUID(callback_data.meter_id)

    @router.callback_query(
        StateFilter(ReadingForm.method, ReadingForm.photo),
        MeterCallback.filter(F.action == "manual"),
    )
    async def choose_manual_input(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        meter_id = await selected_meter_id(callback, callback_data, state)
        if meter_id is None or not isinstance(callback.message, Message):
            return
        await callback.answer()
        assert current_user.id is not None
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        await state.set_state(ReadingForm.value)
        await callback.message.answer(
            f"Введите текущее показание в {unit_label(meter.unit)}:",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.callback_query(
        StateFilter(ReadingForm.method, ReadingForm.photo),
        MeterCallback.filter(F.action == "photo"),
    )
    async def choose_photo_input(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
    ) -> None:
        meter_id = await selected_meter_id(callback, callback_data, state)
        if meter_id is None or not isinstance(callback.message, Message):
            return
        await callback.answer()
        await state.set_state(ReadingForm.photo)
        await callback.message.answer(
            "Отправьте фотографию дисплея счётчика.\n\n"
            "Снимайте прямо, без бликов, и заполните показаниями большую часть кадра.",
            reply_markup=cancel_keyboard(),
        )

    def result_text(
        meter: Meter,
        result: ManualReadingResult | PhotoReadingResult,
        *,
        include_wastewater: bool = True,
    ) -> str:
        assert result.reading.confirmed_value is not None
        current = format_decimal(result.reading.confirmed_value)
        unit = unit_label(meter.unit)
        if result.is_baseline:
            return (
                f"Показание сохранено как начальное.\n\n"
                f"{meter.name}: {current} {unit}\n"
                "Расход и стоимость будут рассчитаны со следующего показания."
            )
        assert result.previous_reading is not None
        assert result.billing is not None
        assert result.charge is not None
        text = (
            f"{utility_label(meter.type)} — {meter.name}\n\n"
            f"Предыдущие: {format_decimal(result.previous_reading)} {unit}\n"
            f"Текущие: {current} {unit}\n"
            f"Расход: {format_decimal(result.billing.consumption)} {unit}\n"
            f"Тариф: {format_decimal(result.charge.tariff_price)} ₽/{unit}\n"
            f"Стоимость: {format_money(result.billing.amount)} ₽"
        )
        if result.wastewater_charge is None or not include_wastewater:
            return text
        wastewater = result.wastewater_charge
        return (
            f"{text}\n\n"
            "Водоотведение по объекту\n"
            f"Холодная вода: {format_decimal(wastewater.cold_water_consumption)} м³\n"
            f"Горячая вода: {format_decimal(wastewater.hot_water_consumption)} м³\n"
            f"Общий расход: {format_decimal(wastewater.consumption)} м³\n"
            f"Тариф: {format_decimal(wastewater.tariff_price)} ₽/м³\n"
            f"Стоимость: {format_money(wastewater.amount)} ₽"
        )

    def recognition_text(meter: Meter, result: PhotoReadingResult) -> str:
        assert result.reading.ocr_value is not None
        unit = unit_label(meter.unit)
        lines = [
            "Проверьте распознанное показание:",
            "",
            f"{meter.name}: {format_decimal(result.reading.ocr_value)} {unit}",
            f"Уверенность OCR: {(result.reading.ocr_confidence or 0) * 100:.0f}%",
        ]
        if result.serial_number:
            lines.append(f"Серийный номер на фото: {result.serial_number}")
            if not meter.serial_number:
                lines.append("После подтверждения номер будет привязан к счётчику.")
        if result.is_baseline:
            lines.extend(["", "Это первое показание — оно будет сохранено как начальное."])
        else:
            assert result.previous_reading is not None
            assert result.billing is not None
            assert result.charge is not None
            lines.extend(
                [
                    "",
                    f"Предыдущие: {format_decimal(result.previous_reading)} {unit}",
                    f"Расход: {format_decimal(result.billing.consumption)} {unit}",
                    f"Тариф: {format_decimal(result.charge.tariff_price)} ₽/{unit}",
                    f"Стоимость: {format_money(result.billing.amount)} ₽",
                ]
            )
        if result.validation is not None and result.validation.requires_confirmation:
            lines.extend(["", "⚠️ Расход выглядит необычно большим."])
        if result.wastewater_tariff_price is not None and result.billing is not None:
            lines.extend(
                [
                    "",
                    "После подтверждения будет пересчитано водоотведение:",
                    f"текущий расход {format_decimal(result.billing.consumption)} м³, "
                    f"тариф {format_decimal(result.wastewater_tariff_price)} ₽/м³.",
                ]
            )
        return "\n".join(lines)

    async def photo_retry(
        message: Message,
        *,
        meter_id: UUID,
        text: str,
    ) -> None:
        await message.answer(
            f"{text}\n\nПопробуйте другое фото или введите показание вручную.",
            reply_markup=reading_method_keyboard(str(meter_id)),
        )

    async def reject_album_items(
        current_user: User,
        items: list[dict[str, str]],
    ) -> None:
        assert current_user.id is not None
        for item in items:
            try:
                await photo_readings.reject(
                    user_id=current_user.id,
                    reading_id=UUID(item["reading_id"]),
                )
            except Exception:
                logger.exception(
                    "Album reading rejection failed telegram_id=%s reading_id=%s",
                    current_user.telegram_id,
                    item.get("reading_id"),
                )

    async def create_photo_preview(
        message: Message,
        state: FSMContext,
        current_user: User,
        *,
        meter: Meter,
        image_content: bytes,
        captured_at: datetime,
        ocr_result: OCRResult | None = None,
    ) -> None:
        if meter.id is None:
            raise RuntimeError("Meter does not have an id")
        assert current_user.id is not None
        result = await photo_readings.recognize_photo(
            user_id=current_user.id,
            meter_id=meter.id,
            image_content=image_content,
            captured_at=captured_at,
            ocr_result=ocr_result,
        )
        if result.reading.id is None:
            raise RuntimeError("Saved recognized reading does not have an id")
        await state.update_data(
            meter_id=str(meter.id),
            reading_id=str(result.reading.id),
            recognized_serial_number=result.serial_number,
            recognized_raw_text=list(result.raw_text),
            recognized_mechanical_digits=result.mechanical_digits,
        )
        await state.set_state(ReadingForm.photo_confirmation)
        await message.answer(
            recognition_text(meter, result),
            reply_markup=photo_confirmation_keyboard(str(result.reading.id)),
        )

    @router.message(StateFilter(ReadingForm.photo_album), HasPhoto())
    async def collect_photo_album(
        message: Message,
        state: FSMContext,
        current_user: User,
        bot: Bot,
    ) -> None:
        if message.media_group_id is None:
            await message.answer(
                "Нужно выбрать все фотографии в галерее и отправить их одним альбомом.",
                reply_markup=cancel_keyboard(),
            )
            return

        async with album_lock:
            data = await state.get_data()
            try:
                property_id = UUID(str(data["property_id"]))
                expected_meter_ids = list(data["album_expected_meter_ids"])
                items: list[dict[str, str]] = list(data.get("album_items", []))
                errors: list[str] = list(data.get("album_errors", []))
                received_count = int(data.get("album_received_count", 0)) + 1
            except (KeyError, TypeError, ValueError):
                await state.clear()
                await message.answer(
                    "Сценарий альбома устарел. Начните заново.",
                    reply_markup=main_menu_keyboard(),
                )
                return

            media_group_id = str(message.media_group_id)
            active_media_group_id = data.get("album_media_group_id")
            if active_media_group_id not in (None, media_group_id):
                await message.answer(
                    "Получен другой альбом. Отмените сценарий и отправьте фото заново.",
                    reply_markup=cancel_keyboard(),
                )
                return
            if received_count > len(expected_meter_ids):
                await reject_album_items(current_user, items)
                await state.clear()
                await message.answer(
                    f"В альбоме больше {len(expected_meter_ids)} фото. "
                    "Все распознанные результаты отклонены — начните заново.",
                    reply_markup=main_menu_keyboard(),
                )
                return

            assert message.photo
            photo = message.photo[-1]
            meter: Meter | None = None
            result: PhotoReadingResult | None = None
            error: str | None = None
            if photo.file_size is not None and photo.file_size > max_photo_bytes:
                error = f"Фото {received_count}: файл слишком большой."
            else:
                try:
                    destination = BytesIO()
                    await bot.download(photo, destination=destination)
                    image_content = destination.getvalue()
                    if len(image_content) > max_photo_bytes:
                        raise ValueError("файл слишком большой")
                    assert current_user.id is not None
                    identification = await photo_readings.identify_meter(
                        user_id=current_user.id,
                        property_id=property_id,
                        image_content=image_content,
                    )
                    meter = identification.matched_meter
                    if meter is None or meter.id is None:
                        raise ReadingRejectedError(
                            "серийный номер не распознан или не совпал"
                        )
                    meter_id = str(meter.id)
                    if meter_id not in expected_meter_ids:
                        raise ReadingRejectedError("счётчик не относится к этому объекту")
                    if any(item["meter_id"] == meter_id for item in items):
                        raise ReadingRejectedError(
                            f"фото счётчика «{meter.name}» получено повторно"
                        )
                    result = await photo_readings.recognize_photo(
                        user_id=current_user.id,
                        meter_id=meter.id,
                        image_content=image_content,
                        captured_at=message.date,
                        ocr_result=identification.ocr_result,
                    )
                    if result.reading.id is None:
                        raise RuntimeError("Saved album reading does not have an id")
                    items.append(
                        {
                            "meter_id": meter_id,
                            "reading_id": str(result.reading.id),
                        }
                    )
                except (
                    ActiveTariffNotFoundError,
                    OCRReadingNotFoundError,
                    ReadingRejectedError,
                    ValueError,
                ) as exc:
                    error = f"Фото {received_count}: {exc}"
                except Exception:
                    logger.exception(
                        "Album photo recognition failed telegram_id=%s property_id=%s",
                        current_user.telegram_id,
                        property_id,
                    )
                    error = f"Фото {received_count}: не удалось обработать."

            if error is not None:
                errors.append(error)
                await message.answer(error)
            elif meter is not None and result is not None:
                await message.answer(
                    f"Фото {received_count}/{len(expected_meter_ids)} сопоставлено.\n\n"
                    + recognition_text(meter, result)
                )

            await state.update_data(
                album_media_group_id=media_group_id,
                album_received_count=received_count,
                album_items=items,
                album_errors=errors,
            )
            if received_count < len(expected_meter_ids):
                return

            if errors or len(items) != len(expected_meter_ids):
                await reject_album_items(current_user, items)
                await state.clear()
                details = "\n".join(f"• {item}" for item in errors)
                await message.answer(
                    "Альбом не принят. Распознанные результаты отклонены.\n\n"
                    f"{details}\n\nИсправьте фотографии и начните заново.",
                    reply_markup=main_menu_keyboard(),
                )
                return

            await state.set_state(ReadingForm.photo_album_confirmation)
            await message.answer(
                f"Все {len(items)} фото сопоставлены со счётчиками. "
                "Проверьте результаты выше и подтвердите их вместе. "
                "Если хотя бы одно значение неверно — отмените альбом и "
                "передайте этот счётчик отдельно.",
                reply_markup=photo_album_confirmation_keyboard(str(property_id)),
            )

    @router.message(StateFilter(ReadingForm.photo_album))
    async def photo_album_expected(message: Message) -> None:
        await message.answer(
            "Отправьте фотографии одним Telegram-альбомом.",
            reply_markup=cancel_keyboard(),
        )

    def meter_identification_text(result: PhotoMeterIdentification) -> str:
        assert result.ocr_result.reading is not None
        lines = [
            f"Распознано показание: {format_decimal(result.ocr_result.reading)}",
            (
                f"Серийный номер: {result.ocr_result.serial_number} (нет совпадения)"
                if result.ocr_result.serial_number
                else "Серийный номер: не распознан"
            ),
        ]
        suggested = next(
            (
                candidate
                for candidate in result.candidates
                if result.suggested_meter is not None
                and candidate.meter.id == result.suggested_meter.id
            ),
            None,
        )
        if suggested is not None and suggested.previous_reading is not None:
            lines.extend(
                [
                    "",
                    f"По прошлому показанию предполагаю: {suggested.meter.name}.",
                    f"Предыдущее: {format_decimal(suggested.previous_reading)} "
                    f"{unit_label(suggested.meter.unit)}",
                    f"Ожидаемый расход: {format_decimal(suggested.delta or Decimal(0))} "
                    f"{unit_label(suggested.meter.unit)}",
                ]
            )
        lines.extend(["", "Выберите, какой это счётчик:"])
        return "\n".join(lines)

    @router.message(StateFilter(ReadingForm.unassigned_photo), HasPhoto())
    async def identify_photo_meter(
        message: Message,
        state: FSMContext,
        current_user: User,
        bot: Bot,
    ) -> None:
        data = await state.get_data()
        try:
            property_id = UUID(str(data["property_id"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer("Сценарий устарел.", reply_markup=main_menu_keyboard())
            return

        assert message.photo
        photo = message.photo[-1]
        if photo.file_size is not None and photo.file_size > max_photo_bytes:
            await message.answer(
                "Файл слишком большой. Попробуйте другое фото.",
                reply_markup=cancel_keyboard(),
            )
            return

        await message.answer("Фото получено. Распознаю показание и счётчик…")
        destination = BytesIO()
        await bot.download(photo, destination=destination)
        image_content = destination.getvalue()
        if len(image_content) > max_photo_bytes:
            await message.answer(
                "Файл слишком большой. Попробуйте другое фото.",
                reply_markup=cancel_keyboard(),
            )
            return

        assert current_user.id is not None
        try:
            identification = await photo_readings.identify_meter(
                user_id=current_user.id,
                property_id=property_id,
                image_content=image_content,
            )
        except (OCRReadingNotFoundError, ReadingRejectedError, ValueError) as exc:
            await message.answer(
                f"{exc}\n\nПопробуйте другое фото.",
                reply_markup=cancel_keyboard(),
            )
            return
        except Exception:
            logger.exception(
                "Photo meter identification failed telegram_id=%s property_id=%s",
                current_user.telegram_id,
                property_id,
            )
            await message.answer(
                "Не удалось обработать фотографию. Попробуйте другое фото.",
                reply_markup=cancel_keyboard(),
            )
            return

        if identification.matched_meter is not None:
            meter = identification.matched_meter
            await message.answer(f"Счётчик определён по серийному номеру: {meter.name}.")
            try:
                await create_photo_preview(
                    message,
                    state,
                    current_user,
                    meter=meter,
                    image_content=image_content,
                    captured_at=message.date,
                    ocr_result=identification.ocr_result,
                )
            except (OCRReadingNotFoundError, ReadingRejectedError, ValueError) as exc:
                await message.answer(
                    f"Показание не принято: {exc}\nПопробуйте другое фото.",
                    reply_markup=cancel_keyboard(),
                )
            except ActiveTariffNotFoundError:
                await state.clear()
                await message.answer(
                    "Для этого ресурса не настроен действующий тариф. "
                    "Сначала откройте раздел «Тарифы».",
                    reply_markup=main_menu_keyboard(),
                )
            except Exception:
                logger.exception(
                    "Matched photo save failed telegram_id=%s meter_id=%s",
                    current_user.telegram_id,
                    meter.id,
                )
                await message.answer(
                    "Не удалось сохранить распознанное показание. Попробуйте другое фото.",
                    reply_markup=cancel_keyboard(),
                )
            return

        candidate_meters = [candidate.meter for candidate in identification.candidates]
        candidate_ids = [str(meter.id) for meter in candidate_meters if meter.id is not None]
        suggested_id = (
            identification.suggested_meter.id
            if identification.suggested_meter is not None
            else None
        )
        await state.update_data(
            photo_file_id=photo.file_id,
            photo_captured_at=message.date.isoformat(),
            ocr_reading=str(identification.ocr_result.reading),
            ocr_serial_number=identification.ocr_result.serial_number,
            ocr_confidence=identification.ocr_result.confidence,
            ocr_raw_text=identification.ocr_result.raw_text,
            candidate_meter_ids=candidate_ids,
            suggested_meter_id=None if suggested_id is None else str(suggested_id),
        )
        await state.set_state(ReadingForm.photo_meter_selection)
        await message.answer(
            meter_identification_text(identification),
            reply_markup=photo_meter_selection_keyboard(
                candidate_meters,
                suggested_meter_id=suggested_id,
            ),
        )

    @router.message(StateFilter(ReadingForm.unassigned_photo))
    async def unassigned_photo_expected(message: Message) -> None:
        await message.answer(
            "Отправьте фотографию как изображение.",
            reply_markup=cancel_keyboard(),
        )

    @router.callback_query(
        StateFilter(ReadingForm.photo_meter_selection),
        MeterCallback.filter(F.action == "select_photo"),
    )
    async def select_photo_meter(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
        current_user: User,
        bot: Bot,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        data = await state.get_data()
        candidate_ids = data.get("candidate_meter_ids", [])
        if callback_data.meter_id not in candidate_ids:
            await state.clear()
            await callback.message.answer(
                "Выбор счётчика устарел. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        try:
            meter_id = UUID(callback_data.meter_id)
            captured_at = datetime.fromisoformat(str(data["photo_captured_at"]))
            ocr_result = OCRResult(
                reading=Decimal(str(data["ocr_reading"])),
                serial_number=data.get("ocr_serial_number"),
                confidence=float(data["ocr_confidence"]),
                raw_text=list(data.get("ocr_raw_text", [])),
            )
            photo_file_id = str(data["photo_file_id"])
        except (KeyError, TypeError, ValueError):
            await state.clear()
            await callback.message.answer(
                "Выбор счётчика устарел. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return

        assert current_user.id is not None
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        destination = BytesIO()
        await bot.download(photo_file_id, destination=destination)
        image_content = destination.getvalue()
        if len(image_content) > max_photo_bytes:
            await state.clear()
            await callback.message.answer(
                "Файл слишком большой. Начните передачу заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        try:
            await create_photo_preview(
                callback.message,
                state,
                current_user,
                meter=meter,
                image_content=image_content,
                captured_at=captured_at,
                ocr_result=ocr_result,
            )
        except (OCRReadingNotFoundError, ReadingRejectedError, ValueError) as exc:
            await callback.message.answer(
                f"Этот счётчик не подходит: {exc}\nВыберите другой счётчик."
            )
        except ActiveTariffNotFoundError:
            await state.clear()
            await callback.message.answer(
                "Для этого ресурса не настроен действующий тариф. "
                "Сначала откройте раздел «Тарифы».",
                reply_markup=main_menu_keyboard(),
            )
        except Exception:
            logger.exception(
                "Selected photo meter save failed telegram_id=%s meter_id=%s",
                current_user.telegram_id,
                meter_id,
            )
            await state.clear()
            await callback.message.answer(
                "Не удалось сохранить показание. Начните передачу заново.",
                reply_markup=main_menu_keyboard(),
            )

    @router.message(StateFilter(ReadingForm.photo), HasPhoto())
    async def recognize_photo(
        message: Message,
        state: FSMContext,
        current_user: User,
        bot: Bot,
    ) -> None:
        data = await state.get_data()
        try:
            meter_id = UUID(str(data["meter_id"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer("Сценарий устарел.", reply_markup=main_menu_keyboard())
            return
        assert message.photo
        photo = message.photo[-1]
        if photo.file_size is not None and photo.file_size > max_photo_bytes:
            await photo_retry(
                message,
                meter_id=meter_id,
                text="Файл слишком большой.",
            )
            return

        await message.answer("Фото получено. Распознаю показание…")
        destination = BytesIO()
        await bot.download(photo, destination=destination)
        image_content = destination.getvalue()
        if len(image_content) > max_photo_bytes:
            await photo_retry(
                message,
                meter_id=meter_id,
                text="Файл слишком большой.",
            )
            return

        assert current_user.id is not None
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        try:
            result = await photo_readings.recognize_photo(
                user_id=current_user.id,
                meter_id=meter_id,
                image_content=image_content,
                captured_at=message.date,
            )
        except (OCRReadingNotFoundError, ReadingRejectedError, ValueError) as exc:
            await photo_retry(message, meter_id=meter_id, text=str(exc))
            return
        except ActiveTariffNotFoundError:
            await state.clear()
            await message.answer(
                "Для этого ресурса не настроен действующий тариф. "
                "Сначала откройте раздел «Тарифы».",
                reply_markup=main_menu_keyboard(),
            )
            return
        except Exception:
            logger.exception(
                "Photo OCR failed telegram_id=%s meter_id=%s",
                current_user.telegram_id,
                meter_id,
            )
            await photo_retry(
                message,
                meter_id=meter_id,
                text="Не удалось обработать фотографию.",
            )
            return

        if result.reading.id is None:
            raise RuntimeError("Saved recognized reading does not have an id")
        await state.update_data(
            reading_id=str(result.reading.id),
            recognized_serial_number=result.serial_number,
            recognized_raw_text=list(result.raw_text),
            recognized_mechanical_digits=result.mechanical_digits,
        )
        await state.set_state(ReadingForm.photo_confirmation)
        await message.answer(
            recognition_text(meter, result),
            reply_markup=photo_confirmation_keyboard(str(result.reading.id)),
        )

    @router.message(StateFilter(ReadingForm.photo))
    async def photo_expected(message: Message) -> None:
        await message.answer(
            "Отправьте фотографию как изображение или выберите ручной ввод.",
            reply_markup=cancel_keyboard(),
        )

    async def persist_reading(
        message: Message,
        state: FSMContext,
        current_user: User,
        *,
        meter_id: UUID,
        value: Decimal,
        allow_suspicious: bool,
    ) -> None:
        assert current_user.id is not None
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        try:
            result = await readings.record_manual(
                user_id=current_user.id,
                meter_id=meter_id,
                value=value,
                allow_suspicious=allow_suspicious,
            )
        except SuspiciousReadingError as exc:
            await state.update_data(meter_id=str(meter_id), value=str(value))
            await state.set_state(ReadingForm.suspicious_confirmation)
            await message.answer(
                f"{exc}\n\nПоказание выглядит необычно большим. Сохранить его?",
                reply_markup=suspicious_reading_keyboard(str(meter_id)),
            )
            return
        except ReadingRejectedError as exc:
            await message.answer(f"Показание не принято: {exc}\nВведите другое значение.")
            return
        except ActiveTariffNotFoundError:
            await message.answer(
                "Для этого ресурса не настроен действующий тариф. "
                "Сначала откройте раздел «Тарифы».",
                reply_markup=main_menu_keyboard(),
            )
            await state.clear()
            return
        await state.clear()
        logger.info(
            "Manual reading saved telegram_id=%s meter_id=%s reading_id=%s",
            current_user.telegram_id,
            meter_id,
            result.reading.id,
        )
        await message.answer(result_text(meter, result), reply_markup=main_menu_keyboard())

    @router.message(StateFilter(ReadingForm.value))
    async def reading_value(
        message: Message,
        state: FSMContext,
        current_user: User,
    ) -> None:
        if not message.text:
            await message.answer("Введите показание числом.", reply_markup=cancel_keyboard())
            return
        try:
            value = parse_decimal(message.text)
        except ValueError as exc:
            await message.answer(str(exc), reply_markup=cancel_keyboard())
            return
        data = await state.get_data()
        try:
            meter_id = UUID(str(data["meter_id"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer(
                "Сценарий устарел. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        await persist_reading(
            message,
            state,
            current_user,
            meter_id=meter_id,
            value=value,
            allow_suspicious=False,
        )

    @router.callback_query(
        StateFilter(ReadingForm.suspicious_confirmation),
        MeterCallback.filter(F.action == "confirm"),
    )
    async def confirm_suspicious(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        data = await state.get_data()
        if data.get("meter_id") != callback_data.meter_id or "value" not in data:
            await state.clear()
            await callback.message.answer(
                "Подтверждение устарело. Начните заново.",
                reply_markup=main_menu_keyboard(),
            )
            return
        await persist_reading(
            callback.message,
            state,
            current_user,
            meter_id=UUID(callback_data.meter_id),
            value=Decimal(str(data["value"])),
            allow_suspicious=True,
        )

    @router.callback_query(
        StateFilter(ReadingForm.suspicious_confirmation),
        MeterCallback.filter(F.action == "retry"),
    )
    async def retry_suspicious(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        state: FSMContext,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        await state.update_data(meter_id=callback_data.meter_id)
        await state.set_state(ReadingForm.value)
        await callback.message.answer("Введите исправленное показание:")

    async def selected_album_items(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        state: FSMContext,
    ) -> list[dict[str, str]] | None:
        data = await state.get_data()
        if data.get("property_id") != callback_data.property_id:
            await state.clear()
            await callback.answer("Подтверждение устарело", show_alert=True)
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    "Начните передачу альбома заново.",
                    reply_markup=main_menu_keyboard(),
                )
            return None
        items = data.get("album_items")
        if not isinstance(items, list) or not items:
            await state.clear()
            await callback.answer("В альбоме нет показаний", show_alert=True)
            return None
        return items

    @router.callback_query(
        StateFilter(ReadingForm.photo_album_confirmation),
        PropertyCallback.filter(F.action == "confirm_album"),
    )
    async def confirm_photo_album(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        items = await selected_album_items(callback, callback_data, state)
        if items is None or not isinstance(callback.message, Message):
            return
        await callback.answer()
        assert current_user.id is not None
        confirmed: list[tuple[Meter, PhotoReadingResult]] = []
        failed: list[dict[str, str]] = []
        errors: list[str] = []
        for item in items:
            try:
                meter_id = UUID(item["meter_id"])
                reading_id = UUID(item["reading_id"])
                meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
                result = await photo_readings.confirm(
                    user_id=current_user.id,
                    reading_id=reading_id,
                )
                confirmed.append((meter, result))
            except Exception as exc:
                logger.exception(
                    "Album confirmation failed telegram_id=%s reading_id=%s",
                    current_user.telegram_id,
                    item.get("reading_id"),
                )
                failed.append(item)
                errors.append(str(exc) or "неизвестная ошибка")

        if failed:
            await reject_album_items(current_user, failed)
        await state.clear()

        wastewater_indexes = [
            index
            for index, (_, result) in enumerate(confirmed)
            if result.wastewater_charge is not None
        ]
        last_wastewater_index = wastewater_indexes[-1] if wastewater_indexes else None
        for index, (meter, result) in enumerate(confirmed):
            await callback.message.answer(
                result_text(
                    meter,
                    result,
                    include_wastewater=index == last_wastewater_index,
                )
            )

        if errors:
            details = "\n".join(f"• {error}" for error in errors)
            await callback.message.answer(
                f"Подтверждено: {len(confirmed)} из {len(items)}.\n"
                f"Ошибки:\n{details}",
                reply_markup=main_menu_keyboard(),
            )
            return
        await callback.message.answer(
            f"Все показания подтверждены: {len(confirmed)}.",
            reply_markup=main_menu_keyboard(),
        )

    @router.callback_query(
        StateFilter(ReadingForm.photo_album_confirmation),
        PropertyCallback.filter(F.action == "reject_album"),
    )
    async def reject_photo_album(
        callback: CallbackQuery,
        callback_data: PropertyCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        items = await selected_album_items(callback, callback_data, state)
        if items is None:
            return
        await reject_album_items(current_user, items)
        await state.clear()
        await callback.answer("Альбом отклонён")
        if isinstance(callback.message, Message):
            await callback.message.answer(
                "Все распознанные показания из альбома отклонены.",
                reply_markup=main_menu_keyboard(),
            )

    async def selected_photo_reading(
        callback: CallbackQuery,
        callback_data: ReadingCallback,
        state: FSMContext,
    ) -> tuple[UUID, UUID] | None:
        data = await state.get_data()
        if data.get("reading_id") != callback_data.reading_id or "meter_id" not in data:
            await state.clear()
            await callback.answer("Подтверждение устарело", show_alert=True)
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    "Начните передачу показаний заново.",
                    reply_markup=main_menu_keyboard(),
                )
            return None
        try:
            return UUID(callback_data.reading_id), UUID(str(data["meter_id"]))
        except ValueError:
            await state.clear()
            await callback.answer("Некорректные данные", show_alert=True)
            return None

    async def finish_photo_confirmation(
        message: Message,
        state: FSMContext,
        current_user: User,
        *,
        reading_id: UUID,
        meter_id: UUID,
        value: Decimal | None,
    ) -> bool:
        assert current_user.id is not None
        state_data = await state.get_data()
        recognized_serial_number = state_data.get("recognized_serial_number")
        stored_raw_text = state_data.get("recognized_raw_text")
        recognized_raw_text = (
            stored_raw_text
            if isinstance(stored_raw_text, list)
            and all(isinstance(line, str) for line in stored_raw_text)
            else []
        )
        stored_mechanical_digits = state_data.get("recognized_mechanical_digits")
        recognized_mechanical_digits = (
            stored_mechanical_digits
            if isinstance(stored_mechanical_digits, str)
            else None
        )
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        try:
            result = await photo_readings.confirm(
                user_id=current_user.id,
                reading_id=reading_id,
                value=value,
                serial_number=(
                    recognized_serial_number
                    if isinstance(recognized_serial_number, str)
                    else None
                ),
                raw_text=recognized_raw_text,
                mechanical_digits=recognized_mechanical_digits,
            )
        except ReadingRejectedError as exc:
            await message.answer(
                f"Показание не принято: {exc}\nВведите другое значение.",
                reply_markup=cancel_keyboard(),
            )
            return False
        except ActiveTariffNotFoundError:
            await state.clear()
            await message.answer(
                "Действующий тариф больше не найден. Настройте его и повторите передачу.",
                reply_markup=main_menu_keyboard(),
            )
            return False
        except Exception:
            logger.exception(
                "Photo confirmation failed telegram_id=%s reading_id=%s",
                current_user.telegram_id,
                reading_id,
            )
            await state.clear()
            await message.answer(
                "Не удалось подтвердить показание. Начните передачу заново.",
                reply_markup=main_menu_keyboard(),
            )
            return False

        serial_note = ""
        if isinstance(recognized_serial_number, str) and recognized_serial_number:
            try:
                meter, was_bound = await meters.bind_serial_number_if_missing(
                    user_id=current_user.id,
                    meter_id=meter_id,
                    serial_number=recognized_serial_number,
                )
                if was_bound:
                    serial_note = (
                        "\n\nСерийный номер "
                        f"{meter.serial_number} привязан к счётчику."
                    )
            except ValueError as exc:
                serial_note = f"\n\n⚠️ Серийный номер не привязан: {exc}"
            except Exception:
                logger.exception(
                    "Meter serial binding failed telegram_id=%s meter_id=%s",
                    current_user.telegram_id,
                    meter_id,
                )
                serial_note = "\n\n⚠️ Не удалось привязать серийный номер."
        learning_note = ""
        was_corrected = result.reading.ocr_value != result.reading.confirmed_value
        if was_corrected and result.profile_updated:
            learning_note = (
                "\n\n✅ Исправление сохранено. Для этого счётчика создан "
                "индивидуальный профиль распознавания."
            )
        elif was_corrected and result.feedback_saved:
            learning_note = (
                "\n\n✅ Исправление сохранено как обучающий пример. "
                "Оно не изменяет распознавание других пользователей."
            )
        elif was_corrected:
            learning_note = (
                "\n\n⚠️ Показание принято, но обучающий пример сохранить не удалось."
            )
        await state.clear()
        logger.info(
            "Photo reading confirmed telegram_id=%s meter_id=%s reading_id=%s corrected=%s",
            current_user.telegram_id,
            meter_id,
            reading_id,
            value is not None,
        )
        await message.answer(
            result_text(meter, result) + serial_note + learning_note,
            reply_markup=main_menu_keyboard(),
        )
        return True

    @router.callback_query(
        StateFilter(ReadingForm.photo_confirmation),
        ReadingCallback.filter(F.action == "confirm"),
    )
    async def confirm_photo_reading(
        callback: CallbackQuery,
        callback_data: ReadingCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        selected = await selected_photo_reading(callback, callback_data, state)
        if selected is None or not isinstance(callback.message, Message):
            return
        await callback.answer()
        reading_id, meter_id = selected
        await finish_photo_confirmation(
            callback.message,
            state,
            current_user,
            reading_id=reading_id,
            meter_id=meter_id,
            value=None,
        )

    @router.callback_query(
        StateFilter(ReadingForm.photo_confirmation),
        ReadingCallback.filter(F.action == "correct"),
    )
    async def correct_photo_reading(
        callback: CallbackQuery,
        callback_data: ReadingCallback,
        state: FSMContext,
    ) -> None:
        selected = await selected_photo_reading(callback, callback_data, state)
        if selected is None or not isinstance(callback.message, Message):
            return
        await callback.answer()
        await state.set_state(ReadingForm.photo_correction)
        await callback.message.answer(
            "Введите правильное показание числом:",
            reply_markup=cancel_keyboard(),
        )

    @router.message(StateFilter(ReadingForm.photo_correction))
    async def corrected_photo_value(
        message: Message,
        state: FSMContext,
        current_user: User,
    ) -> None:
        if not message.text:
            await message.answer("Введите показание числом.", reply_markup=cancel_keyboard())
            return
        try:
            value = parse_decimal(message.text)
        except ValueError as exc:
            await message.answer(str(exc), reply_markup=cancel_keyboard())
            return
        data = await state.get_data()
        try:
            reading_id = UUID(str(data["reading_id"]))
            meter_id = UUID(str(data["meter_id"]))
        except (KeyError, ValueError):
            await state.clear()
            await message.answer("Сценарий устарел.", reply_markup=main_menu_keyboard())
            return
        await finish_photo_confirmation(
            message,
            state,
            current_user,
            reading_id=reading_id,
            meter_id=meter_id,
            value=value,
        )

    @router.callback_query(
        StateFilter(ReadingForm.photo_confirmation),
        ReadingCallback.filter(F.action == "reject"),
    )
    async def reject_photo_reading(
        callback: CallbackQuery,
        callback_data: ReadingCallback,
        state: FSMContext,
        current_user: User,
    ) -> None:
        selected = await selected_photo_reading(callback, callback_data, state)
        if selected is None:
            return
        reading_id, _ = selected
        assert current_user.id is not None
        try:
            await photo_readings.reject(user_id=current_user.id, reading_id=reading_id)
        except Exception:
            logger.exception(
                "Photo rejection failed telegram_id=%s reading_id=%s",
                current_user.telegram_id,
                reading_id,
            )
        await state.clear()
        await callback.answer("Отменено")
        if isinstance(callback.message, Message):
            await callback.message.answer(
                "Распознанное показание отклонено.",
                reply_markup=main_menu_keyboard(),
            )

    @router.callback_query(MeterCallback.filter(F.action == "history"))
    async def meter_history(
        callback: CallbackQuery,
        callback_data: MeterCallback,
        current_user: User,
    ) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        assert current_user.id is not None
        meter_id = UUID(callback_data.meter_id)
        meter = await meters.get(user_id=current_user.id, meter_id=meter_id)
        history = await readings.list_history(
            user_id=current_user.id,
            meter_id=meter_id,
            limit=10,
        )
        if not history:
            await callback.message.answer(f"У счётчика «{meter.name}» пока нет показаний.")
            return
        unit = unit_label(meter.unit)
        lines = [f"Последние показания — {meter.name}: "]
        for reading in history:
            assert reading.confirmed_value is not None
            lines.append(
                f"• {reading.captured_at:%d.%m.%Y}: "
                f"{format_decimal(reading.confirmed_value)} {unit}"
            )
        await callback.message.answer("\n".join(lines))

    return router
