from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from src.application.interfaces import OCRResult, OCRTextLine

_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё0-9])"
    r"(?:\d{1,3}(?:[ '\u00a0]\d{3})+(?:[.,]\d{1,4})?|\d{1,12}(?:[.,]\d{1,4})?)"
    r"(?![A-Za-zА-Яа-яЁё0-9])"
)
_SERIAL_LABEL = r"(?:s\s*/?\s*n|serial|сер(?:ия|ийный)?|номер|№|n\s*(?:[oоeеg]\.?|[°º]))"
_SERIAL_PATTERN = re.compile(
    rf"{_SERIAL_LABEL}\s*[:#№-]?\s*([A-ZА-Я0-9-]{{5,20}})",
    re.IGNORECASE,
)
_PREFIXED_SERIAL_PATTERN = re.compile(
    r"(?<![A-ZА-Я0-9])(?P<prefix>N[°º]?|OB|ОВ)\s*[:#№-]?\s*"
    r"(?P<number>\d(?:[ -]?\d){5,19})(?!\d)",
    re.IGNORECASE,
)
_SERIAL_MARKER = re.compile(_SERIAL_LABEL, re.I)
_ELECTRICAL_NOISE = re.compile(
    r"(?:\b\d+(?:[.,]\d+)?\s*(?:v|a|hz|в|а|гц)\b|\d+\s*[-–]\s*\d+\s*a\b)",
    re.I,
)
_METER_UNIT = re.compile(r"(?:m[³3]|м[³3]|kwh|квт)", re.I)
_TECHNICAL_COEFFICIENT = re.compile(
    r"(?:^\s*[×x]\s*\d|(?:^|\s)k\s*=|\b(?:q[nm]|tmax|pmax)\b|имп\s*[.=])",
    re.I,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    value: Decimal
    confidence: float
    score: float
    text: str


class MeterReadingParser:
    """Choose the most plausible counter value from OCR text lines."""

    def parse(
        self,
        lines: Sequence[OCRTextLine],
        *,
        previous_reading: Decimal | None = None,
        max_delta: Decimal | None = None,
    ) -> OCRResult:
        candidates: list[_Candidate] = []
        for line in lines:
            for match in _NUMBER_PATTERN.finditer(line.text):
                candidate = self._make_candidate(
                    match.group(0),
                    line=line,
                    previous_reading=previous_reading,
                    max_delta=max_delta,
                )
                if candidate is not None:
                    candidates.append(candidate)

        selected = max(candidates, key=lambda candidate: candidate.score, default=None)
        if selected is not None and selected.score <= 0:
            selected = None
        serial_number = self._extract_serial(lines)
        return OCRResult(
            reading=None if selected is None else selected.value,
            serial_number=serial_number,
            confidence=0.0 if selected is None else selected.confidence,
            raw_text=[line.text for line in lines],
        )

    def _make_candidate(
        self,
        raw_value: str,
        *,
        line: OCRTextLine,
        previous_reading: Decimal | None,
        max_delta: Decimal | None,
    ) -> _Candidate | None:
        normalized = raw_value.replace(" ", "").replace("'", "").replace("\u00a0", "")
        normalized = normalized.replace(",", ".")
        try:
            value = Decimal(normalized)
        except InvalidOperation:
            return None

        digits = sum(character.isdigit() for character in raw_value)
        has_fraction = "." in raw_value or "," in raw_value
        plausible_shape = digits >= 4 or has_fraction
        if previous_reading is not None and value >= previous_reading:
            plausible_shape = True
        if not plausible_shape:
            return None

        confidence = min(max(float(line.confidence), 0.0), 1.0)
        score = confidence * 5
        if has_fraction:
            score += 4
        if 4 <= digits <= 9:
            score += 2
        if normalized.startswith("0") and digits >= 5:
            score += 1
        if _METER_UNIT.search(line.text):
            score += 1.5
        if _SERIAL_MARKER.search(line.text):
            score -= 20
        if _ELECTRICAL_NOISE.search(line.text):
            score -= 12
        if _TECHNICAL_COEFFICIENT.search(line.text):
            score -= 20

        if previous_reading is not None:
            delta = value - previous_reading
            if delta < 0:
                score -= 20
            else:
                score += 6
                if max_delta is None or delta <= max_delta:
                    score += 4
                else:
                    score -= 3

        return _Candidate(value=value, confidence=confidence, score=score, text=line.text)

    @staticmethod
    def _extract_serial(lines: Sequence[OCRTextLine]) -> str | None:
        matches: list[tuple[float, str]] = []
        for line in lines:
            prefixed = _PREFIXED_SERIAL_PATTERN.search(line.text)
            if prefixed is not None:
                prefix = prefixed.group("prefix").upper()
                number = re.sub(r"[ -]", "", prefixed.group("number"))
                normalized = f"N{number}" if prefix.startswith("N") else f"OB {number}"
                matches.append((line.confidence, normalized))
            match = _SERIAL_PATTERN.search(line.text)
            if match is not None:
                matches.append((line.confidence, match.group(1).upper()))
        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]
