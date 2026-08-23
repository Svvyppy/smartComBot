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


def test_parser_prefers_counter_line_over_technical_coefficients() -> None:
    result = MeterReadingParser().parse(
        [
            OCRTextLine("60420.370", 0.70),
            OCRTextLine("K=1,4815×10 m/мин.", 0.95),
            OCRTextLine("×0,000", 0.99),
        ]
    )

    assert result.reading == Decimal("60420.370")


def test_parser_extracts_serial_prefixes_seen_on_real_water_meters() -> None:
    first = MeterReadingParser().parse([OCRTextLine("N164701553", 0.96)])
    second = MeterReadingParser().parse([OCRTextLine("OB 8980478 13", 0.97)])

    assert first.serial_number == "N164701553"
    assert second.serial_number == "OB 898047813"


def test_parser_understands_ocr_variants_of_number_sign() -> None:
    for label in ("No.", "Ne.", "Ng."):
        result = MeterReadingParser().parse(
            [
                OCRTextLine(f"{label}22297698 2022r.", 0.92),
                OCRTextLine("3465.81", 0.84),
            ]
        )

        assert result.reading == Decimal("3465.81")
        assert result.serial_number == "22297698"
