"""Calendar schedules follow the configured timezone, independent of process startup."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError

from app.config import Settings
from app.services.scheduler_service import start_scheduler


@pytest.fixture
def scheduled_jobs(settings):
    service = SimpleNamespace(settings=settings, submit=AsyncMock())
    # Keep real triggers and jobs; prevent background execution during unit tests.
    with patch("app.services.scheduler_service.AsyncIOScheduler.start") as start:
        scheduler = start_scheduler(service)
    start.assert_called_once_with()
    return scheduler, service


def test_schedule_defaults(settings):
    assert settings.timezone == "America/Cuiaba"
    assert settings.account_cron_hour == 7
    assert settings.account_cron_minute == 0
    assert settings.media_cron_hours == "0,6,12,18"
    assert settings.media_cron_minute == 0


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2026, 10, 7, 10, 59, tzinfo=UTC), datetime(2026, 10, 7, 11, tzinfo=UTC)),
        (datetime(2026, 10, 7, 11, 0, 1, tzinfo=UTC), datetime(2026, 10, 8, 11, tzinfo=UTC)),
        (datetime(2026, 10, 8, 3, 59, tzinfo=UTC), datetime(2026, 10, 8, 11, tzinfo=UTC)),
    ],
)
def test_account_runs_at_seven_cuiaba(scheduled_jobs, now, expected):
    scheduler, _ = scheduled_jobs
    trigger = scheduler.get_job("account").trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "America/Cuiaba"
    next_run = trigger.get_next_fire_time(None, now)
    assert next_run.astimezone(UTC) == expected
    assert (next_run.hour, next_run.minute, next_run.second) == (7, 0, 0)


def test_media_runs_at_all_four_hours_across_midnight(scheduled_jobs):
    scheduler, _ = scheduled_jobs
    trigger = scheduler.get_job("media").trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "America/Cuiaba"
    previous = None
    now = datetime(2026, 10, 7, 3, 59, tzinfo=UTC)
    expected = [datetime(2026, 10, 7, hour, tzinfo=UTC) for hour in (4, 10, 16, 22)] + [
        datetime(2026, 10, 8, 4, tzinfo=UTC)
    ]
    for expected_run in expected:
        next_run = trigger.get_next_fire_time(previous, now)
        assert next_run.astimezone(UTC) == expected_run
        assert next_run.hour in (0, 6, 12, 18)
        assert (next_run.minute, next_run.second) == (0, 0)
        previous = next_run
        now = next_run + timedelta(seconds=1)


def test_schedule_uses_environment_overrides(settings, monkeypatch):
    monkeypatch.setenv("TIMEZONE", "UTC")
    monkeypatch.setenv("ACCOUNT_CRON_HOUR", "9")
    monkeypatch.setenv("ACCOUNT_CRON_MINUTE", "15")
    monkeypatch.setenv("MEDIA_CRON_HOURS", "1,13")
    monkeypatch.setenv("MEDIA_CRON_MINUTE", "30")
    values = settings.model_dump()
    for field in (
        "timezone",
        "account_cron_hour",
        "account_cron_minute",
        "media_cron_hours",
        "media_cron_minute",
    ):
        values.pop(field)
    service = SimpleNamespace(settings=Settings(_env_file=None, **values))
    with patch("app.services.scheduler_service.AsyncIOScheduler.start"):
        scheduler = start_scheduler(service)
    now = datetime(2026, 10, 7, tzinfo=UTC)
    assert scheduler.get_job("account").trigger.get_next_fire_time(None, now) == datetime(
        2026, 10, 7, 9, 15, tzinfo=UTC
    )
    assert scheduler.get_job("media").trigger.get_next_fire_time(None, now) == datetime(
        2026, 10, 7, 1, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("job_type", ["account", "media"])
async def test_scheduled_callback_submits_correct_job(scheduled_jobs, job_type):
    scheduler, service = scheduled_jobs
    job = scheduler.get_job(job_type)
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 300
    await job.func(*job.args)
    service.submit.assert_awaited_once_with(job_type)


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_cron_hour", -1),
        ("account_cron_hour", 24),
        ("account_cron_minute", 60),
        ("media_cron_hours", "0,24"),
        ("media_cron_hours", "0,,6"),
        ("media_cron_hours", ""),
        ("media_cron_minute", -1),
        ("media_cron_minute", 60),
    ],
)
def test_invalid_schedule_rejected(settings, field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(settings.model_dump() | {field: value}))
