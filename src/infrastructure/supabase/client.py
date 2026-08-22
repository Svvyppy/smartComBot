from supabase.client import ClientOptions

from src.config import Settings
from supabase import Client, create_client


def create_supabase_client(settings: Settings) -> Client:
    """Create the application-scoped client without exposing its service role key."""

    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
        options=ClientOptions(
            postgrest_client_timeout=20,
            storage_client_timeout=30,
            schema="public",
        ),
    )

