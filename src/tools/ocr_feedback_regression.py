from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.application.interfaces import OCRResult
from src.config import Settings
from src.infrastructure.ocr import (
    ImagePreprocessor,
    MeterReadingParser,
    PaddleOCRService,
    PreprocessingConfig,
)
from src.infrastructure.supabase import create_supabase_client


@dataclass(frozen=True, slots=True)
class FeedbackCase:
    id: UUID
    meter_id: UUID
    corrected_value: Decimal
    detected_value: Decimal
    photo_path: str
    status: str


def response_rows(response: Any) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else response.data
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    return list(data)


def feedback_case_from_row(row: dict[str, Any]) -> FeedbackCase:
    photo_path = row.get("photo_path")
    if not isinstance(photo_path, str) or not photo_path:
        raise ValueError(f"OCR feedback {row.get('id')} does not have a photo path")
    return FeedbackCase(
        id=UUID(str(row["id"])),
        meter_id=UUID(str(row["meter_id"])),
        corrected_value=Decimal(str(row["corrected_value"])),
        detected_value=Decimal(str(row["detected_value"])),
        photo_path=photo_path,
        status=str(row["status"]),
    )


def load_feedback_cases(
    client: Any,
    *,
    status: str,
    meter_id: UUID | None,
    limit: int,
) -> list[FeedbackCase]:
    query = (
        client.table("ocr_feedback")
        .select("id,meter_id,corrected_value,detected_value,photo_path,status")
        .order("created_at")
        .limit(limit)
    )
    if status == "all":
        query = query.neq("status", "ignored")
    else:
        query = query.eq("status", status)
    if meter_id is not None:
        query = query.eq("meter_id", str(meter_id))
    return [feedback_case_from_row(row) for row in response_rows(query.execute())]


def load_fraction_profiles(client: Any) -> dict[UUID, int]:
    response = (
        client.table("meter_ocr_profiles")
        .select("meter_id,mechanical_fraction_digits")
        .execute()
    )
    profiles: dict[UUID, int] = {}
    for row in response_rows(response):
        fraction_digits = row.get("mechanical_fraction_digits")
        if fraction_digits is not None:
            profiles[UUID(str(row["meter_id"]))] = int(fraction_digits)
    return profiles


def result_payload(result: OCRResult) -> dict[str, object]:
    return {
        "reading": None if result.reading is None else str(result.reading),
        "serial_number": result.serial_number,
        "confidence": result.confidence,
        "mechanical_digits": result.mechanical_digits,
        "mechanical_fraction_digits": result.mechanical_fraction_digits,
        "raw_text": result.raw_text,
    }


def build_ocr(settings: Settings) -> PaddleOCRService:
    return PaddleOCRService(
        preprocessor=ImagePreprocessor(
            PreprocessingConfig(
                max_dimension=settings.ocr_image_max_dimension,
                grayscale=settings.ocr_grayscale,
                enhance_contrast=settings.ocr_enhance_contrast,
                threshold=settings.ocr_threshold,
                perspective_correction=settings.ocr_perspective_correction,
            )
        ),
        parser=MeterReadingParser(),
        language=settings.ocr_language,
        cpu_threads=settings.ocr_cpu_threads,
    )


def run_regression(
    settings: Settings,
    *,
    status: str = "all",
    meter_id: UUID | None = None,
    limit: int = 500,
) -> dict[str, object]:
    if not settings.supabase_url or not settings.supabase_service_role_key.get_secret_value():
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    client = create_supabase_client(settings)
    cases = load_feedback_cases(
        client,
        status=status,
        meter_id=meter_id,
        limit=limit,
    )
    profiles = load_fraction_profiles(client)
    ocr = build_ocr(settings)
    results: list[dict[str, object]] = []
    passed = 0
    for case in cases:
        try:
            image_content = client.storage.from_(
                settings.supabase_storage_bucket
            ).download(case.photo_path)
            current = ocr.recognize(
                image_content,
                mechanical_fraction_digits=profiles.get(case.meter_id),
            )
            is_passed = current.reading == case.corrected_value
            if is_passed:
                passed += 1
            results.append(
                {
                    "feedback_id": str(case.id),
                    "meter_id": str(case.meter_id),
                    "status": case.status,
                    "saved_detected_value": str(case.detected_value),
                    "expected_value": str(case.corrected_value),
                    "passed": is_passed,
                    "current_result": result_payload(current),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "feedback_id": str(case.id),
                    "meter_id": str(case.meter_id),
                    "status": case.status,
                    "saved_detected_value": str(case.detected_value),
                    "expected_value": str(case.corrected_value),
                    "passed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    total = len(cases)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "safe_to_deploy": total == passed,
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run current OCR against user-corrected Supabase photos. "
            "The command exits with code 1 when any expected value regresses."
        ),
    )
    parser.add_argument(
        "--status",
        choices=("all", "pending", "profiled", "global_fixed"),
        default="all",
    )
    parser.add_argument("--meter-id", type=UUID)
    parser.add_argument("--limit", type=int, default=500)
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if not 1 <= arguments.limit <= 5000:
        parser.error("--limit must be between 1 and 5000")
    try:
        report = run_regression(
            Settings(),
            status=arguments.status,
            meter_id=arguments.meter_id,
            limit=arguments.limit,
        )
    except Exception as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["safe_to_deploy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
