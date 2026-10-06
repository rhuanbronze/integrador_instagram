"""Only GET requests, bearer authentication, bounded retries and safe pagination."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from app.config import Settings
from app.utils.retry import retry_delay

logger = logging.getLogger(__name__)
RATE_CODES = {4, 17, 32, 613, 80000, 80002}


class InstagramAPIError(Exception):
    """Only fixed diagnostic text escapes this boundary; never raw Meta error bodies."""

    def __init__(
        self,
        status: int = 0,
        code: int | None = None,
        *,
        transient: bool = False,
        unsupported: bool = False,
        oauth: bool = False,
    ):
        self.status = status
        self.code = code
        self.transient = transient
        self.unsupported = unsupported
        self.oauth = oauth
        super().__init__(f"Instagram request failed (HTTP {status}, code {code})")


class InstagramClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.instagram_base_url + "/",
            headers={
                "Authorization": "Bearer " + settings.instagram_access_token.get_secret_value()
            },
            timeout=settings.request_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # Do not permit caller-controlled URLs to receive the bearer token.
        if not path or any(c in path for c in (":", "?", "#", "\\")) or path.startswith("/"):
            raise InstagramAPIError()
        for attempt in range(self.settings.request_max_retries + 1):
            retry_after = None
            try:
                response = await self.http.get(path, params=params)
                retry_after = response.headers.get("Retry-After")
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                if not isinstance(error, dict):
                    error = {"message": "Malformed error payload"}
                if response.is_success and not error:
                    if not isinstance(payload, dict) or not payload:
                        raise InstagramAPIError(response.status_code)
                    return payload
                code = error.get("code") if isinstance(error.get("code"), int) else None
                message = str(error.get("message", "")).lower()
                unsupported = code == 100 and any(
                    word in message for word in ("metric", "field", "breakdown", "not supported")
                )
                failure = InstagramAPIError(
                    response.status_code,
                    code,
                    transient=(
                        response.status_code == 429
                        or response.status_code >= 500
                        or code in RATE_CODES
                        or error.get("is_transient") is True
                    ),
                    unsupported=unsupported,
                    oauth=(code in {102, 190} or response.status_code == 401),
                )
            except (httpx.TimeoutException, httpx.TransportError):
                failure = InstagramAPIError(transient=True)
            if (
                failure.oauth
                or not failure.transient
                or attempt == self.settings.request_max_retries
            ):
                raise failure from None
            logger.warning("Temporary Instagram failure; retry %s", attempt + 1)
            await asyncio.sleep(retry_delay(attempt, retry_after))
        raise InstagramAPIError()  # defensive; loop always returns or raises

    async def media_pages(self, fields: str) -> AsyncIterator[list[dict[str, Any]]]:
        params: dict[str, Any] = {"fields": fields, "limit": 100}
        seen: set[str] = set()
        while True:
            payload = await self.get("me/media", params)
            data = payload.get("data")
            if not isinstance(data, list):
                raise InstagramAPIError()
            yield data
            paging = payload.get("paging") or {}
            if not paging.get("next"):
                break
            # Extract only the opaque cursor, never follow a next URL with embedded tokens.
            cursor = (paging.get("cursors") or {}).get("after")
            if not cursor:
                next_url = httpx.URL(paging["next"])
                cursor = next_url.params.get("after")
            if not cursor or cursor in seen:
                raise InstagramAPIError()  # avoid silent truncation or an infinite loop
            seen.add(cursor)
            params = {**params, "after": cursor}

    async def optional_metric(
        self,
        object_id: str,
        metric: str,
        params: dict[str, Any],
        warning: Callable[[str], None],
        *,
        expected_unsupported: bool = False,
    ) -> dict[str, Any] | None:
        """Suppress only expected incompatibility/empty data, never malformed data or failures."""
        try:
            payload = await self.get(f"{object_id}/insights", {**params, "metric": metric})
        except InstagramAPIError as error:
            if error.oauth or error.transient or not error.unsupported:
                raise
            if expected_unsupported:
                logger.debug("Optional metric %s UNSUPPORTED for object %s", metric, object_id)
            else:
                warning(f"Metric {metric} unavailable for object {object_id}")
            return None
        items = payload.get("data")
        if not isinstance(items, list):
            warning(f"Metric {metric} has malformed data for object {object_id}")
            return None
        item = next(
            (item for item in items if isinstance(item, dict) and item.get("name") == metric), None
        )
        if item is None:
            if expected_unsupported and not items:
                logger.debug("Optional metric %s UNSUPPORTED for object %s", metric, object_id)
            else:
                warning(f"Metric {metric} absent for object {object_id}")
        return item
