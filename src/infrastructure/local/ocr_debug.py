import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from src.application.interfaces import OCRResult


class LocalOCRDebugSampleStore:
    """Persist labeled OCR samples in a private Docker volume."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def create(
        self,
        *,
        user_id: UUID,
        telegram_id: int,
        image_content: bytes,
        captured_at: datetime,
        current_result: OCRResult | None,
        error: str | None,
    ) -> UUID:
        if not image_content:
            raise ValueError("Debug photo cannot be empty")
        sample_id = uuid4()
        sample_dir = self._root / str(sample_id)
        sample_dir.mkdir(parents=True, exist_ok=False)
        (sample_dir / "original.jpg").write_bytes(image_content)
        metadata: dict[str, object] = {
            "sample_id": str(sample_id),
            "user_id": str(user_id),
            "telegram_id": telegram_id,
            "captured_at": captured_at.isoformat(),
            "status": "awaiting_expected_value",
            "expected_value": None,
            "current_result": self._result_payload(current_result),
            "error": error,
            "image_file": "original.jpg",
        }
        self._write_metadata(sample_dir, metadata)
        return sample_id

    async def set_expected_value(
        self,
        *,
        sample_id: UUID,
        user_id: UUID,
        expected_value: Decimal,
    ) -> None:
        sample_dir = self._root / str(sample_id)
        metadata_path = sample_dir / "metadata.json"
        if not metadata_path.is_file():
            raise ValueError("OCR debug sample not found")
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("user_id") != str(user_id):
            raise ValueError("OCR debug sample does not belong to this user")
        metadata: dict[str, object] = dict(raw)
        metadata["expected_value"] = str(expected_value)
        metadata["status"] = "ready"
        self._write_metadata(sample_dir, metadata)

    @staticmethod
    def _result_payload(result: OCRResult | None) -> dict[str, object] | None:
        if result is None:
            return None
        return {
            "reading": None if result.reading is None else str(result.reading),
            "serial_number": result.serial_number,
            "confidence": result.confidence,
            "raw_text": result.raw_text,
        }

    @staticmethod
    def _write_metadata(sample_dir: Path, metadata: dict[str, object]) -> None:
        target = sample_dir / "metadata.json"
        temporary = sample_dir / "metadata.json.tmp"
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(target)
