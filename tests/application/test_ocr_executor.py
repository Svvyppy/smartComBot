import threading
from decimal import Decimal

from src.application.interfaces import OCRResult
from src.application.ocr import OCRExecutor


class ThreadRecordingOCR:
    def __init__(self) -> None:
        self.thread_id: int | None = None

    def recognize(
        self,
        image_content: bytes,
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
        mechanical_fraction_digits: int | None = None,
    ) -> OCRResult:
        self.thread_id = threading.get_ident()
        return OCRResult(Decimal("12.3"), None, 0.9, ["12.3"])


async def test_executor_runs_engine_in_worker_thread() -> None:
    engine = ThreadRecordingOCR()
    result = await OCRExecutor(engine).recognize(b"photo")

    assert result.reading == Decimal("12.3")
    assert engine.thread_id is not None
    assert engine.thread_id != threading.get_ident()
