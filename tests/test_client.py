import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.clients.instagram_client import InstagramAPIError, InstagramClient


async def test_pagination_uses_all_pages_and_bearer_only(settings):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer fake-token-never-real"
        assert "access_token" not in request.url.params
        assert request.url.host == "graph.instagram.com"
        if request.url.params.get("after") == "cursor-2":
            return httpx.Response(200, json={"data": [{"id": "2"}]})
        return httpx.Response(
            200,
            json={
                "data": [{"id": "1"}],
                "paging": {
                    "next": "https://evil.invalid/?after=cursor-2&access_token=do-not-forward",
                },
            },
        )

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        pages = [page async for page in client.media_pages("id")]
        assert pages == [[{"id": "1"}], [{"id": "2"}]]
        assert len(requests) == 2
    finally:
        await client.close()


async def test_repeating_cursor_fails_instead_of_truncating(settings):
    client = InstagramClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"data": [], "paging": {"next": "https://graph.instagram.com/?after=x"}},
            )
        ),
    )
    try:
        with pytest.raises(InstagramAPIError):
            _ = [page async for page in client.media_pages("id")]
    finally:
        await client.close()


@pytest.mark.parametrize("failure", ["timeout", "429", "503", "graph-rate", "transient"])
async def test_transient_retries(settings, monkeypatch, failure):
    calls = 0
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("Secret should not escape", request=request)
            if failure == "graph-rate":
                return httpx.Response(400, json={"error": {"code": 4}})
            if failure == "transient":
                return httpx.Response(400, json={"error": {"code": 2, "is_transient": True}})
            return httpx.Response(int(failure), headers={"Retry-After": "5"})
        return httpx.Response(200, json={"id": "123"})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        assert (await client.get("me"))["id"] == "123"
        assert calls == 2
        sleep.assert_awaited_once_with(5.0 if failure in {"429", "503"} else 2.0)
    finally:
        await client.close()


async def test_retry_limit_and_exponential_backoff(settings, monkeypatch):
    calls = 0
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": {"message": "fake-token-never-real"}})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(InstagramAPIError) as error:
            await client.get("me")
        assert "fake-token" not in str(error.value)
        assert calls == 4
        assert [call.args[0] for call in sleep.await_args_list] == [2, 4, 8]
    finally:
        await client.close()


@pytest.mark.parametrize("status,code", [(400, 100), (403, 200), (400, 190), (401, None)])
async def test_permanent_and_oauth_errors_do_not_retry(settings, monkeypatch, status, code):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    client = InstagramClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status,
                json={"error": {"code": code, "message": "fake-token-never-real"}},
            )
        ),
    )
    try:
        with pytest.raises(InstagramAPIError) as error:
            await client.get("me")
        assert "fake-token" not in str(error.value)
        assert error.value.oauth == (code == 190 or status == 401)
        sleep.assert_not_awaited()
    finally:
        await client.close()


async def test_client_refuses_arbitrary_urls(settings):
    client = InstagramClient(settings)
    try:
        with pytest.raises(InstagramAPIError):
            await client.get("https://evil.invalid")
    finally:
        await client.close()


async def test_malformed_error_response_is_safe(settings):
    client = InstagramClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400,
                json={"error": "fake-token-never-real"},
            )
        ),
    )
    try:
        with pytest.raises(InstagramAPIError) as error:
            await client.get("me")
        assert "fake-token" not in str(error.value)
    finally:
        await client.close()


async def test_malformed_optional_metric_becomes_null(settings):
    client = InstagramClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"data": {"unexpected": "format"}},
            )
        ),
    )
    warnings = []
    try:
        assert await client.optional_metric("180", "views", {}, warnings.append) is None
        assert len(warnings) == 1
    finally:
        await client.close()
