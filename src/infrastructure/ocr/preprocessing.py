from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

ImageArray = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class PreprocessingConfig:
    max_dimension: int = 1600
    grayscale: bool = True
    enhance_contrast: bool = True
    threshold: bool = False
    perspective_correction: bool = False

    def __post_init__(self) -> None:
        if self.max_dimension < 320:
            raise ValueError("max_dimension must be at least 320 pixels")


class ImagePreprocessor:
    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self._config = config or PreprocessingConfig()

    def process(self, image_content: bytes) -> ImageArray:
        if not image_content:
            raise ValueError("Image is empty")
        encoded = np.frombuffer(image_content, dtype=np.uint8)
        decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if decoded is None:
            raise ValueError("Unsupported or corrupted image")
        image = np.asarray(decoded, dtype=np.uint8)

        if self._config.perspective_correction:
            image = self._correct_perspective(image)
        image = self._resize(image)
        if self._config.grayscale:
            image = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
        if self._config.enhance_contrast:
            image = self._enhance_contrast(image)
        if self._config.threshold:
            image = self._apply_threshold(image)
        return image

    def _resize(self, image: ImageArray) -> ImageArray:
        height, width = image.shape[:2]
        largest_dimension = max(height, width)
        if largest_dimension <= self._config.max_dimension:
            return image
        scale = self._config.max_dimension / largest_dimension
        return np.asarray(
            cv2.resize(
                image,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            ),
            dtype=np.uint8,
        )

    @staticmethod
    def _enhance_contrast(image: ImageArray) -> ImageArray:
        if image.ndim == 2:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return np.asarray(clahe.apply(image), dtype=np.uint8)
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        lightness, green_red, blue_yellow = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = cv2.merge((clahe.apply(lightness), green_red, blue_yellow))
        return np.asarray(cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR), dtype=np.uint8)

    @staticmethod
    def _apply_threshold(image: ImageArray) -> ImageArray:
        grayscale = image
        if image.ndim == 3:
            grayscale = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
        blurred = cv2.GaussianBlur(grayscale, (3, 3), 0)
        return np.asarray(
            cv2.adaptiveThreshold(
                blurred,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                7,
            ),
            dtype=np.uint8,
        )

    @staticmethod
    def _correct_perspective(image: ImageArray) -> ImageArray:
        grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(grayscale, (5, 5), 0), 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        image_area = image.shape[0] * image.shape[1]
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(polygon) != 4 or cv2.contourArea(polygon) < image_area * 0.15:
                continue
            points = polygon.reshape(4, 2).astype(np.float32)
            return ImagePreprocessor._warp_four_points(image, points)
        return image

    @staticmethod
    def _warp_four_points(image: ImageArray, points: NDArray[np.float32]) -> ImageArray:
        ordered = np.zeros((4, 2), dtype=np.float32)
        sums = points.sum(axis=1)
        differences = np.diff(points, axis=1).reshape(-1)
        ordered[0] = points[np.argmin(sums)]
        ordered[2] = points[np.argmax(sums)]
        ordered[1] = points[np.argmin(differences)]
        ordered[3] = points[np.argmax(differences)]

        top_left, top_right, bottom_right, bottom_left = ordered
        width = max(
            int(np.linalg.norm(bottom_right - bottom_left)),
            int(np.linalg.norm(top_right - top_left)),
        )
        height = max(
            int(np.linalg.norm(top_right - bottom_right)),
            int(np.linalg.norm(top_left - bottom_left)),
        )
        if width < 2 or height < 2:
            return image
        destination = np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            dtype=np.float32,
        )
        transform = cv2.getPerspectiveTransform(ordered, destination)
        return np.asarray(cv2.warpPerspective(image, transform, (width, height)), dtype=np.uint8)
