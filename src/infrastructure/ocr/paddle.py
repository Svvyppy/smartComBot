from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from src.application.interfaces import OCRResult, OCRTextLine
from src.infrastructure.ocr.parser import MeterReadingParser
from src.infrastructure.ocr.preprocessing import ImageArray, ImagePreprocessor


class PaddleEngine(Protocol):
    def predict(self, input_image: ImageArray, **kwargs: object) -> Iterable[object]: ...


class PaddleTextRecognizer(Protocol):
    def predict(
        self,
        input_image: list[ImageArray],
        *,
        batch_size: int = 1,
    ) -> Iterable[object]: ...


EngineFactory = Callable[..., PaddleEngine]
RecognizerFactory = Callable[..., PaddleTextRecognizer]

_COUNTER_LINE = re.compile(r"^[\d\s.,:;-]+$")
_EXPECTED_COUNTER_DIGITS = 8
_COUNTER_FRACTION_DIGITS = 3


@dataclass(frozen=True, slots=True)
class _OCRRegion:
    line: OCRTextLine
    polygon: NDArray[np.float32] | None


@dataclass(frozen=True, slots=True)
class _CounterReading:
    value: Decimal
    confidence: float


class PaddleOCRService:
    """CPU-only PaddleOCR adapter using the 3.x ``predict`` API."""

    def __init__(
        self,
        *,
        preprocessor: ImagePreprocessor,
        parser: MeterReadingParser,
        language: str = "en",
        cpu_threads: int = 2,
        engine_factory: EngineFactory | None = None,
        counter_recognizer_factory: RecognizerFactory | None = None,
    ) -> None:
        if cpu_threads < 1:
            raise ValueError("cpu_threads must be positive")
        self._engine_factory = engine_factory or self._create_engine
        self._counter_recognizer_factory = (
            counter_recognizer_factory or self._create_counter_recognizer
        )
        self._engine_options: dict[str, object] = {
            "lang": language,
            "device": "cpu",
            "cpu_threads": cpu_threads,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_recognition_model_name": "PP-OCRv5_mobile_rec",
        }
        self._counter_recognizer_options: dict[str, object] = {
            "model_name": "en_PP-OCRv5_mobile_rec",
            "device": "cpu",
            "cpu_threads": cpu_threads,
        }
        self._engine: PaddleEngine | None = None
        self._counter_recognizer: PaddleTextRecognizer | None = None
        self._preprocessor = preprocessor
        self._parser = parser

    def _get_engine(self) -> PaddleEngine:
        if self._engine is None:
            self._engine = self._engine_factory(
                **self._engine_options,
            )
        return self._engine

    def _get_counter_recognizer(self) -> PaddleTextRecognizer:
        if self._counter_recognizer is None:
            self._counter_recognizer = self._counter_recognizer_factory(
                **self._counter_recognizer_options,
            )
        return self._counter_recognizer

    def recognize(
        self,
        image_content: bytes,
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
    ) -> OCRResult:
        color_image, image = self._preprocessor.process_with_color(image_content)
        return self.recognize_image(
            image,
            source_image=color_image,
            previous_reading=previous_reading,
            max_delta=max_delta,
        )

    def recognize_image(
        self,
        image: ImageArray,
        *,
        source_image: ImageArray | None = None,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
    ) -> OCRResult:
        """Recognize an already prepared image while reusing the loaded OCR engine."""

        engine_image = self._ensure_three_channels(image)
        pages = self._get_engine().predict(engine_image, text_det_unclip_ratio=1.2)
        regions: list[_OCRRegion] = []
        for page in pages:
            regions.extend(self._extract_page_regions(page))
        lines = [region.line for region in regions]
        parsed = self._parser.parse(
            lines,
            previous_reading=previous_reading,
            max_delta=max_delta,
        )
        counter = self._recognize_counter(
            self._ensure_three_channels(source_image) if source_image is not None else engine_image,
            regions,
        )
        if counter is None:
            return parsed
        return OCRResult(
            reading=counter.value,
            serial_number=parsed.serial_number,
            confidence=counter.confidence,
            raw_text=parsed.raw_text,
        )

    @staticmethod
    def _ensure_three_channels(image: ImageArray) -> ImageArray:
        """Convert supported OpenCV images to PaddleOCR's H×W×3 input contract."""

        if image.ndim == 2:
            return np.asarray(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
        if image.ndim == 3 and image.shape[2] == 1:
            return np.asarray(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
        if image.ndim == 3 and image.shape[2] == 4:
            return np.asarray(cv2.cvtColor(image, cv2.COLOR_BGRA2BGR), dtype=np.uint8)
        if image.ndim == 3 and image.shape[2] == 3:
            return image
        received = " × ".join(str(dimension) for dimension in image.shape)
        raise ValueError(
            "PaddleOCR expects an image shaped height × width × 3 channels; "
            f"received {received or 'no dimensions'}"
        )

    @staticmethod
    def _create_engine(**options: object) -> PaddleEngine:
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]

        return cast(PaddleEngine, PaddleOCR(**options))

    @staticmethod
    def _create_counter_recognizer(**options: object) -> PaddleTextRecognizer:
        from paddleocr import TextRecognition

        return cast(PaddleTextRecognizer, TextRecognition(**options))

    @classmethod
    def _extract_page_regions(cls, page: object) -> list[_OCRRegion]:
        payload = cls._extract_result_payload(page)
        if payload is None:
            return []
        raw_texts = payload.get("rec_texts")
        raw_scores = payload.get("rec_scores")
        raw_polygons = payload.get("rec_polys")
        if not cls._is_iterable_value(raw_texts):
            return []

        texts = list(cast(Iterable[object], raw_texts))
        scores: list[object] = []
        polygons: list[object] = []
        if cls._is_iterable_value(raw_scores):
            scores = list(cast(Iterable[object], raw_scores))
        if cls._is_iterable_value(raw_polygons):
            polygons = list(cast(Iterable[object], raw_polygons))

        result: list[_OCRRegion] = []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                continue
            result.append(
                _OCRRegion(
                    line=OCRTextLine(
                        text=text.strip(),
                        confidence=cls._confidence_at(scores, index),
                    ),
                    polygon=cls._polygon_at(polygons, index),
                )
            )
        return result

    @classmethod
    def _extract_page_lines(cls, page: object) -> list[OCRTextLine]:
        return [region.line for region in cls._extract_page_regions(page)]

    @staticmethod
    def _extract_result_payload(page: object) -> Mapping[str, object] | None:
        raw_payload: Any = getattr(page, "json", page)
        if callable(raw_payload):
            raw_payload = raw_payload()
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                return None
        if not isinstance(raw_payload, Mapping):
            return None

        payload = cast(Mapping[str, object], raw_payload)
        nested = payload.get("res")
        if isinstance(nested, Mapping):
            payload = cast(Mapping[str, object], nested)
        return payload

    @staticmethod
    def _polygon_at(polygons: list[object], index: int) -> NDArray[np.float32] | None:
        if index >= len(polygons):
            return None
        try:
            polygon = np.asarray(polygons[index], dtype=np.float32)
        except (TypeError, ValueError):
            return None
        if polygon.shape != (4, 2):
            return None
        return polygon

    def _recognize_counter(
        self,
        source_image: ImageArray,
        regions: list[_OCRRegion],
    ) -> _CounterReading | None:
        candidates = [region for region in regions if self._is_counter_line(region)]
        if not candidates:
            return None
        region = max(
            candidates,
            key=lambda item: (
                len(self._digits(item.line.text)) == _EXPECTED_COUNTER_DIGITS,
                item.line.confidence,
            ),
        )
        assert region.polygon is not None
        display = ImagePreprocessor._warp_four_points(source_image, region.polygon)
        if display.size == 0:
            return None

        height, width = display.shape[:2]
        last_digit = display[max(0, int(height * 0.55)) :, max(0, int(width * 0.82)) :]
        if last_digit.size == 0:
            return None
        last_digit = np.asarray(
            cv2.copyMakeBorder(
                last_digit,
                30,
                30,
                30,
                30,
                cv2.BORDER_CONSTANT,
                value=(255, 255, 255),
            ),
            dtype=np.uint8,
        )
        direct_results = list(
            self._get_counter_recognizer().predict([display, last_digit], batch_size=1)
        )
        if len(direct_results) < 2:
            return None
        direct_text, direct_confidence = self._extract_direct_result(direct_results[0])
        last_text, last_confidence = self._extract_direct_result(direct_results[1])
        direct_digits = self._digits(direct_text)
        last_digits = self._digits(last_text)
        generic_digits = self._digits(region.line.text)

        digits: str | None = None
        confidence = 0.0
        if len(direct_digits) == _EXPECTED_COUNTER_DIGITS and direct_confidence >= 0.75:
            digits = direct_digits
            confidence = direct_confidence
        elif (
            len(direct_digits) == _EXPECTED_COUNTER_DIGITS - 1
            and len(last_digits) == 1
            and direct_confidence >= 0.75
            and last_confidence >= 0.5
        ):
            digits = f"{direct_digits}{last_digits}"
            confidence = min(direct_confidence, last_confidence)
        elif len(generic_digits) == _EXPECTED_COUNTER_DIGITS:
            digits = generic_digits
            confidence = region.line.confidence
        if digits is None:
            return None

        integer = digits[:-_COUNTER_FRACTION_DIGITS]
        fraction = digits[-_COUNTER_FRACTION_DIGITS:]
        return _CounterReading(value=Decimal(f"{integer}.{fraction}"), confidence=confidence)

    @staticmethod
    def _is_counter_line(region: _OCRRegion) -> bool:
        if region.polygon is None or _COUNTER_LINE.fullmatch(region.line.text) is None:
            return False
        digit_count = len(PaddleOCRService._digits(region.line.text))
        return _EXPECTED_COUNTER_DIGITS - 1 <= digit_count <= _EXPECTED_COUNTER_DIGITS + 2

    @staticmethod
    def _digits(text: str) -> str:
        return "".join(character for character in text if character.isdigit())

    @classmethod
    def _extract_direct_result(cls, result: object) -> tuple[str, float]:
        payload = cls._extract_result_payload(result)
        if payload is None:
            return "", 0.0
        text = payload.get("rec_text")
        score = payload.get("rec_score")
        if not isinstance(text, str):
            return "", 0.0
        try:
            confidence = min(max(float(score), 0.0), 1.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            confidence = 0.0
        return text.strip(), confidence

    @staticmethod
    def _is_iterable_value(value: object) -> bool:
        return isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping))

    @staticmethod
    def _confidence_at(scores: list[object], index: int) -> float:
        if index >= len(scores):
            return 0.0
        try:
            return min(max(float(scores[index]), 0.0), 1.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
