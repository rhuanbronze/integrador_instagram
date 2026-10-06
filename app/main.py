import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api import routes_health, routes_jobs
from app.clients.instagram_client import InstagramClient
from app.config import get_settings
from app.database.session import build_engine, check_database, session_factory
from app.models import ETLRun
from app.services.instagram_service import InstagramService, JobBusyError
from app.services.scheduler_service import start_scheduler
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        settings = get_settings()
    except Exception:
        raise RuntimeError("Invalid environment configuration; verify required variables") from None
    configure_logging(
        settings.log_level,
        tuple(
            secret.get_secret_value()
            for secret in (
                settings.instagram_access_token,
                settings.mysql_password,
                settings.admin_api_key,
            )
        ),
    )
    engine = build_engine(settings)
    try:
        check_database(engine)
        sessions = session_factory(engine)
        with sessions() as session:
            session.execute(select(ETLRun.id).limit(1))
    except Exception:
        engine.dispose()
        raise RuntimeError("Database unavailable or migrations missing") from None
    client = InstagramClient(settings)
    service = InstagramService(settings, sessions, client)
    application.state.settings = settings
    application.state.engine = engine
    application.state.sessions = sessions
    application.state.service = service
    scheduler = None
    try:
        if settings.collect_on_startup:
            try:
                await service.submit("all")
            except JobBusyError:
                logger.info("Startup collection already running in another process")
        if settings.scheduler_enabled:
            scheduler = start_scheduler(service)
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
        await service.shutdown()
        await client.close()
        engine.dispose()


app = FastAPI(title="Instagram BI", version="1.0.0", lifespan=lifespan)
app.include_router(routes_health.router)
app.include_router(routes_jobs.router)


@app.exception_handler(Exception)
async def internal_error(request: Request, exception: Exception):
    logger.error("HTTP request failed; error type: %s", type(exception).__name__)
    return JSONResponse({"detail": "Internal error; verify service status"}, status_code=500)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exception: RequestValidationError):
    # FastAPI's default validator can echo user-supplied header/body values.
    return JSONResponse({"detail": "Invalid request"}, status_code=422)
