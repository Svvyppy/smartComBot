from src.application.interfaces.manual_reading import ManualReadingPersistence
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
    "PropertyRepository",
    "ReadingRepository",
    "TariffRepository",
    "UserRepository",
]
