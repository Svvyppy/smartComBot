from decimal import Decimal
from uuid import UUID

import pytest

from src.application.interfaces import OCRResult
from src.tools.ocr_feedback_regression import feedback_case_from_row, result_payload

FEEDBACK_ID = UUID("10000000-0000-0000-0000-000000000001")
METER_ID = UUID("20000000-0000-0000-0000-000000000002")


def test_feedback_case_from_supabase_row() -> None:
    case = feedback_case_from_row(
        {
            "id": str(FEEDBACK_ID),
            "meter_id": str(METER_ID),
            "corrected_value": "127.929000",
            "detected_value": "1279.290000",
            "photo_path": "user/property/meter/photo.jpg",
            "status": "profiled",
        }
    )

    assert case.id == FEEDBACK_ID
    assert case.meter_id == METER_ID
    assert case.corrected_value == Decimal("127.929")


def test_feedback_case_requires_original_photo() -> None:
    with pytest.raises(ValueError, match="does not have a photo path"):
        feedback_case_from_row(
            {
                "id": str(FEEDBACK_ID),
                "meter_id": str(METER_ID),
                "corrected_value": "1",
                "detected_value": "2",
                "photo_path": None,
                "status": "pending",
            }
        )


def test_regression_payload_includes_mechanical_metadata() -> None:
    payload = result_payload(
        OCRResult(
            reading=Decimal("127.929"),
            serial_number="N164701553",
            confidence=0.91,
            raw_text=["00127929"],
            mechanical_digits="00127929",
            mechanical_fraction_digits=3,
        )
    )

    assert payload["mechanical_digits"] == "00127929"
    assert payload["mechanical_fraction_digits"] == 3
