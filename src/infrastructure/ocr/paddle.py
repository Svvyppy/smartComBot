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

_COUNTER_LINE = re.compile(r"^[\d\s.,:;\-ODQILJZSB]+$", re.IGNORECASE)
_EXPECTED_COUNTER_DIGITS = 8
_COUNTER_FRACTION_DIGITS = 3
_LCD_UNIT = re.compile(r"(?:k[bв][tтrр]|квт)", re.IGNORECASE)
_LCD_READING = re.compile(r"(?<!\d)(\d{1,6})[.,](\d{2})(?!\d)")
_LCD_PARTIAL_READING = re.compile(r"(?<!\d)(\d{1,6})[.,](\d)(?!\d)")
_LCD_FRACTION = re.compile(r"[.,](\d{2})(?!\d)")
_LCD_MIN_INTEGER_DIGITS = 3
_LCD_MAX_INTEGER_DIGITS = 6


@dataclass(frozen=True, slots=True)
class _OCRRegion:
    line: OCRTextLine
    polygon: NDArray[np.float32] | None


@dataclass(frozen=True, slots=True)
class _CounterReading:
    value: Decimal
    confidence: float
    mechanical_digits: str | None = None
    mechanical_fraction_digits: int | None = None


@dataclass(frozen=True, slots=True)
class _PartialLCDReading:
    integer: str
    fraction: str
    confidence: float
    display: ImageArray


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
        mechanical_fraction_digits: int | None = None,
    ) -> OCRResult:
        color_image, image = self._preprocessor.process_with_color(image_content)
        return self.recognize_image(
            image,
            source_image=color_image,
            previous_reading=previous_reading,
            max_delta=max_delta,
            mechanical_fraction_digits=mechanical_fraction_digits,
        )

    def recognize_image(
        self,
        image: ImageArray,
        *,
        source_image: ImageArray | None = None,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
        mechanical_fraction_digits: int | None = None,
    ) -> OCRResult:
        """Recognize an already prepared image while reusing the loaded OCR engine."""

        try:
            return self._recognize_image_once(
                image,
                source_image=source_image,
                previous_reading=previous_reading,
                max_delta=max_delta,
                mechanical_fraction_digits=mechanical_fraction_digits,
            )
        except RuntimeError:
            self._engine = None
            self._counter_recognizer = None
            return self._recognize_image_once(
                image,
                source_image=source_image,
                previous_reading=previous_reading,
                max_delta=max_delta,
                mechanical_fraction_digits=mechanical_fraction_digits,
            )

    def _recognize_image_once(
        self,
        image: ImageArray,
        *,
        source_image: ImageArray | None,
        previous_reading: Decimal | None,
        max_delta: Decimal | None,
        mechanical_fraction_digits: int | None,
    ) -> OCRResult:

        engine_image = self._ensure_three_channels(image)
        regions = self._predict_regions(engine_image)
        lines = [region.line for region in regions]
        parsed = self._parser.parse(
            lines,
            previous_reading=previous_reading,
            max_delta=max_delta,
        )
        counter = self._recognize_counter(
            self._ensure_three_channels(source_image) if source_image is not None else engine_image,
            regions,
            parsed.serial_number,
            mechanical_fraction_digits,
        )
        if counter is None:
            counter = self._recognize_lcd(
                self._ensure_three_channels(source_image)
                if source_image is not None
                else engine_image,
                regions,
            )
        if counter is None:
            return parsed
        return OCRResult(
            reading=counter.value,
            serial_number=parsed.serial_number,
            confidence=counter.confidence,
            raw_text=parsed.raw_text,
            mechanical_digits=counter.mechanical_digits,
            mechanical_fraction_digits=counter.mechanical_fraction_digits,
        )

    def _predict_regions(self, image: ImageArray) -> list[_OCRRegion]:
        pages = self._get_engine().predict(image, text_det_unclip_ratio=1.2)
        regions: list[_OCRRegion] = []
        for page in pages:
            regions.extend(self._extract_page_regions(page))
        return regions

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
        serial_number: str | None,
        mechanical_fraction_digits: int | None,
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

        if serial_number is not None and serial_number.upper().startswith("OB"):
            tenths_digits = self._recover_ob_tenths_digits(
                direct_digits,
                generic_digits,
            )
            if tenths_digits is not None:
                fraction_digits = (
                    1
                    if mechanical_fraction_digits is None
                    else mechanical_fraction_digits
                )
                return _CounterReading(
                    value=self._decimal_from_digits(tenths_digits, fraction_digits),
                    confidence=max(direct_confidence, region.line.confidence),
                    mechanical_digits=tenths_digits,
                    mechanical_fraction_digits=fraction_digits,
                )

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
            cell_result = self._recognize_counter_cells(display)
            if cell_result is not None:
                digits, confidence = cell_result
        if digits is None:
            return None

        fraction_digits = (
            _COUNTER_FRACTION_DIGITS
            if mechanical_fraction_digits is None
            else mechanical_fraction_digits
        )
        return _CounterReading(
            value=self._decimal_from_digits(digits, fraction_digits),
            confidence=confidence,
            mechanical_digits=digits,
            mechanical_fraction_digits=fraction_digits,
        )

    @staticmethod
    def _decimal_from_digits(digits: str, fraction_digits: int) -> Decimal:
        if not 0 <= fraction_digits <= 6:
            raise ValueError("mechanical_fraction_digits must be between 0 and 6")
        if fraction_digits == 0:
            return Decimal(digits)
        integer = digits[:-fraction_digits] or "0"
        fraction = digits[-fraction_digits:]
        return Decimal(f"{integer}.{fraction}")

    def _recognize_counter_cells(self, display: ImageArray) -> tuple[str, float] | None:
        height, width = display.shape[:2]
        cells: list[ImageArray] = []
        for index in range(_EXPECTED_COUNTER_DIGITS):
            x1 = int(width * index / _EXPECTED_COUNTER_DIGITS)
            x2 = int(width * (index + 1) / _EXPECTED_COUNTER_DIGITS)
            cell = display[int(height * 0.12) : int(height * 0.88), x1:x2]
            if cell.size == 0:
                return None
            cells.append(self._add_white_border(cell, 20))
        results = list(self._get_counter_recognizer().predict(cells, batch_size=1))
        if len(results) != _EXPECTED_COUNTER_DIGITS:
            return None

        digits: list[str] = []
        confidences: list[float] = []
        for result in results:
            text, confidence = self._extract_direct_result(result)
            digit = self._single_counter_digit(text)
            if digit is None or confidence < 0.2:
                return None
            digits.append(digit)
            confidences.append(confidence)
        return "".join(digits), min(confidences)

    @staticmethod
    def _single_counter_digit(text: str) -> str | None:
        digits = PaddleOCRService._digits(text)
        if len(digits) == 1:
            return digits
        if len(digits) == 2 and digits[1] == "1":
            return digits[0]
        normalized = text.strip().upper()
        substitutions = {
            "D": "0",
            "O": "0",
            "Q": "0",
            "I": "1",
            "L": "1",
            "T": "1",
            "|": "1",
            "Z": "2",
            "S": "5",
            "G": "6",
            "B": "8",
        }
        return substitutions.get(normalized)

    @staticmethod
    def _recover_ob_tenths_digits(
        direct_digits: str,
        generic_digits: str,
    ) -> str | None:
        if len(direct_digits) == 6:
            return direct_digits
        if len(direct_digits) == 7:
            return direct_digits[1:-1].zfill(6)
        if len(direct_digits) >= 8:
            return direct_digits[:6]
        if len(generic_digits) == 8:
            return generic_digits[2:-2].zfill(6)
        return None

    def _recognize_lcd(
        self,
        source_image: ImageArray,
        regions: list[_OCRRegion],
    ) -> _CounterReading | None:
        candidates = [
            region
            for region in regions
            if self._is_lcd_line(region, regions, source_image.shape[0])
        ]
        if not candidates:
            return None
        region = max(candidates, key=self._polygon_height)
        assert region.polygon is not None
        integer_digits = self._digits(region.line.text)
        source_polygon = region.polygon

        source_regions = self._predict_regions(source_image)
        source_candidates = [
            source_region
            for source_region in source_regions
            if self._is_lcd_line(source_region, source_regions, source_image.shape[0])
        ]
        if source_candidates:
            source_region = max(source_candidates, key=self._polygon_height)
            assert source_region.polygon is not None
            source_polygon = source_region.polygon

        partials: list[_PartialLCDReading] = []
        for horizontal_scale in (2.7, 3.0):
            display = self._crop_lcd_line(source_image, source_polygon, horizontal_scale)
            if display.size == 0:
                continue
            bordered_display = self._add_white_border(display, 20)
            display_regions = self._predict_regions(bordered_display)
            direct = self._find_lcd_reading(
                display_regions,
                integer_digits,
            )
            if direct is not None:
                return direct
            partial = self._find_partial_lcd_reading(
                display_regions,
                integer_digits,
                display,
            )
            if partial is not None:
                partials.append(partial)

        if partials:
            partial = max(partials, key=lambda item: item.confidence)
            last_digit = self._recognize_lcd_last_digit(partial.display)
            if last_digit is not None:
                digit, digit_confidence = last_digit
                return _CounterReading(
                    value=Decimal(f"{partial.integer}.{partial.fraction}{digit}"),
                    confidence=min(partial.confidence, digit_confidence),
                )

        if len(integer_digits) < 4:
            return None
        display = self._crop_lcd_line(source_image, source_polygon, 2.4)
        if display.size == 0:
            return None
        height, width = display.shape[:2]
        fraction_image = display[int(height * 0.35) :, int(width * 0.7) :]
        if fraction_image.size == 0:
            return None
        fraction_image = self._add_white_border(fraction_image, 30)
        fraction = self._find_lcd_fraction(self._predict_regions(fraction_image))
        if fraction is None:
            return None
        fraction_digits, fraction_confidence = fraction
        return _CounterReading(
            value=Decimal(f"{integer_digits}.{fraction_digits}"),
            confidence=min(region.line.confidence, fraction_confidence),
        )

    @classmethod
    def _is_lcd_line(
        cls,
        region: _OCRRegion,
        regions: list[_OCRRegion],
        image_height: int,
    ) -> bool:
        if region.polygon is None or _COUNTER_LINE.fullmatch(region.line.text) is None:
            return False
        digit_count = len(cls._digits(region.line.text))
        if not _LCD_MIN_INTEGER_DIGITS <= digit_count <= _LCD_MAX_INTEGER_DIGITS:
            return False
        height = cls._polygon_height(region)
        if height < image_height * 0.08:
            return False
        center_y = float(region.polygon[:, 1].mean())
        return any(
            other.polygon is not None
            and _LCD_UNIT.search(other.line.text) is not None
            and 0 < center_y - float(other.polygon[:, 1].mean()) < height * 1.5
            for other in regions
        )

    @staticmethod
    def _crop_lcd_line(
        source_image: ImageArray,
        polygon: NDArray[np.float32],
        horizontal_scale: float,
    ) -> ImageArray:
        min_y = float(polygon[:, 1].min())
        max_y = float(polygon[:, 1].max())
        height = max_y - min_y
        center_x = float((polygon[:, 0].min() + polygon[:, 0].max()) / 2)
        image_height, image_width = source_image.shape[:2]
        x1 = max(0, int(center_x - horizontal_scale * height))
        x2 = min(image_width, int(center_x + horizontal_scale * height))
        y1 = max(0, int(min_y - 0.15 * height))
        y2 = min(image_height, int(max_y + 0.45 * height))
        return source_image[y1:y2, x1:x2]

    @staticmethod
    def _add_white_border(image: ImageArray, size: int) -> ImageArray:
        return np.asarray(
            cv2.copyMakeBorder(
                image,
                size,
                size,
                size,
                size,
                cv2.BORDER_CONSTANT,
                value=(255, 255, 255),
            ),
            dtype=np.uint8,
        )

    @classmethod
    def _find_lcd_reading(
        cls,
        regions: list[_OCRRegion],
        expected_integer_fragment: str,
    ) -> _CounterReading | None:
        matches: list[_CounterReading] = []
        for region in regions:
            for match in _LCD_READING.finditer(region.line.text):
                integer, fraction = match.groups()
                if not cls._lcd_integer_matches(integer, expected_integer_fragment):
                    continue
                matches.append(
                    _CounterReading(
                        value=Decimal(f"{integer}.{fraction}"),
                        confidence=region.line.confidence,
                    )
                )
        return max(matches, key=lambda item: item.confidence, default=None)

    @classmethod
    def _find_partial_lcd_reading(
        cls,
        regions: list[_OCRRegion],
        expected_integer_fragment: str,
        display: ImageArray,
    ) -> _PartialLCDReading | None:
        matches: list[_PartialLCDReading] = []
        for region in regions:
            for match in _LCD_PARTIAL_READING.finditer(region.line.text):
                integer, fraction = match.groups()
                if not cls._lcd_integer_matches(integer, expected_integer_fragment):
                    continue
                matches.append(
                    _PartialLCDReading(
                        integer=integer,
                        fraction=fraction,
                        confidence=region.line.confidence,
                        display=display,
                    )
                )
        return max(matches, key=lambda item: item.confidence, default=None)

    def _recognize_lcd_last_digit(self, display: ImageArray) -> tuple[str, float] | None:
        height, width = display.shape[:2]
        raw_digit_image = display[int(height * 0.3) :, int(width * 0.88) : int(width * 0.94)]
        if raw_digit_image.size == 0:
            return None
        digit_image = self._add_white_border(raw_digit_image, 30)
        results = list(self._get_counter_recognizer().predict([digit_image], batch_size=1))
        if not results:
            return None
        text, confidence = self._extract_direct_result(results[0])
        digits = self._digits(text)
        if len(digits) == 1 and confidence >= 0.5:
            return digits, confidence
        if (
            text.strip().upper() in {"I", "L", "|"}
            and confidence >= 0.8
            and self._dark_pixel_ratio(raw_digit_image) < 0.055
        ):
            return "1", confidence
        return None

    @staticmethod
    def _lcd_integer_matches(integer: str, expected_fragment: str) -> bool:
        normalized_integer = integer.lstrip("0") or "0"
        normalized_fragment = expected_fragment.lstrip("0") or "0"
        return normalized_integer.startswith(normalized_fragment)

    @staticmethod
    def _dark_pixel_ratio(image: ImageArray) -> float:
        grayscale = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
        mask = cv2.adaptiveThreshold(
            grayscale,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            7,
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), dtype=np.uint8))
        return float(np.count_nonzero(mask)) / float(mask.size)

    @staticmethod
    def _find_lcd_fraction(regions: list[_OCRRegion]) -> tuple[str, float] | None:
        matches: list[tuple[float, str]] = []
        for region in regions:
            match = _LCD_FRACTION.search(region.line.text)
            if match is not None:
                matches.append((region.line.confidence, match.group(1)))
        if not matches:
            return None
        confidence, fraction = max(matches, key=lambda item: item[0])
        return fraction, confidence

    @staticmethod
    def _polygon_height(region: _OCRRegion) -> float:
        if region.polygon is None:
            return 0.0
        return float(region.polygon[:, 1].max() - region.polygon[:, 1].min())

    @staticmethod
    def _is_counter_line(region: _OCRRegion) -> bool:
        if region.polygon is None or _COUNTER_LINE.fullmatch(region.line.text) is None:
            return False
        digit_count = len(PaddleOCRService._digits(region.line.text))
        return _EXPECTED_COUNTER_DIGITS - 1 <= digit_count <= _EXPECTED_COUNTER_DIGITS * 2

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
