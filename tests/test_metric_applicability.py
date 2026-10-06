"""Validated metric compatibility reduces expected warnings without hiding regressions."""

import httpx
import pytest
from sqlalchemy import select

from app.clients.instagram_client import InstagramAPIError, InstagramClient
from app.collectors.account_insights_collector import collect_account_insights
from app.collectors.media_collector import upsert_media
from app.collectors.media_insights_collector import collect_media_insights
from app.collectors.metrics import MEDIA_INSIGHT_METRICS, REEL_INSIGHT_METRICS
from app.models import ETLRun, InstagramAccountInsights, InstagramMediaInsights
from app.services.instagram_service import InstagramService, RunStats


def valid_metric(metric):
    if metric == "follows_and_unfollows":
        return {"name": metric, "values": [{"value": {"follows": 10, "unfollows": 2}}]}
    return {"name": metric, "values": [{"value": 42}]}


@pytest.mark.parametrize(
    "product,kind",
    [
        ("REELS", "VIDEO"),
        ("REELS", "REELS"),
        ("FEED", "IMAGE"),
        ("FEED", "CAROUSEL_ALBUM"),
    ],
)
async def test_media_requests_only_applicable_metrics(
    settings, session, account, now, product, kind
):
    requests = []
    stats = RunStats()

    def handler(request):
        metric = request.url.params["metric"]
        requests.append(metric)
        return httpx.Response(200, json={"data": [valid_metric(metric)]})

    media, _ = upsert_media(
        session,
        account.id,
        {
            "id": "180",
            "timestamp": now.isoformat(),
            "media_product_type": product,
            "media_type": kind,
        },
        now,
    )
    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        await collect_media_insights(client, session, media, now, stats.warning)
        session.commit()
        snapshot = session.scalar(select(InstagramMediaInsights))
        expected = set(MEDIA_INSIGHT_METRICS)
        if product == "REELS":
            expected -= {"follows", "profile_visits"}
            expected.update(REEL_INSIGHT_METRICS)
            assert snapshot.follows is None and snapshot.profile_visits is None
            assert snapshot.avg_watch_time_ms == snapshot.total_watch_time_ms == 42
            assert snapshot.skip_rate == 42
        else:
            assert snapshot.follows == snapshot.profile_visits == 42
            assert snapshot.avg_watch_time_ms is None and snapshot.total_watch_time_ms is None
            assert snapshot.skip_rate is None
        assert set(requests) == expected and len(requests) == len(expected)
        assert snapshot.views == snapshot.reach == 42
        assert stats.warnings_count == 0
    finally:
        await client.close()


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"code": 100, "message": "Invalid metric profile_visits"}},
        {"data": []},
    ],
)
async def test_account_optional_absence_has_no_recurring_warning(
    settings,
    session,
    account,
    now,
    response,
):
    stats = RunStats()
    requested = []

    def handler(request):
        metric = request.url.params["metric"]
        requested.append(metric)
        if metric == "profile_visits":
            return httpx.Response(400 if "error" in response else 200, json=response)
        return httpx.Response(200, json={"data": [valid_metric(metric)]})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        await collect_account_insights(client, session, account, now, stats.warning)
        session.commit()
        row = session.scalar(select(InstagramAccountInsights))
        assert row.profile_visits is None and row.views == 42
        assert row.follows == 10 and row.unfollows == 2
        assert "follows_and_unfollows" in requested
        assert stats.warnings_count == 0
    finally:
        await client.close()


@pytest.mark.parametrize(
    "response",
    [
        {"unexpected": "payload"},
        {"data": None},
        {"data": {}},
        {"data": [{"name": "wrong_metric"}]},
        {"data": [{"name": "profile_visits", "values": [{"value": "invalid"}]}]},
    ],
)
async def test_optional_account_metric_still_warns_on_unexpected_response(
    settings,
    session,
    account,
    now,
    response,
):
    stats = RunStats()

    def handler(request):
        metric = request.url.params["metric"]
        return httpx.Response(
            200, json=(response if metric == "profile_visits" else {"data": [valid_metric(metric)]})
        )

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        await collect_account_insights(client, session, account, now, stats.warning)
        assert stats.warnings_count == 1
    finally:
        await client.close()


async def test_unrecognized_follow_breakdown_still_warns(settings, session, account, now):
    stats = RunStats()

    def handler(request):
        metric = request.url.params["metric"]
        if metric == "profile_visits":
            return httpx.Response(400, json={"error": {"code": 100, "message": "Invalid metric"}})
        item = (
            {
                "name": metric,
                "total_value": {
                    "breakdowns": [
                        {
                            "dimension_keys": ["follow_type"],
                            "results": [
                                {"dimension_values": ["UNRECOGNIZED"], "value": 50},
                            ],
                        }
                    ]
                },
            }
            if metric == "follows_and_unfollows"
            else valid_metric(metric)
        )
        return httpx.Response(200, json={"data": [item]})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        await collect_account_insights(client, session, account, now, stats.warning)
        session.commit()
        row = session.scalar(select(InstagramAccountInsights))
        assert row.follows is None and row.unfollows is None
        assert stats.warnings_count == 1
    finally:
        await client.close()


@pytest.mark.parametrize("status,code", [(403, 200), (400, 190), (429, 4), (503, 2)])
async def test_expected_optional_metric_does_not_swallow_relevant_errors(settings, status, code):
    settings = settings.model_copy(update={"request_max_retries": 0})
    stats = RunStats()
    client = InstagramClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                status,
                json={"error": {"code": code, "message": "API failure"}},
            )
        ),
    )
    try:
        with pytest.raises(InstagramAPIError):
            await client.optional_metric(
                "123", "profile_visits", {}, stats.warning, expected_unsupported=True
            )
    finally:
        await client.close()


async def test_reels_job_persists_zero_expected_warnings(settings, sessions, now, monkeypatch):
    monkeypatch.setattr("app.services.instagram_service.utcnow", lambda: now)

    def handler(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "123", "username": "test"})
        if request.url.path.endswith("/me/media"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "180",
                            "timestamp": now.isoformat(),
                            "media_type": "VIDEO",
                            "media_product_type": "REELS",
                        }
                    ]
                },
            )
        metric = request.url.params["metric"]
        assert metric not in {"follows", "profile_visits"}
        return httpx.Response(200, json={"data": [valid_metric(metric)]})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    service = InstagramService(settings, sessions, client)
    try:
        ids = await service.submit("media")
        await service.task
        with sessions() as session:
            run = session.get(ETLRun, ids[0])
            assert run.status == "SUCCESS" and run.warnings_count == 0
    finally:
        await client.close()
