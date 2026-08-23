from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import UUID

from aiohttp import web
from pydantic import BaseModel, Field, ValidationError

from src.application.dashboard import DashboardService, DashboardSnapshot
from src.application.exceptions import AccessDeniedError
from src.application.management import ManagementService
from src.application.meters import MeterService
from src.application.properties import PropertyService
from src.application.users import UserService
from src.config import Settings
from src.domain.entities import Meter, Property, User
from src.domain.enums import MeterUnit, UtilityType
from src.web.auth import MiniAppAuthError, validate_init_data

logger = logging.getLogger(__name__)
STATIC_ROOT = Path(__file__).with_name("static")
CURRENT_USER_KEY = web.RequestKey("current_user", User)
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' https://telegram.org",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors https://telegram.org https://*.telegram.org",
    )
)


class PropertyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str | None = Field(default=None, max_length=500)


class MeterPayload(BaseModel):
    property_id: UUID
    name: str = Field(min_length=1, max_length=100)
    type: UtilityType
    serial_number: str | None = Field(default=None, max_length=100)


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    return None if value is None else str(value)


def dashboard_payload(snapshot: DashboardSnapshot) -> dict[str, object]:
    return {
        "summary": {
            "property_count": snapshot.property_count,
            "meter_count": snapshot.meter_count,
            "meters_with_readings": snapshot.meters_with_readings,
            "meters_needing_reading": snapshot.meters_needing_reading,
        },
        "properties": [
            {
                "id": str(property_.id),
                "name": property_.name,
                "address": property_.address,
                "meters": [
                    {
                        key: _json_value(value)
                        for key, value in asdict(meter).items()
                    }
                    for meter in property_.meters
                ],
            }
            for property_ in snapshot.properties
        ],
    }


def property_payload(property_: Property) -> dict[str, object]:
    return {
        "id": None if property_.id is None else str(property_.id),
        "name": property_.name,
        "address": property_.address,
    }


def meter_payload(meter: Meter) -> dict[str, object]:
    return {
        "id": None if meter.id is None else str(meter.id),
        "property_id": str(meter.property_id),
        "name": meter.name,
        "type": meter.type.value,
        "unit": meter.unit.value,
        "serial_number": meter.serial_number,
        "active": meter.active,
    }


async def _request_payload(request: web.Request, model: type[BaseModel]) -> BaseModel:
    try:
        raw = await request.json()
        return model.model_validate(raw)
    except (ValueError, TypeError, ValidationError) as exc:
        raise web.HTTPBadRequest(
            text="Некорректные данные запроса.",
            content_type="text/plain",
        ) from exc


def _current_user(request: web.Request) -> User:
    try:
        user = request[CURRENT_USER_KEY]
    except KeyError as exc:
        raise web.HTTPUnauthorized(text="Telegram authentication required") from exc
    if user.id is None:
        raise web.HTTPUnauthorized(text="Telegram authentication required")
    return user


