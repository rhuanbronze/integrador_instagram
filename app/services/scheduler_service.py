import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.instagram_service import InstagramService, JobBusyError

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

    for job_type, hour, minute in (
        ("account", service.settings.account_cron_hour, service.settings.account_cron_minute),
        ("media", service.settings.media_cron_hours, service.settings.media_cron_minute),
    ):
        scheduler.add_job(
            collect,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=zone),
            args=[job_type],
            id=job_type,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
    scheduler.start()
    return scheduler
