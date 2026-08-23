from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.domain.entities import MeterOCRProfile, OCRFeedback
from src.infrastructure.supabase.repositories.base import SupabaseRepository
from src.infrastructure.supabase.repositories.mappers import (
    meter_ocr_profile_from_row,
    ocr_feedback_from_row,
)


class SupabaseOCRFeedbackRepository(SupabaseRepository):
    async def add(self, feedback: OCRFeedback, user_id: UUID) -> OCRFeedback:
        if feedback.user_id != user_id:
            raise ValueError("OCR feedback user does not match current user")
        await self._require_meter_owned(feedback.meter_id, user_id)
        payload: dict[str, Any] = {
            "reading_id": str(feedback.reading_id),
            "meter_id": str(feedback.meter_id),
            "user_id": str(feedback.user_id),
            "detected_value": str(feedback.detected_value),
            "corrected_value": str(feedback.corrected_value),
            "serial_number": feedback.serial_number,
            "raw_text": list(feedback.raw_text),
            "mechanical_digits": feedback.mechanical_digits,
            "photo_path": feedback.photo_path,
            "status": feedback.status,
        }
        if feedback.id is not None:
            payload["id"] = str(feedback.id)
        response = await self._run(
            lambda: self._client.table("ocr_feedback").insert(payload).execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the created OCR feedback")
        return ocr_feedback_from_row(row)

    async def get_meter_profile(
        self,
        meter_id: UUID,
        user_id: UUID,
    ) -> MeterOCRProfile | None:
        await self._require_meter_owned(meter_id, user_id)
        response = await self._run(
            lambda: self._client.table("meter_ocr_profiles")
            .select("*")
            .eq("meter_id", str(meter_id))
            .limit(1)
            .execute()
        )
        row = self._first(response)
        return None if row is None else meter_ocr_profile_from_row(row)

    async def save_meter_profile(
        self,
        profile: MeterOCRProfile,
        user_id: UUID,
    ) -> MeterOCRProfile:
        await self._require_meter_owned(profile.meter_id, user_id)
        payload = {
            "meter_id": str(profile.meter_id),
            "mechanical_fraction_digits": profile.mechanical_fraction_digits,
            "learned_from_feedback_id": (
                None
                if profile.learned_from_feedback_id is None
                else str(profile.learned_from_feedback_id)
            ),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        response = await self._run(
            lambda: self._client.table("meter_ocr_profiles")
            .upsert(payload, on_conflict="meter_id")
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("Supabase did not return the saved OCR meter profile")
        return meter_ocr_profile_from_row(row)

    async def set_feedback_status(
        self,
        feedback_id: UUID,
        user_id: UUID,
        status: str,
    ) -> OCRFeedback:
        response = await self._run(
            lambda: self._client.table("ocr_feedback")
            .update({"status": status})
            .eq("id", str(feedback_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        row = self._first(response)
        if row is None:
            raise RuntimeError("OCR feedback not found or access denied")
        return ocr_feedback_from_row(row)
