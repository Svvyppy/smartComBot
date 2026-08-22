import cv2
import numpy as np
import pytest

from src.infrastructure.ocr import ImagePreprocessor, PreprocessingConfig


def _jpeg(width: int = 2200, height: int = 1000) -> bytes:
    image = np.full((height, width, 3), 220, dtype=np.uint8)
    cv2.putText(image, "00123.4", (200, 600), cv2.FONT_HERSHEY_SIMPLEX, 5, (20, 20, 20), 12)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


def test_preprocessor_decodes_resizes_and_grayscales() -> None:
    result = ImagePreprocessor(PreprocessingConfig(max_dimension=1000)).process(_jpeg())

    assert result.ndim == 2
    assert max(result.shape) == 1000


def test_preprocessor_can_apply_threshold() -> None:
    result = ImagePreprocessor(PreprocessingConfig(max_dimension=1000, threshold=True)).process(
        _jpeg()
    )

    assert set(np.unique(result)).issubset({0, 255})


def test_preprocessor_rejects_corrupted_image() -> None:
    with pytest.raises(ValueError, match="corrupted"):
        ImagePreprocessor().process(b"not an image")
