from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.clients.instagram_client import InstagramClient
from app.collectors.account_insights_collector import collect_account_insights
from app.collectors.insights_parser import breakdown_rows, follows_and_unfollows, scalar
from app.collectors.media_collector import upsert_media
from app.collectors.media_insights_collector import collect_media_insights
from app.models import InstagramAccountInsights, InstagramMediaInsights


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"values": [{"value": 12}, {"value": 3}]}, 15),
        ({"total_value": {"value": 19}}, 19),
        ({"total_value": 8}, 8),
        ({"values": [{"value": 0}]}, 0),
        ({"total_value": {"value": "23.125"}}, Decimal("23.125")),
        ({"total_value": {"value": "NaN"}}, None),
        ({"values": [{"value": 12}, {}]}, None),
        ({"values": [{"value": {"unknown": 5}}]}, None),
        ({"data": []}, None),
        ({"values": None}, None),
        ({"values": {"unknown": 3}}, None),
        (None, None),
    ],
)
def test_scalar_formats(payload, expected):
    assert scalar(payload) == expected


def follow_payload():
    return {
        "name": "follows_and_unfollows",
        "total_value": {
            "breakdowns": [
                {
                    "dimension_keys": ["follow_type"],
                    "results": [
                        {"dimension_values": ["FOLLOW"], "value": 100},
                        {"dimension_values": ["UNFOLLOW"], "value": 30},
                    ],
                }
            ]
        },
    }


def test_follow_actions_are_separate_from_net_delta():
    assert follows_and_unfollows(follow_payload()) == {"follows": 100, "unfollows": 30}
    assert follows_and_unfollows({"total_value": {"value": 70}}) == {
        "follows": None,
        "unfollows": None,
    }
    assert follows_and_unfollows({"values": [{"value": {"follows": 100, "unfollows": 30}}]}) == {
        "follows": 100,
        "unfollows": 30,
    }


def test_unknown_breakdown_labels_are_not_invented():
    item = {
        "total_value": {
            "breakdowns": [
                {
                    "dimension_keys": ["follow_type"],
                    "results": [{"dimension_values": ["NON_FOLLOWER"], "value": 99}],
                }
            ]
        }
    }
    assert follows_and_unfollows(item) == {"follows": None, "unfollows": None}


def test_breakdown_dimensions_do_not_depend_on_position():
    item = {
        "values": [
            {
                "breakdowns": [
                    {
                        "dimension_keys": ["gender", "age"],
                        "results": [{"dimension_values": ["F", "25-34"], "value": 2380}],
                    }
                ]
            }
        ]
    }
    assert list(breakdown_rows(item)) == [({"gender": "F", "age": "25-34"}, 2380)]


async def test_one_invalid_metric_does_not_lose_media_snapshot(settings, session, account, now):
    requested = []
    warnings = []
    media, _ = upsert_media(
        session,
        account.id,
        {
            "id": "180",
            "timestamp": now.isoformat(),
            "media_type": "VIDEO",
            "media_product_type": "REELS",
        },
        now,
    )

    def handler(request):
        metric = request.url.params["metric"]
        requested.append(metric)
        if metric == "reels_skip_rate":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 100,
                        "message": "Invalid metric reels_skip_rate fake-token-never-real",
                    }
                },
            )
        if metric == "saved":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"data": [{"name": metric, "values": [{"value": 42}]}]})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        await collect_media_insights(client, session, media, now, warnings.append)
        session.commit()
        snapshot = session.scalar(select(InstagramMediaInsights))
        assert snapshot.views == 42
        assert snapshot.avg_watch_time_ms == 42
        assert snapshot.skip_rate is None
        assert snapshot.saved is None
        assert len(warnings) == 2
        assert "comments" in requested
        assert all("fake-token" not in warning for warning in warnings)
    finally:
        await client.close()


async def test_account_window_and_action_breakdown(settings, session, account, now):
    def handler(request):
        metric = request.url.params["metric"]
        assert request.url.params["period"] == "day"
        assert request.url.params["metric_type"] == "total_value"
        assert int(request.url.params["until"]) - int(request.url.params["since"]) == 86400
        if metric == "follows_and_unfollows":
            assert request.url.params["breakdown"] == "follow_type"
            return httpx.Response(200, json={"data": [follow_payload()]})
        return httpx.Response(200, json={"data": [{"name": metric, "total_value": {"value": 5}}]})

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        await collect_account_insights(client, session, account, now, lambda _: None)
        session.commit()
        row = session.scalar(select(InstagramAccountInsights))
        assert row.follows == 100 and row.unfollows == 30
        assert row.period_start.isoformat() == row.period_end.isoformat() == "2026-10-04"
    finally:
        await client.close()
