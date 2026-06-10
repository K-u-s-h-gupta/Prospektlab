from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin
from typing import Any, Mapping

import httpx

logger = logging.getLogger("finagent.telemetry")


@dataclass(frozen=True)
class TelemetryUserContext:
    email: str
    name: str
    user_id: str | None = None
    tenant_id: str | None = None
    auth_provider: str | None = None


@dataclass(frozen=True)
class TelemetrySettings:
    enabled: bool
    connection_string: str
    ingestion_url: str
    instrumentation_key: str
    role_name: str
    role_instance: str


def _env_bool(*names: str, default: bool = False) -> bool:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _env_string(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return default


def _parse_connection_string(connection_string: str) -> tuple[str, str] | None:
    parts = {}
    for chunk in connection_string.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts[key.strip().lower()] = value.strip()

    instrumentation_key = parts.get("instrumentationkey")
    if not instrumentation_key:
        return None

    ingestion_endpoint = parts.get("ingestionendpoint", "https://dc.services.visualstudio.com")
    if not ingestion_endpoint.endswith("/"):
        ingestion_endpoint += "/"

    return (
        instrumentation_key,
        urljoin(ingestion_endpoint, "v2/track"),
    )


def _format_duration(duration_ms: float | int | None) -> str:
    total_ms = max(0, int(round(duration_ms or 0)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _sanitize_properties(properties: Mapping[str, Any] | None) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    if not properties:
        return sanitized

    for key, value in properties.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = str(value)
        else:
            sanitized[key] = repr(value)
    return sanitized


def _sanitize_measurements(measurements: Mapping[str, Any] | None) -> dict[str, float]:
    sanitized: dict[str, float] = {}
    if not measurements:
        return sanitized

    for key, value in measurements.items():
        if isinstance(value, (int, float)) and value == value:
            sanitized[key] = float(value)
    return sanitized


def _user_properties(user: TelemetryUserContext | None) -> dict[str, str]:
    if not user:
        return {}
    properties = {
        "user_email": user.email,
        "user_name": user.name,
    }
    if user.user_id:
        properties["user_id"] = user.user_id
    if user.tenant_id:
        properties["tenant_id"] = user.tenant_id
    if user.auth_provider:
        properties["auth_provider"] = user.auth_provider
    return properties


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TelemetryClient:
    def __init__(self) -> None:
        connection_string = _env_string(
            "APPINSIGHTS_CONNECTION_STRING",
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
        )
        parsed = _parse_connection_string(connection_string) if connection_string else None
        enabled = _env_bool("APPINSIGHTS_ENABLED", "APPLICATIONINSIGHTS_ENABLED", "APPLICATIONINSIGHTS_ENABLE")
        role_name = _env_string("APPINSIGHTS_ROLE_NAME", "APPLICATIONINSIGHTS_ROLE_NAME", default="prospektlab-backend")
        role_instance = _env_string("APPINSIGHTS_ROLE_INSTANCE", "APPLICATIONINSIGHTS_ROLE_INSTANCE", default=socket.gethostname() or "backend")

        if not enabled or not parsed:
            self.settings = TelemetrySettings(
                enabled=False,
                connection_string=connection_string,
                ingestion_url="",
                instrumentation_key="",
                role_name=role_name,
                role_instance=role_instance,
            )
            self._client: httpx.AsyncClient | None = None
            return

        instrumentation_key, ingestion_url = parsed
        self.settings = TelemetrySettings(
            enabled=True,
            connection_string=connection_string,
            ingestion_url=ingestion_url,
            instrumentation_key=instrumentation_key,
            role_name=role_name,
            role_instance=role_instance,
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def _build_tags(self, user: TelemetryUserContext | None = None, extra_tags: Mapping[str, str] | None = None) -> dict[str, str]:
        tags = {
            "ai.application.ver": self.settings.role_name,
            "ai.cloud.role": self.settings.role_name,
            "ai.cloud.roleInstance": self.settings.role_instance,
            "ai.operation.id": str(uuid.uuid4()),
        }
        if user:
            tags["ai.user.id"] = user.email
            tags["ai.user.authUserId"] = user.email
            tags["ai.user.accountId"] = user.email
        if extra_tags:
            tags.update(extra_tags)
        return tags

    def _build_envelope(
        self,
        base_type: str,
        base_data: dict[str, Any],
        *,
        user: TelemetryUserContext | None = None,
        extra_tags: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "name": f"Microsoft.ApplicationInsights.{base_type}",
            "time": _now_iso(),
            "iKey": self.settings.instrumentation_key,
            "tags": self._build_tags(user=user, extra_tags=extra_tags),
            "data": {
                "baseType": base_type,
                "baseData": base_data,
            },
        }

    def _schedule(self, payload: dict[str, Any]) -> None:
        if not self.enabled or self._client is None:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _send() -> None:
            try:
                await self._client.post(
                    self.settings.ingestion_url,
                    content=json.dumps([payload]).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
            except Exception as exc:  # pragma: no cover - best effort telemetry
                logger.debug("App Insights send failed: %s", exc)

        loop.create_task(_send())

    def emit_event(
        self,
        name: str,
        *,
        user: TelemetryUserContext | None = None,
        properties: Mapping[str, Any] | None = None,
        measurements: Mapping[str, Any] | None = None,
        extra_tags: Mapping[str, str] | None = None,
    ) -> None:
        if not self.enabled:
            return

        self._schedule(
            self._build_envelope(
                "EventData",
                {
                    "ver": 2,
                    "name": name,
                    "properties": _sanitize_properties({
                        **_user_properties(user),
                        **(properties or {}),
                    }),
                    "measurements": _sanitize_measurements(measurements),
                },
                user=user,
                extra_tags=extra_tags,
            )
        )

    def emit_request(
        self,
        *,
        name: str,
        url: str,
        method: str,
        duration_ms: float | int,
        success: bool,
        status_code: int | None = None,
        user: TelemetryUserContext | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        properties: Mapping[str, Any] | None = None,
        measurements: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return

        tags: dict[str, str] = {}
        if request_id:
            tags["ai.operation.id"] = request_id
        if session_id:
            tags["ai.session.id"] = session_id

        self._schedule(
            self._build_envelope(
                "RequestData",
                {
                    "ver": 2,
                    "id": request_id or str(uuid.uuid4()),
                    "name": name,
                    "url": url,
                    "duration": _format_duration(duration_ms),
                    "success": success,
                    "responseCode": str(status_code) if status_code is not None else None,
                    "properties": _sanitize_properties({
                        **_user_properties(user),
                        **(properties or {}),
                    }),
                    "measurements": _sanitize_measurements({
                        **(measurements or {}),
                        "duration_ms": float(duration_ms),
                    }),
                },
                user=user,
                extra_tags=tags,
            )
        )

    def emit_dependency(
        self,
        *,
        name: str,
        target: str,
        data: str,
        duration_ms: float | int,
        success: bool,
        status_code: int | None = None,
        user: TelemetryUserContext | None = None,
        request_id: str | None = None,
        properties: Mapping[str, Any] | None = None,
        measurements: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return

        self._schedule(
            self._build_envelope(
                "RemoteDependencyData",
                {
                    "ver": 2,
                    "id": request_id or str(uuid.uuid4()),
                    "name": name,
                    "data": data,
                    "target": target,
                    "duration": _format_duration(duration_ms),
                    "success": success,
                    "resultCode": str(status_code) if status_code is not None else None,
                    "type": "Dependency",
                    "properties": _sanitize_properties({
                        **_user_properties(user),
                        **(properties or {}),
                    }),
                    "measurements": _sanitize_measurements({
                        **(measurements or {}),
                        "duration_ms": float(duration_ms),
                    }),
                },
                user=user,
            )
        )

    def emit_trace(
        self,
        message: str,
        *,
        severity_level: int = 1,
        user: TelemetryUserContext | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        properties: Mapping[str, Any] | None = None,
        measurements: Mapping[str, Any] | None = None,
        extra_tags: Mapping[str, str] | None = None,
    ) -> None:
        if not self.enabled:
            return

        tags: dict[str, str] = {}
        if request_id:
            tags["ai.operation.id"] = request_id
        if session_id:
            tags["ai.session.id"] = session_id
        if extra_tags:
            tags.update(extra_tags)

        self._schedule(
            self._build_envelope(
                "MessageData",
                {
                    "ver": 2,
                    "message": message,
                    "severityLevel": severity_level,
                    "properties": _sanitize_properties({
                        **_user_properties(user),
                        **(properties or {}),
                    }),
                    "measurements": _sanitize_measurements(measurements),
                },
                user=user,
                extra_tags=tags,
            )
        )

    def emit_metric(
        self,
        name: str,
        value: float | int,
        *,
        count: int = 1,
        minimum: float | int | None = None,
        maximum: float | int | None = None,
        std_dev: float | int | None = None,
        user: TelemetryUserContext | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        properties: Mapping[str, Any] | None = None,
        extra_tags: Mapping[str, str] | None = None,
    ) -> None:
        if not self.enabled:
            return

        tags: dict[str, str] = {}
        if request_id:
            tags["ai.operation.id"] = request_id
        if session_id:
            tags["ai.session.id"] = session_id
        if extra_tags:
            tags.update(extra_tags)

        metric: dict[str, Any] = {
            "name": name,
            "value": float(value),
            "count": max(1, int(count)),
        }
        if minimum is not None:
            metric["min"] = float(minimum)
        if maximum is not None:
            metric["max"] = float(maximum)
        if std_dev is not None:
            metric["stdDev"] = float(std_dev)

        self._schedule(
            self._build_envelope(
                "MetricData",
                {
                    "ver": 2,
                    "metrics": [metric],
                    "properties": _sanitize_properties({
                        **_user_properties(user),
                        **(properties or {}),
                    }),
                },
                user=user,
                extra_tags=tags,
            )
        )

    def emit_exception(
        self,
        error: BaseException,
        *,
        user: TelemetryUserContext | None = None,
        request_id: str | None = None,
        properties: Mapping[str, Any] | None = None,
        measurements: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return

        self._schedule(
            self._build_envelope(
                "ExceptionData",
                {
                    "ver": 2,
                    "exceptions": [
                        {
                            "typeName": error.__class__.__name__,
                            "message": str(error),
                            "hasFullStack": True,
                            "stack": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
                        }
                    ],
                    "severityLevel": 3,
                    "properties": _sanitize_properties({
                        **_user_properties(user),
                        **(properties or {}),
                    }),
                    "measurements": _sanitize_measurements(measurements),
                },
                user=user,
                extra_tags={"ai.operation.id": request_id} if request_id else None,
            )
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


TELEMETRY = TelemetryClient()


def telemetry_enabled() -> bool:
    return TELEMETRY.enabled


def telemetry_user_from_request_user(current_user: Mapping[str, Any] | None) -> TelemetryUserContext | None:
    if not current_user:
        return None
    email = (current_user.get("email") or "").strip()
    if not email:
        return None
    return TelemetryUserContext(
        email=email,
        name=(current_user.get("name") or email).strip() or email,
        user_id=(current_user.get("user_id") or current_user.get("sub") or "").strip() or None,
        tenant_id=(current_user.get("tenant_id") or "").strip() or None,
        auth_provider=(current_user.get("auth_provider") or "").strip() or None,
    )


def telemetry_user_from_authorization_header(authorization: str | None) -> TelemetryUserContext | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        from finagent.gateway.auth_guard import decode_current_user_token
        local_secret = _env_string("JWT_SECRET")
        if not local_secret:
            return None
        payload = decode_current_user_token(token, local_jwt_secret=local_secret)
    except Exception:
        return None

    email = (payload.get("email") or "").strip()
    if not email:
        return None

    return TelemetryUserContext(
        email=email,
        name=(payload.get("name") or email).strip() or email,
        user_id=(payload.get("user_id") or payload.get("sub") or "").strip() or None,
        tenant_id=(payload.get("tenant_id") or "").strip() or None,
        auth_provider=(payload.get("auth_provider") or "").strip() or None,
    )


def telemetry_request_context(request) -> tuple[str, str | None]:
    request_id = request.headers.get("X-Prospektlab-Request-Id") or request.headers.get("X-ProspektLab-Request-Id") or str(uuid.uuid4())
    session_id = request.headers.get("X-Prospektlab-Session-Id") or request.headers.get("X-ProspektLab-Session-Id")
    return request_id, session_id


def schedule_telemetry(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)
