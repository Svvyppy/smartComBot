from collections.abc import Iterable
from decimal import Decimal

import cv2
import numpy as np
import pytest

from src.infrastructure.ocr import (
    ImagePreprocessor,
    MeterReadingParser,
    PaddleOCRService,
    PreprocessingConfig,
)
from src.infrastructure.ocr.preprocessing import ImageArray


def _jpeg() -> bytes:
    image = np.full((500, 1000, 3), 220, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


class FakePage:
    json = {
        "res": {
            "rec_texts": ["Модель 201", "00123.4 m3", "№ 99887766"],
            "rec_scores": [0.99, 0.91, 0.88],
        }
    }


class FakeEngine:
    def __init__(self) -> None:
        self.predict_calls = 0

    def predict(self, input_image: ImageArray) -> Iterable[object]:
        self.predict_calls += 1
        assert input_image.ndim == 3
        assert input_image.shape[2] == 3
        return [FakePage()]


def test_paddle_adapter_reuses_engine_and_parses_v3_result() -> None:
    engine = FakeEngine()
    factory_calls: list[dict[str, object]] = []

    def factory(**options: object) -> FakeEngine:
        factory_calls.append(options)
        return engine

    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=factory,
    )

    first = service.recognize(_jpeg())
    prepared = ImagePreprocessor(PreprocessingConfig(max_dimension=1000)).process(_jpeg())
    second = service.recognize_image(prepared, previous_reading=Decimal("100"))

    assert first.reading == Decimal("123.4")
    assert first.serial_number == "99887766"
    assert second.reading == Decimal("123.4")
    assert engine.predict_calls == 2
    assert len(factory_calls) == 1
    assert factory_calls[0]["device"] == "cpu"
    assert factory_calls[0]["text_detection_model_name"] == "PP-OCRv5_mobile_det"


def test_paddle_adapter_reports_received_and_expected_image_shape() -> None:
    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: FakeEngine(),
    )

    invalid = np.zeros((10,), dtype=np.uint8)
    with pytest.raises(
        ValueError,
        match=r"expects an image shaped height × width × 3 channels; received 10",
    ):
        service.recognize_image(invalid)
