from dataclasses import dataclass

from src.application.dashboard import DashboardService
from src.application.management import ManagementService
from src.application.meters import MeterService
from src.application.ocr import OCRDebugService, OCRExecutor
from src.application.properties import PropertyService
from src.application.readings import PhotoReadingService, ReadingService
from src.application.tariffs import TariffService
from src.application.users import UserService
from src.config import Settings
from src.domain.services import BillingService, ReadingValidationService
from src.infrastructure.local import LocalOCRDebugSampleStore
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
    SupabaseOCRFeedbackRepository,
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
    dashboard: DashboardService
    properties: PropertyService
    meters: MeterService
    management: ManagementService
    tariffs: TariffService
    readings: ReadingService
    photo_readings: PhotoReadingService
    ocr_debug: OCRDebugService


def build_application(settings: Settings) -> ApplicationServices:
    client = create_supabase_client(settings)
    users = UserService(SupabaseUserRepository(client))
    property_repository = SupabasePropertyRepository(client)
    properties = PropertyService(property_repository)
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
    ocr_executor = OCRExecutor(ocr, max_concurrency=settings.ocr_max_concurrency)
    image_storage = SupabaseImageStorage(client, settings.supabase_storage_bucket)
    photo_readings = PhotoReadingService(
        meters=meter_repository,
        readings=reading_repository,
        ocr_feedback=SupabaseOCRFeedbackRepository(client),
        recognized_readings=SupabaseRecognizedReadingPersistence(client),
        tariffs=tariffs,
        billing=billing,
        validation=validation,
        ocr=ocr_executor,
        storage=image_storage,
    )
    ocr_debug = OCRDebugService(
        ocr=ocr_executor,
        samples=LocalOCRDebugSampleStore(settings.ocr_debug_dir),
    )
    return ApplicationServices(
        users=users,
        dashboard=DashboardService(
            properties=property_repository,
            meters=meter_repository,
            readings=reading_repository,
        ),
        properties=properties,
        meters=meters,
        management=ManagementService(
            properties=property_repository,
            meters=meter_repository,
            readings=reading_repository,
            storage=image_storage,
        ),
        tariffs=tariffs,
        readings=readings,
        photo_readings=photo_readings,
        ocr_debug=ocr_debug,
    )
