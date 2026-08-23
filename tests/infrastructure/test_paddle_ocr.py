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

    def predict(self, input_image: ImageArray, **_: object) -> Iterable[object]:
        self.predict_calls += 1
        assert input_image.ndim == 3
        assert input_image.shape[2] == 3
        return [FakePage()]


class FailingEngine:
    def predict(self, input_image: ImageArray, **_: object) -> Iterable[object]:
        raise RuntimeError("std::exception")


class FakeMechanicalPage:
    def __init__(self, counter_text: str, serial_text: str) -> None:
        self.json = {
            "res": {
                "rec_texts": [counter_text, serial_text, "K=1,4815×10 m/мин."],
                "rec_scores": [0.78, 0.97, 0.95],
                "rec_polys": [
                    [[100, 100], [900, 100], [900, 200], [100, 200]],
                    [[100, 250], [500, 250], [500, 300], [100, 300]],
                    [[100, 350], [500, 350], [500, 400], [100, 400]],
                ],
            }
        }


class FakeMechanicalEngine:
    def __init__(self, counter_text: str, serial_text: str) -> None:
        self._page = FakeMechanicalPage(counter_text, serial_text)

    def predict(self, input_image: ImageArray, **kwargs: object) -> Iterable[object]:
        assert input_image.shape == (500, 1000, 3)
        assert kwargs["text_det_unclip_ratio"] == 1.2
        return [self._page]


class FakeRecognitionResult:
    def __init__(self, text: str, score: float) -> None:
        self.json = {"res": {"rec_text": text, "rec_score": score}}


class FakeCounterRecognizer:
    def __init__(self, direct_text: str, direct_score: float, last_text: str, last_score: float):
        self._results = [
            FakeRecognitionResult(direct_text, direct_score),
            FakeRecognitionResult(last_text, last_score),
        ]

    def predict(
        self,
        input_image: list[ImageArray],
        *,
        batch_size: int = 1,
    ) -> Iterable[object]:
        assert len(input_image) == 2
        assert all(image.ndim == 3 for image in input_image)
        assert batch_size == 1
        return self._results


class FakeCellCounterRecognizer:
    def predict(
        self,
        input_image: list[ImageArray],
        *,
        batch_size: int = 1,
    ) -> Iterable[object]:
        assert batch_size == 1
        if len(input_image) == 2:
            return [
                FakeRecognitionResult("00272", 0.39),
                FakeRecognitionResult("", 0.0),
            ]
        assert len(input_image) == 8
        return [
            FakeRecognitionResult(text, score)
            for text, score in zip(
                ["D", "0", "T", "2", "7", "91", "2", "9"],
                [0.76, 0.58, 0.41, 0.88, 0.78, 0.91, 0.98, 0.43],
                strict=True,
            )
        ]


class FakeLCDDigitRecognizer:
    def __init__(self, text: str, score: float) -> None:
        self._result = FakeRecognitionResult(text, score)

    def predict(
        self,
        input_image: list[ImageArray],
        *,
        batch_size: int = 1,
    ) -> Iterable[object]:
        assert len(input_image) == 1
        assert input_image[0].ndim == 3
        assert batch_size == 1
        return [self._result]


class FakeLCDPage:
    def __init__(
        self,
        texts: list[str],
        scores: list[float],
        polygons: list[list[list[int]]] | None = None,
    ) -> None:
        payload: dict[str, object] = {"rec_texts": texts, "rec_scores": scores}
        if polygons is not None:
            payload["rec_polys"] = polygons
        self.json = {"res": payload}


class FakeLCDEngine:
    def __init__(self, pages: list[FakeLCDPage]) -> None:
        self._pages = pages
        self.predict_calls = 0

    def predict(self, input_image: ImageArray, **kwargs: object) -> Iterable[object]:
        assert input_image.ndim == 3
        assert input_image.shape[2] == 3
        assert kwargs["text_det_unclip_ratio"] == 1.2
        page = self._pages[self.predict_calls]
        self.predict_calls += 1
        return [page]


def _lcd_source_page(reading: str, unit: str = "KBTU") -> FakeLCDPage:
    return FakeLCDPage(
        [unit, reading, "Ne.22297698"],
        [0.72, 0.82, 0.91],
        [
            [[450, 150], [550, 150], [550, 180], [450, 180]],
            [[350, 200], [650, 200], [650, 320], [350, 320]],
            [[100, 40], [350, 40], [350, 80], [100, 80]],
        ],
    )


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


def test_paddle_adapter_recreates_predictor_after_runtime_failure() -> None:
    engines = [FailingEngine(), FakeEngine()]
    factory_calls = 0

    def factory(**_: object) -> FailingEngine | FakeEngine:
        nonlocal factory_calls
        engine = engines[factory_calls]
        factory_calls += 1
        return engine

    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=factory,
    )

    result = service.recognize(_jpeg())

    assert result.reading == Decimal("123.4")
    assert factory_calls == 2


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


