from decimal import Decimal

from src.application.interfaces import OCRTextLine
from src.infrastructure.ocr import MeterReadingParser


def test_parser_selects_display_and_extracts_serial_number() -> None:
    result = MeterReadingParser().parse(
        [
            OCRTextLine("МЕРКУРИЙ 201", 0.99),
            OCRTextLine("230V 5-60A", 0.96),
            OCRTextLine("0018427.3 kWh", 0.93),
            OCRTextLine("№ 94838271", 0.91),
        ]
    )

    assert result.reading == Decimal("18427.3")
    assert result.serial_number == "94838271"
    assert result.confidence == 0.93


def test_parser_uses_previous_reading_to_choose_plausible_candidate() -> None:
    result = MeterReadingParser().parse(
        [
            OCRTextLine("888888", 0.99),
            OCRTextLine("01245,7", 0.82),
        ],
        previous_reading=Decimal("1230.2"),
        max_delta=Decimal("100"),
    )

    assert result.reading == Decimal("1245.7")


def test_parser_returns_none_when_no_meter_shaped_number_exists() -> None:
    result = MeterReadingParser().parse(
        [OCRTextLine("Модель 201", 0.99), OCRTextLine("230V", 0.98)]
    )

    assert result.reading is None
    assert result.confidence == 0.0
    assert result.raw_text == ["Модель 201", "230V"]