def create_mini_app(
    settings: Settings,
    *,
    users: UserService,
    dashboard: DashboardService,
    properties: PropertyService,
    meters: MeterService,
    management: ManagementService,
) -> web.Application:
    @web.middleware
    async def errors_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except AccessDeniedError as exc:
            raise web.HTTPNotFound(text="Ресурс не найден.") from exc
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except Exception as exc:
            logger.exception(
                "Mini App request failed method=%s path=%s",
                request.method,
                request.path,
            )
            raise web.HTTPInternalServerError(text="Внутренняя ошибка сервера.") from exc

    @web.middleware
    async def auth_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if not request.path.startswith("/api/"):
            return await handler(request)
        try:
            identity = validate_init_data(
                request.headers.get("X-Telegram-Init-Data", ""),
                bot_token=settings.bot_token.get_secret_value(),
                max_age_seconds=settings.mini_app_auth_max_age_seconds,
            )
        except MiniAppAuthError as exc:
            raise web.HTTPUnauthorized(text=str(exc)) from exc
        request[CURRENT_USER_KEY] = await users.resolve(
            telegram_id=identity.telegram_id,
            username=identity.username,
            first_name=identity.first_name,
        )
        return await handler(request)

    @web.middleware
    async def security_headers_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.path.startswith("/api/") else "public, max-age=300"
        )
        return response

    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_ROOT / "index.html")

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def get_dashboard(request: web.Request) -> web.Response:
        user = _current_user(request)
        snapshot = await dashboard.get_snapshot(user_id=user.id)  # type: ignore[arg-type]
        return web.json_response(dashboard_payload(snapshot))

    async def create_property(request: web.Request) -> web.Response:
        user = _current_user(request)
        payload = await _request_payload(request, PropertyPayload)
        assert isinstance(payload, PropertyPayload)
        property_ = await properties.create(
            user_id=user.id,  # type: ignore[arg-type]
            name=payload.name,
            address=payload.address,
        )
        return web.json_response(property_payload(property_), status=201)

    async def create_meter(request: web.Request) -> web.Response:
        user = _current_user(request)
        payload = await _request_payload(request, MeterPayload)
        assert isinstance(payload, MeterPayload)
        if payload.type not in {
            UtilityType.COLD_WATER,
            UtilityType.HOT_WATER,
            UtilityType.ELECTRICITY,
        }:
            raise web.HTTPBadRequest(text="Тип счётчика пока не поддерживается.")
        meter = await meters.create(
            user_id=user.id,  # type: ignore[arg-type]
            property_id=payload.property_id,
            name=payload.name,
            utility_type=payload.type,
            unit={
                UtilityType.COLD_WATER: MeterUnit.CUBIC_METER,
                UtilityType.HOT_WATER: MeterUnit.CUBIC_METER,
                UtilityType.ELECTRICITY: MeterUnit.KILOWATT_HOUR,
            }[payload.type],
            serial_number=payload.serial_number,
        )
        return web.json_response(meter_payload(meter), status=201)

    async def delete_meter(request: web.Request) -> web.Response:
        user = _current_user(request)
        result = await management.delete_meter(
            user_id=user.id,  # type: ignore[arg-type]
            meter_id=UUID(request.match_info["meter_id"]),
        )
        return web.json_response(asdict(result))

    async def delete_property(request: web.Request) -> web.Response:
        user = _current_user(request)
        result = await management.delete_property(
            user_id=user.id,  # type: ignore[arg-type]
            property_id=UUID(request.match_info["property_id"]),
        )
        return web.json_response(asdict(result))

    app = web.Application(
        middlewares=[errors_middleware, auth_middleware, security_headers_middleware]
    )
    app.router.add_get("/", index)
    app.router.add_get("/miniapp", index)
    app.router.add_get("/miniapp/", index)
    app.router.add_static("/miniapp/static/", STATIC_ROOT)
    app.router.add_get("/healthz", health)
    app.router.add_get("/api/v1/dashboard", get_dashboard)
    app.router.add_post("/api/v1/properties", create_property)
    app.router.add_post("/api/v1/meters", create_meter)
    app.router.add_delete("/api/v1/meters/{meter_id}", delete_meter)
    app.router.add_delete("/api/v1/properties/{property_id}", delete_property)
    return app


async def start_mini_app_server(
    settings: Settings,
    *,
    users: UserService,
    dashboard: DashboardService,
    properties: PropertyService,
    meters: MeterService,
    management: ManagementService,
) -> web.AppRunner:
    app = create_mini_app(
        settings,
        users=users,
        dashboard=dashboard,
        properties=properties,
        meters=meters,
        management=management,
    )
    runner = web.AppRunner(app, access_log=logger)
    await runner.setup()
    site = web.TCPSite(runner, settings.mini_app_host, settings.mini_app_port)
    await site.start()
    return runner
