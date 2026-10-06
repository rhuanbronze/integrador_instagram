import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.instagram_service import InstagramService, JobBusyError
from app.utils.dates import utcnow

logger = logging.getLogger(__name__)


def start_scheduler(service: InstagramService) -> AsyncIOScheduler:
    zone = ZoneInfo(service.settings.timezone)
    scheduler = AsyncIOScheduler(timezone=zone)

    async def collect(job_type: str) -> None:
        try:
            await service.submit(job_type)
        except JobBusyError:
            logger.info("Scheduled %s job skipped; collection already running", job_type)
        except Exception:
            logger.error("Unable to start scheduled %s job; verify database", job_type)

    for job_type, hours in (
        ("account", service.settings.account_collection_hours),
        ("media", service.settings.media_collection_hours),
    ):
        scheduler.add_job(
            collect,
            trigger=IntervalTrigger(hours=hours, timezone=zone),
            args=[job_type],
            id=job_type,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
            next_run_time=utcnow() + timedelta(hours=hours),
        )
    scheduler.start()
    return scheduler
