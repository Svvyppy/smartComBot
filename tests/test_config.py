from src.config import Settings


def test_mini_app_server_can_start_before_public_url_is_known() -> None:
    settings = Settings(mini_app_enabled=True, mini_app_url="")

    assert settings.mini_app_server_enabled is True


def test_public_url_keeps_backwards_compatible_server_startup() -> None:
    settings = Settings(
        mini_app_enabled=False,
        mini_app_url="https://meters.example.com/miniapp/",
    )

    assert settings.mini_app_server_enabled is True


def test_mini_app_server_remains_opt_in_without_url() -> None:
    settings = Settings(mini_app_enabled=False, mini_app_url="")

    assert settings.mini_app_server_enabled is False
