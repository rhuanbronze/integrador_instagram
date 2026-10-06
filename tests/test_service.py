import asyncio
from datetime import timedelta
from itertools import count

import httpx
import pytest
from sqlalchemy import func, select

from app.clients.instagram_client import InstagramClient
from app.models import (
    ETLRun,
    InstagramAccountDaily,
    InstagramAccountInsights,
    InstagramMedia,
    InstagramMediaInsights,
)
from app.services.instagram_service import InstagramService, JobBusyError


@pytest.fixture(autouse=True)
def controlled_job_clock(now, monkeypatch):
    ticks = count()
    monkeypatch.setattr(
        "app.services.instagram_service.utcnow", lambda: now + timedelta(microseconds=next(ticks))
    )


def successful_handler(now, *, unavailable_metric=None):
    def handler(request):
        assert request.method == "GET"
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={
                    "id": "123",
                    "username": "mocked",
                    "name": "Mock",
                    "profile_picture_url": "https://example.invalid/profile",
                    "followers_count": 170,
                    "follows_count": 20,
                    "media_count": 2,
                },
            )
        if request.url.path.endswith("/me/media"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "180", "timestamp": now.isoformat(), "media_type": "IMAGE"},
                        {
                            "id": "181",
                            "timestamp": (now - timedelta(days=120)).isoformat(),
                            "media_type": "CAROUSEL_ALBUM",
                        },
                    ]
                },
            )
        metric = request.url.params["metric"]
        if metric == unavailable_metric:
            return httpx.Response(400, json={"error": {"code": 100, "message": "Invalid metric"}})
        if metric == "follows_and_unfollows":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"data": [{"name": metric, "total_value": {"value": 10}}]})

    return handler


async def test_all_jobs_then_rerun_preserves_history(settings, sessions, now):
    client = InstagramClient(settings, transport=httpx.MockTransport(successful_handler(now)))
    service = InstagramService(settings, sessions, client)
    try:
        ids = await service.submit("all")
        with pytest.raises(JobBusyError):
            await service.submit("account")
        await service.task
        await service.submit("all")
        await service.task
        with sessions() as session:
            assert len(ids) == 2
            assert session.scalar(select(func.count()).select_from(InstagramMedia)) == 2
            assert session.scalar(select(func.count()).select_from(InstagramMediaInsights)) == 2
            assert session.scalar(select(func.count()).select_from(InstagramAccountDaily)) == 1
            assert session.scalar(select(func.count()).select_from(InstagramAccountInsights)) == 1
            runs = list(session.scalars(select(ETLRun).order_by(ETLRun.id)))
            assert len(runs) == 4
            assert all(run.status in {"SUCCESS", "SUCCESS_WITH_WARNINGS"} for run in runs)
            assert all(run.finished_at is not None for run in runs)
            assert runs[1].records_read == 3
            assert runs[3].records_updated >= 2
            assert runs[2].records_inserted == 0
            assert runs[2].records_updated == 3  # profile, daily snapshot, account insights
    finally:
        await client.close()


async def test_bad_token_fails_run_without_storing_secrets(settings, sessions):
    client = InstagramClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400,
                json={"error": {"code": 190, "message": "expired fake-token-never-real"}},
            )
        ),
    )
    service = InstagramService(settings, sessions, client)
    try:
        ids = await service.submit("account")
        await service.task
        with sessions() as session:
            run = session.get(ETLRun, ids[0])
            assert run.status == "FAILED" and run.errors_count == 1
            assert run.error_message == "Instagram token invalid or expired"
            assert "fake-token" not in run.error_message
    finally:
        await client.close()


async def test_abandoned_run_is_recovered(settings, sessions, now):
    with sessions() as session:
        stale = ETLRun(job_type="account", started_at=now, status="RUNNING")
        session.add(stale)
        session.commit()
        stale_id = stale.id
    client = InstagramClient(settings, transport=httpx.MockTransport(successful_handler(now)))
    service = InstagramService(settings, sessions, client)
    try:
        await service.submit("media")
        await service.task
        with sessions() as session:
            assert session.get(ETLRun, stale_id).status == "FAILED"
    finally:
        await client.close()


async def test_shutdown_marks_accepted_runs_failed_and_releases_lock(settings, sessions):
    waiting = asyncio.Event()

    async def handler(_):
        await waiting.wait()
        return httpx.Response(200, json={"id": "123"})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    service = InstagramService(settings, sessions, client)
    try:
        ids = await service.submit("all")
        await asyncio.sleep(0)
        await service.shutdown()
        with sessions() as session:
            assert all(session.get(ETLRun, run_id).status == "FAILED" for run_id in ids)
        assert service.lock_connection is None
    finally:
        await client.close()


async def test_later_page_failure_preserves_previous_media(settings, sessions, now):
    base = successful_handler(now)

    def handler(request):
        if request.url.path.endswith("/me/media") and request.url.params.get("after"):
            return httpx.Response(400, json={"error": {"code": 200, "message": "Permission error"}})
        response = base(request)
        if request.url.path.endswith("/me/media"):
            payload = response.json()
            payload["paging"] = {"next": "https://graph.instagram.com/?after=next-page"}
            return httpx.Response(200, json=payload)
        return response

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    service = InstagramService(settings, sessions, client)
    try:
        ids = await service.submit("media")
        await service.task
        with sessions() as session:
            assert session.get(ETLRun, ids[0]).status == "FAILED"
            assert session.scalar(select(func.count()).select_from(InstagramMedia)) == 2
            assert session.scalar(select(func.count()).select_from(InstagramMediaInsights)) == 1
    finally:
        await client.close()


async def test_audience_failure_does_not_fail_main_account(settings, sessions, now):
    settings = settings.model_copy(update={"audience_collection_enabled": True})
    base = successful_handler(now)

    def handler(request):
        if request.url.params.get("metric") == "follower_demographics":
            return httpx.Response(403, json={"error": {"code": 200, "message": "Permission error"}})
        return base(request)

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    service = InstagramService(settings, sessions, client)
    try:
        ids = await service.submit("account")
        await service.task
        with sessions() as session:
            assert session.get(ETLRun, ids[0]).status == "SUCCESS_WITH_WARNINGS"
            assert session.scalar(select(func.count()).select_from(InstagramAccountDaily)) == 1
    finally:
        await client.close()
