from src.infrastructure.supabase.repositories.billing import SupabaseBillingRepository
from src.infrastructure.supabase.repositories.manual_reading import (
    SupabaseManualReadingPersistence,
)
from src.infrastructure.supabase.repositories.meter import SupabaseMeterRepository
from src.infrastructure.supabase.repositories.ocr_feedback import (
    SupabaseOCRFeedbackRepository,
)
from src.infrastructure.supabase.repositories.property import SupabasePropertyRepository
from src.infrastructure.supabase.repositories.reading import SupabaseReadingRepository
from src.infrastructure.supabase.repositories.recognized_reading import (
    SupabaseRecognizedReadingPersistence,
)
from src.infrastructure.supabase.repositories.tariff import SupabaseTariffRepository
from src.infrastructure.supabase.repositories.user import SupabaseUserRepository

__all__ = [
    "SupabaseBillingRepository",
    "SupabaseManualReadingPersistence",
    "SupabaseMeterRepository",
    "SupabaseOCRFeedbackRepository",
    "SupabasePropertyRepository",
    "SupabaseReadingRepository",
    "SupabaseRecognizedReadingPersistence",
    "SupabaseTariffRepository",
    "SupabaseUserRepository",
]
