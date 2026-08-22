class ApplicationError(Exception):
    """Base class for expected application-level failures."""


class AccessDeniedError(ApplicationError):
    """The requested entity does not belong to the current Telegram user."""


class EntityNotFoundError(ApplicationError):
    """A requested entity does not exist."""


class ActiveTariffNotFoundError(ApplicationError):
    """No applicable simple tariff exists for a meter."""


class ReadingRejectedError(ApplicationError):
    """A reading failed hard validation."""


class SuspiciousReadingError(ApplicationError):
    """A reading needs explicit confirmation because its delta is unusually large."""


class OCRReadingNotFoundError(ApplicationError):
    """OCR completed but did not find a plausible meter value."""
