import json
from pathlib import Path
from uuid import UUID

import pytest

from src.config import Settings
from src.tools.ocr_debug import find_sample, load_metadata, preprocessing_variants

SAMPLE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_find_and_load_explicit_debug_sample(tmp_path: Path) -> None:
    sample_dir = tmp_path / str(SAMPLE_ID)
    sample_dir.mkdir()
    metadata = {"sample_id": str(SAMPLE_ID), "goal": "Показание 123.4"}
    (sample_dir / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    found = find_sample(tmp_path, SAMPLE_ID)

    assert found == sample_dir
    assert load_metadata(found) == metadata


def test_missing_debug_sample_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="was not found"):
        find_sample(tmp_path, SAMPLE_ID)


def test_preprocessing_variants_are_unique_and_cover_thresholding() -> None:
    variants = preprocessing_variants(Settings())

    assert len(variants) == len({variant.config for variant in variants})
    assert any(variant.config.threshold for variant in variants)
    assert any(not variant.config.grayscale for variant in variants)
