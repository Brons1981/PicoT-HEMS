"""Runtime-only Home Assistant HTTP transport defined by ADR-035."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from picot.domain.home_assistant import (
    HomeAssistantDispatchMode,
    HomeAssistantServiceCall,
)

HTTP_TIMEOUT_SECONDS = 10.0


class HomeAssistantHttpTransport:
    """Send an already validated service call to the Home Assistant REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        transport_mode: HomeAssistantDispatchMode = HomeAssistantDispatchMode.DRY_RUN,
        timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Home Assistant base URL must be an absolute HTTP(S) URL.")
        if not access_token.strip():
            raise ValueError("Home Assistant access token must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("Home Assistant timeout must be greater than zero.")

        self._base_url = normalized_url
        self._access_token = access_token
        self._transport_mode = transport_mode
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def send(self, call: HomeAssistantServiceCall) -> int:
        """POST one immutable LIVE service call and return the HTTP status code."""
        if self._transport_mode is not HomeAssistantDispatchMode.LIVE:
            raise RuntimeError("Home Assistant HTTP transport is not enabled for LIVE dispatch.")
        if call.dispatch_mode is not HomeAssistantDispatchMode.LIVE:
            raise RuntimeError("Home Assistant HTTP transport accepts only LIVE service calls.")

        endpoint = f"{self._base_url}/api/services/{call.domain}/{call.service}"
        payload: dict[str, str | float] = dict(call.target)
        for key, value in call.service_data:
            payload[key] = value
        request = Request(
            endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = self._opener(request, timeout=self._timeout_seconds)
        status = getattr(response, "status", None)
        if not isinstance(status, int):
            raise RuntimeError("Home Assistant response did not contain an HTTP status.")
        return status