@pytest.mark.parametrize(
    (
        "generic_text",
        "serial_text",
        "direct_text",
        "direct_score",
        "last_text",
        "last_score",
        "expected_reading",
        "expected_serial",
    ),
    [
        (
            "00127:042",
            "N164701553",
            "0012704",
            0.83,
            "4",
            0.61,
            Decimal("127.044"),
            "N164701553",
        ),
        (
            "60420.370",
            "OB 8980478 13",
            "00420371",
            0.94,
            "1U",
            0.26,
            Decimal("420.3"),
            "OB 898047813",
        ),
    ],
)
def test_paddle_adapter_recovers_eight_wheel_counter_reading(
    generic_text: str,
    serial_text: str,
    direct_text: str,
    direct_score: float,
    last_text: str,
    last_score: float,
    expected_reading: Decimal,
    expected_serial: str,
) -> None:
    recognizer_calls: list[dict[str, object]] = []

    def recognizer_factory(**options: object) -> FakeCounterRecognizer:
        recognizer_calls.append(options)
        return FakeCounterRecognizer(direct_text, direct_score, last_text, last_score)

    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: FakeMechanicalEngine(generic_text, serial_text),
        counter_recognizer_factory=recognizer_factory,
    )

    result = service.recognize(_jpeg())

    assert result.reading == expected_reading
    assert result.serial_number == expected_serial
    assert len(recognizer_calls) == 1
    assert recognizer_calls[0]["model_name"] == "en_PP-OCRv5_mobile_rec"


def test_paddle_adapter_reads_transitional_wheels_cell_by_cell() -> None:
    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: FakeMechanicalEngine(
            "0J01321791219",
            "N164701553",
        ),
        counter_recognizer_factory=lambda **_: FakeCellCounterRecognizer(),
    )

    result = service.recognize(_jpeg())

    assert result.reading == Decimal("127.929")
    assert result.serial_number == "N164701553"
    assert result.mechanical_digits == "00127929"
    assert result.mechanical_fraction_digits == 3


def test_paddle_adapter_uses_tenths_for_ob_mechanical_meter() -> None:
    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: FakeMechanicalEngine(
            "66420728",
            "OB 898047813",
        ),
        counter_recognizer_factory=lambda **_: FakeCounterRecognizer(
            "8042073",
            0.46,
            "",
            0.0,
        ),
    )

    result = service.recognize(_jpeg())

    assert result.reading == Decimal("420.7")
    assert result.serial_number == "OB 898047813"
    assert result.mechanical_digits == "004207"
    assert result.mechanical_fraction_digits == 1


def test_paddle_adapter_applies_meter_specific_fraction_digits() -> None:
    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: FakeMechanicalEngine(
            "00127:042",
            "N164701553",
        ),
        counter_recognizer_factory=lambda **_: FakeCounterRecognizer(
            "00127042",
            0.83,
            "2",
            0.61,
        ),
    )

    result = service.recognize(_jpeg(), mechanical_fraction_digits=2)

    assert result.reading == Decimal("1270.42")
    assert result.mechanical_digits == "00127042"
    assert result.mechanical_fraction_digits == 2


def test_paddle_adapter_recognizes_complete_lcd_reading_on_expanded_crop() -> None:
    engine = FakeLCDEngine(
        [
            _lcd_source_page("346", unit="KBrou"),
            _lcd_source_page("346"),
            FakeLCDPage(["3465.81"], [0.87]),
        ]
    )
    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: engine,
    )

    result = service.recognize(_jpeg())

    assert result.reading == Decimal("3465.81")
    assert result.serial_number == "22297698"
    assert result.confidence == 0.87
    assert engine.predict_calls == 3


def test_paddle_adapter_combines_lcd_integer_with_separate_fraction_crop() -> None:
    engine = FakeLCDEngine(
        [
            _lcd_source_page("1172"),
            _lcd_source_page("117"),
            FakeLCDPage(["117"], [0.71]),
            FakeLCDPage(["101172"], [0.66]),
            FakeLCDPage(["C.55"], [0.74]),
        ]
    )
    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: engine,
    )

    result = service.recognize(_jpeg())

    assert result.reading == Decimal("1172.55")
    assert result.serial_number == "22297698"
    assert result.confidence == 0.74
    assert engine.predict_calls == 5


def test_paddle_adapter_completes_thin_last_lcd_digit_from_its_cell() -> None:
    engine = FakeLCDEngine(
        [
            _lcd_source_page("346", unit="KBrou"),
            _lcd_source_page("346"),
            FakeLCDPage(["3465.8"], [0.90]),
            FakeLCDPage(["13465.8"], [0.93]),
        ]
    )
    service = PaddleOCRService(
        preprocessor=ImagePreprocessor(PreprocessingConfig(max_dimension=1000)),
        parser=MeterReadingParser(),
        engine_factory=lambda **_: engine,
        counter_recognizer_factory=lambda **_: FakeLCDDigitRecognizer("I", 0.86),
    )

    result = service.recognize(_jpeg())

    assert result.reading == Decimal("3465.81")
    assert result.serial_number == "22297698"
    assert result.confidence == 0.86
    assert engine.predict_calls == 4
