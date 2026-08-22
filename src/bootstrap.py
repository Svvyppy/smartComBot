from dataclasses import dataclass

from src.application.meters import MeterService
from src.application.ocr import OCRExecutor
from src.application.properties import PropertyService
from src.application.readings import PhotoReadingService, ReadingService
from src.application.tariffs import TariffService
from src.application.users import UserService
from src.config import Settings
from src.domain.services import BillingService, ReadingValidationService
from src.infrastructure.ocr import (
    ImagePreprocessor,
    MeterReadingParser,
    PaddleOCRService,
    PreprocessingConfig,
)
from src.infrastructure.supabase import create_supabase_client
from src.infrastructure.supabase.repositories import (
    SupabaseManualReadingPersistence,
    SupabaseMeterRepository,
    SupabasePropertyRepository,
    SupabaseReadingRepository,
    SupabaseRecognizedReadingPersistence,
    SupabaseTariffRepository,
    SupabaseUserRepository,
)
from src.infrastructure.supabase.storage import SupabaseImageStorage


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    users: UserService
    properties: PropertyService
    meters: MeterService
    tariffs: TariffService
    readings: ReadingService
    photo_readings: PhotoReadingService


def build_application(settings: Settings) -> ApplicationServices:
    client = create_supabase_client(settings)
    users = UserService(SupabaseUserRepository(client))
    properties = PropertyService(SupabasePropertyRepository(client))
    meter_repository = SupabaseMeterRepository(client)
    meters = MeterService(meter_repository)
    tariff_repository = SupabaseTariffRepository(client)
    tariffs = TariffService(tariff_repository)
    reading_repository = SupabaseReadingRepository(client)
    validation = ReadingValidationService(settings.reading_delta_limits)
    billing = BillingService()
    readings = ReadingService(
        meters=meter_repository,
        readings=reading_repository,
        manual_readings=SupabaseManualReadingPersistence(client),
        tariffs=tariffs,
        billing=billing,
        validation=validation,
    )
    ocr = PaddleOCRService(
        preprocessor=ImagePreprocessor(
            PreprocessingConfig(
                max_dimension=settings.ocr_image_max_dimension,
                grayscale=settings.ocr_grayscale,
                enhance_contrast=settings.ocr_enhance_contrast,
                threshold=settings.ocr_threshold,
                perspective_correction=settings.ocr_perspective_correction,
            )
        ),
        parser=MeterReadingParser(),
        language=settings.ocr_language,
        cpu_threads=settings.ocr_cpu_threads,
    )
    photo_readings = PhotoReadingService(
        meters=meter_repository,
        readings=reading_repository,
        recognized_readings=SupabaseRecognizedReadingPersistence(client),
        tariffs=tariffs,
        billing=billing,
        validation=validation,
        ocr=OCRExecutor(ocr, max_concurrency=settings.ocr_max_concurrency),
        storage=SupabaseImageStorage(client, settings.supabase_storage_bucket),
    )
    return ApplicationServices(
        users=users,
        properties=properties,
        meters=meters,
        tariffs=tariffs,
        readings=readings,
        photo_readings=photo_readings,
    )
