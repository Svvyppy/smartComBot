from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast
from uuid import UUID

from src.application.interfaces import OCRResult
from src.config import Settings
from src.infrastructure.ocr import (
    ImagePreprocessor,
    MeterReadingParser,
    PaddleOCRService,
    PreprocessingConfig,
)


def find_sample(root: Path, sample_id: UUID | None) -> Path:
    if sample_id is not None:
        sample_dir = root / str(sample_id)
        if not (sample_dir / "metadata.json").is_file():
            raise ValueError(f"OCR debug sample {sample_id} was not found in {root}")
        return sample_dir

    metadata_files = list(root.glob("*/metadata.json"))
    if not metadata_files:
        raise ValueError(f"No OCR debug samples found in {root}")
    latest = max(metadata_files, key=lambda item: item.stat().st_mtime)
    return latest.parent


def load_metadata(sample_dir: Path) -> dict[str, object]:
    raw: object = json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("OCR debug metadata must be a JSON object")
    return cast(dict[str, object], raw)


def result_payload(result: OCRResult) -> dict[str, object]:
    return {
        "reading": None if result.reading is None else str(result.reading),
        "serial_number": result.serial_number,
        "confidence": result.confidence,
        "raw_text": result.raw_text,
    }


def recognize_sample(settings: Settings, sample_dir: Path) -> OCRResult:
    image_content = (sample_dir / "original.jpg").read_bytes()
    ocr = PaddleOCRService(
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
    return ocr.recognize(image_content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rerun current OCR against a labeled debug sample.",
    )
    parser.add_argument(
        "sample_id",
        nargs="?",
        type=UUID,
        help="Sample UUID; defaults to the most recently updated sample.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()
    settings = Settings()
    try:
        sample_dir = find_sample(settings.ocr_debug_dir, arguments.sample_id)
        metadata = load_metadata(sample_dir)
        rerun_result = recognize_sample(settings, sample_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return

    print(
        json.dumps(
            {
                "sample_id": metadata.get("sample_id"),
                "goal": metadata.get("goal"),
                "captured_at": metadata.get("captured_at"),
                "saved_result": metadata.get("current_result"),
                "rerun_result": result_payload(rerun_result),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
