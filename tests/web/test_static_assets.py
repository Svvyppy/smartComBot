from pathlib import Path

STATIC_ROOT = Path("src/web/static")


def test_mini_app_page_loads_telegram_sdk_and_dashboard_assets() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

    assert "https://telegram.org/js/telegram-web-app.js" in html
    assert "/miniapp/static/styles.css" in html
    assert "/miniapp/static/app.js" in html
    assert 'id="summary"' in html
    assert 'id="delete-dialog"' in html


def test_mini_app_javascript_uses_authenticated_api_routes() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert '"X-Telegram-Init-Data": initData' in script
    assert 'api("/api/v1/dashboard")' in script
    assert 'api("/api/v1/properties"' in script
    assert 'api("/api/v1/meters"' in script
    assert 'method: "DELETE"' in script
