from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from src.application.interfaces import OCRResult
from src.application.ocr import OCRDebugService
from src.infrastructure.local import LocalOCRDebugSampleStore

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
CAPTURED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class FakeOCRExecutor:
    async def recognize(self, image_content: bytes, **_: object) -> OCRResult:
        return OCRResult(Decimal("123.4"), "998877", 0.91, ["00123.4", "№998877"])


async def test_debug_capture_persists_photo_result_and_expected_value(tmp_path: Path) -> None:
    store = LocalOCRDebugSampleStore(tmp_path)
    service = OCRDebugService(
        ocr=FakeOCRExecutor(),  # type: ignore[arg-type]
        samples=store,
    )

    capture = await service.capture(
        user_id=USER_ID,
        telegram_id=42,
        image_content=b"jpeg-data",
        captured_at=CAPTURED_AT,
    )
    await service.set_expected_value(
        sample_id=capture.sample_id,
        user_id=USER_ID,
        expected_value=Decimal("125.6"),
    )

    sample_dir = tmp_path / str(capture.sample_id)
    assert (sample_dir / "original.jpg").read_bytes() == b"jpeg-data"
    metadata = (sample_dir / "metadata.json").read_text(encoding="utf-8")
    assert '"status": "ready"' in metadata
    assert '"expected_value": "125.6"' in metadata
    assert '"reading": "123.4"' in metadata
    assert "00123.4" in metadata
