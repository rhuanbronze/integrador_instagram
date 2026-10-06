"""Sequential jobs with database locking, incremental commits and durable audit rows."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text, update
from sqlalchemy.orm import Session, sessionmaker

from app.clients.instagram_client import InstagramAPIError, InstagramClient
from app.collectors.account_collector import collect_metadata, save_daily, upsert_account
from app.collectors.account_insights_collector import collect_account_insights, collect_audience
from app.collectors.media_collector import MEDIA_FIELDS, upsert_media
from app.collectors.media_insights_collector import collect_media_insights
from app.config import Settings
from app.models import ETLRun
from app.services.token_service import validate_token
from app.utils.dates import utcnow

logger = logging.getLogger(__name__)


class JobBusyError(Exception):
    pass


@dataclass
class RunStats:
    records_read: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    warnings_count: int = 0
    errors_count: int = 0

    def warning(self, message: str) -> None:
        self.warnings_count += 1
        logger.warning(message)


class InstagramService:
    def __init__(self, settings: Settings, sessions: sessionmaker, client: InstagramClient):
        self.settings = settings
        self.sessions = sessions
        self.client = client
        self.task: asyncio.Task | None = None
        self.lock_connection = None
        self.lock_name = (
            "ig-bi:" + hashlib.sha256(settings.mysql_database.encode()).hexdigest()[:48]
        )

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def _acquire(self) -> None:
        if self.busy or self.lock_connection is not None:
            raise JobBusyError()
        connection = self.sessions.kw["bind"].connect()
        try:
            if connection.dialect.name == "mysql":
                acquired = connection.scalar(
                    text("SELECT GET_LOCK(:name, 0)"), {"name": self.lock_name}
                )
                if acquired != 1:
                    raise JobBusyError()
            self.lock_connection = connection
        except BaseException:
            connection.close()
            raise

    def _release(self) -> None:
        if self.lock_connection is not None:
            try:
                if self.lock_connection.dialect.name == "mysql":
                    self.lock_connection.execute(
                        text("SELECT RELEASE_LOCK(:name)"), {"name": self.lock_name}
                    )
            finally:
                self.lock_connection.close()
                self.lock_connection = None

    async def submit(self, job_type: str) -> list[int]:
        if job_type not in {"account", "media", "all"}:
            raise ValueError("Invalid job type")
        self._acquire()
        try:
            jobs = ("account", "media") if job_type == "all" else (job_type,)
            with self.sessions() as session:
                # Holding the database lock proves these RUNNING rows are abandoned.
                session.execute(
                    update(ETLRun)
                    .where(ETLRun.status == "RUNNING")
                    .values(
                        status="FAILED",
                        finished_at=utcnow(),
                        errors_count=ETLRun.errors_count + 1,
                        error_message="Previous process interrupted before job completion",
                    )
                )
                runs = [ETLRun(job_type=job, started_at=utcnow(), status="RUNNING") for job in jobs]
                session.add_all(runs)
                session.commit()
                ids = [run.id for run in runs]
            self.task = asyncio.create_task(self._execute_many(list(zip(ids, jobs, strict=True))))
            return ids
        except BaseException:
            self._release()
            raise

    async def _execute_many(self, jobs: list[tuple[int, str]]) -> None:
        try:
            for run_id, job_type in jobs:
                await self._execute(run_id, job_type)
        except Exception:
            logger.error("Unable to finalize ETL audit; verify database")
        finally:
            # Cancellation may leave the second job of /all waiting to run.
            try:
                with self.sessions() as session:
                    session.execute(
                        update(ETLRun)
                        .where(
                            ETLRun.id.in_([run_id for run_id, _ in jobs]),
                            ETLRun.status == "RUNNING",
                        )
                        .values(
                            status="FAILED",
                            finished_at=utcnow(),
                            errors_count=1,
                            error_message="Collection interrupted",
                        )
                    )
                    session.commit()
            except Exception:
                logger.error("Unable to persist interrupted jobs; recovered on next collection")
            finally:
                self._release()

    async def _execute(self, run_id: int, job_type: str) -> None:
        stats = RunStats()
        status = "FAILED"
        error_message = None
        logger.info("Starting %s collection (run %s)", job_type, run_id)
        try:
            with self.sessions() as session:
                if job_type == "account":
                    await self._account(session, stats)
                else:
                    await self._media(session, stats)
                session.commit()
            status = (
                "SUCCESS_WITH_WARNINGS" if stats.warnings_count or stats.errors_count else "SUCCESS"
            )
        except asyncio.CancelledError:
            stats.errors_count += 1
            error_message = "Collection interrupted"
            raise
        except Exception as error:
            stats.errors_count += 1
            if isinstance(error, InstagramAPIError):
                error_message = "Instagram token invalid or expired" if error.oauth else str(error)
            else:
                error_message = "Collection failed; verify configuration and infrastructure"
            logger.error("Job %s failed: %s", run_id, error_message)
        finally:
            with self.sessions() as audit:
                run = audit.get(ETLRun, run_id)
                for field, value in vars(stats).items():
                    setattr(run, field, value)
                run.status = status
                run.finished_at = utcnow()
                run.error_message = error_message
                audit.commit()
            logger.info("Job %s finished: %s", run_id, status)

    async def _account(self, session: Session, stats: RunStats) -> None:
        metadata = await collect_metadata(self.client, stats.warning)
        now = utcnow()
        account, inserted = upsert_account(session, metadata)
        stats.records_read += 1
        session.commit()
        stats.records_inserted += int(inserted)
        stats.records_updated += int(not inserted)
        daily_inserted = save_daily(session, account.id, metadata, now, self.settings.timezone)
        session.commit()
        stats.records_inserted += int(daily_inserted)
        stats.records_updated += int(not daily_inserted)
        logger.info("Account metadata collected; followers: %s", metadata.get("followers_count"))
        insights_inserted = await collect_account_insights(
            self.client,
            session,
            account,
            now,
            stats.warning,
        )
        session.commit()
        stats.records_inserted += int(insights_inserted)
        stats.records_updated += int(not insights_inserted)
        if self.settings.audience_collection_enabled:
            try:
                with session.begin_nested():
                    inserted, updated = await collect_audience(
                        self.client, session, account, now, stats.warning
                    )
                session.commit()
                stats.records_inserted += inserted
                stats.records_updated += updated
            except Exception as error:
                if isinstance(error, InstagramAPIError) and error.oauth:
                    raise
                session.rollback()
                stats.warning(
                    "Optional audience collection unavailable; account snapshots preserved"
                )

    async def _media(self, session: Session, stats: RunStats) -> None:
        identity = await validate_token(self.client)
        account, inserted = upsert_account(session, identity)
        session.commit()
        stats.records_read += 1
        stats.records_inserted += int(inserted)
        stats.records_updated += int(not inserted)
        cutoff = utcnow() - timedelta(days=self.settings.media_insights_lookback_days)
        seen = set()
        fields = await self._media_fields(stats)
        async for page in self.client.media_pages(fields):
            for data in page:
                stats.records_read += 1
                if str(data.get("id")) in seen:
                    continue
                try:
                    media, inserted = upsert_media(session, account.id, data, utcnow())
                    session.commit()
                except (KeyError, ValueError):
                    session.rollback()
                    stats.errors_count += 1
                    stats.warning("Malformed media metadata skipped")
                    continue
                seen.add(media.instagram_media_id)
                stats.records_inserted += int(inserted)
                stats.records_updated += int(not inserted)
                if media.published_at < cutoff:
                    continue
                logger.info("Collecting insights for media %s", media.instagram_media_id)
                try:
                    await collect_media_insights(
                        self.client, session, media, utcnow(), stats.warning
                    )
                    session.commit()
                    stats.records_inserted += 1
                except InstagramAPIError as error:
                    session.rollback()
                    if error.oauth or error.transient:
                        raise
                    stats.errors_count += 1
                    stats.warning(f"Insights unavailable for media {media.instagram_media_id}")
        logger.info("Found %s media items; media collection completed", len(seen))

    async def _media_fields(self, stats: RunStats) -> str:
        """Probe once; isolate unsupported optional fields only if the bulk request fails."""
        try:
            await self.client.get("me/media", {"fields": MEDIA_FIELDS, "limit": 1})
            return MEDIA_FIELDS
        except InstagramAPIError as error:
            if not error.unsupported:
                raise
        fields = ["id", "timestamp"]
        for field in MEDIA_FIELDS.split(","):
            if field in fields:
                continue
            try:
                await self.client.get("me/media", {"fields": "id," + field, "limit": 1})
                fields.append(field)
            except InstagramAPIError as error:
                if not error.unsupported:
                    raise
                stats.warning(f"Optional media field {field} unavailable")
        return ",".join(fields)

    async def shutdown(self) -> None:
        if self.busy:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
