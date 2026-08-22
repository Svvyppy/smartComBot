from dataclasses import dataclass

from src.application.meters import MeterService
from src.application.properties import PropertyService
from src.application.readings import ReadingService
from src.application.tariffs import TariffService
from src.application.users import UserService
from src.config import Settings
from src.domain.services import BillingService, ReadingValidationService
from src.infrastructure.supabase import create_supabase_client
from src.infrastructure.supabase.repositories import (
    SupabaseManualReadingPersistence,
    SupabaseMeterRepository,
    SupabasePropertyRepository,
    SupabaseReadingRepository,
    SupabaseTariffRepository,
    SupabaseUserRepository,
)


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    users: UserService
    properties: PropertyService
    meters: MeterService
    tariffs: TariffService
    readings: ReadingService


def build_application(settings: Settings) -> ApplicationServices:
    client = create_supabase_client(settings)
    users = UserService(SupabaseUserRepository(client))
    properties = PropertyService(SupabasePropertyRepository(client))
    meter_repository = SupabaseMeterRepository(client)
    meters = MeterService(meter_repository)
    tariff_repository = SupabaseTariffRepository(client)
    tariffs = TariffService(tariff_repository)
    readings = ReadingService(
        meters=meter_repository,
        readings=SupabaseReadingRepository(client),
        manual_readings=SupabaseManualReadingPersistence(client),
        tariffs=tariffs,
        billing=BillingService(),
        validation=ReadingValidationService(settings.reading_delta_limits),
    )
    return ApplicationServices(
        users=users,
        properties=properties,
        meters=meters,
        tariffs=tariffs,
        readings=readings,
    )

