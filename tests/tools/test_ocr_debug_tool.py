import json
from pathlib import Path
from uuid import UUID

import pytest

from src.tools.ocr_debug import find_sample, load_metadata

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
