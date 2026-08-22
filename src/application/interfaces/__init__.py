from src.application.interfaces.manual_reading import ManualReadingPersistence
from src.application.interfaces.ocr import OCRResult, OCRTextLine, SynchronousOCR
from src.application.interfaces.ocr_debug import OCRDebugSampleStore
from src.application.interfaces.recognized_reading import RecognizedReadingPersistence
from src.application.interfaces.repositories import (
    BillingRepository,
    MeterRepository,
    PropertyRepository,
    ReadingRepository,
    TariffRepository,
    UserRepository,
)
from src.application.interfaces.storage import ImageStorage

__all__ = [
    "BillingRepository",
    "ImageStorage",
    "ManualReadingPersistence",
    "MeterRepository",
    "OCRResult",
    "OCRDebugSampleStore",
    "OCRTextLine",
    "PropertyRepository",
    "ReadingRepository",
    "RecognizedReadingPersistence",
    "SynchronousOCR",
    "TariffRepository",
    "UserRepository",
]
