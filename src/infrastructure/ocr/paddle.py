from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any, Protocol, cast

from src.application.interfaces import OCRResult, OCRTextLine
from src.infrastructure.ocr.parser import MeterReadingParser
from src.infrastructure.ocr.preprocessing import ImageArray, ImagePreprocessor


class PaddleEngine(Protocol):
    def predict(self, input_image: ImageArray) -> Iterable[object]: ...


EngineFactory = Callable[..., PaddleEngine]


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
    ) -> None:
        if cpu_threads < 1:
            raise ValueError("cpu_threads must be positive")
        self._engine_factory = engine_factory or self._create_engine
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
        self._engine: PaddleEngine | None = None
        self._preprocessor = preprocessor
        self._parser = parser

    def _get_engine(self) -> PaddleEngine:
        if self._engine is None:
            self._engine = self._engine_factory(
                **self._engine_options,
            )
        return self._engine

    def recognize(
        self,
        image_content: bytes,
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
    ) -> OCRResult:
        image = self._preprocessor.process(image_content)
        return self.recognize_image(
            image,
            previous_reading=previous_reading,
            max_delta=max_delta,
        )

    def recognize_image(
        self,
        image: ImageArray,
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
    ) -> OCRResult:
        """Recognize an already prepared image while reusing the loaded OCR engine."""

        pages = self._get_engine().predict(image)
        lines: list[OCRTextLine] = []
        for page in pages:
            lines.extend(self._extract_page_lines(page))
        return self._parser.parse(
            lines,
            previous_reading=previous_reading,
            max_delta=max_delta,
        )

    @staticmethod
    def _create_engine(**options: object) -> PaddleEngine:
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]

        return cast(PaddleEngine, PaddleOCR(**options))

    @staticmethod
    def _extract_page_lines(page: object) -> list[OCRTextLine]:
        raw_payload: Any = getattr(page, "json", page)
        if callable(raw_payload):
            raw_payload = raw_payload()
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                return []
        if not isinstance(raw_payload, Mapping):
            return []

        payload = cast(Mapping[str, object], raw_payload)
        nested = payload.get("res")
        if isinstance(nested, Mapping):
            payload = cast(Mapping[str, object], nested)
        raw_texts = payload.get("rec_texts")
        raw_scores = payload.get("rec_scores")
        if not PaddleOCRService._is_iterable_value(raw_texts):
            return []

        texts = list(cast(Iterable[object], raw_texts))
        scores: list[object] = []
        if PaddleOCRService._is_iterable_value(raw_scores):
            scores = list(cast(Iterable[object], raw_scores))

        result: list[OCRTextLine] = []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                continue
            confidence = PaddleOCRService._confidence_at(scores, index)
            result.append(OCRTextLine(text=text.strip(), confidence=confidence))
        return result

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
