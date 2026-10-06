import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select

from app.models import ETLRun, InstagramAccount, InstagramMedia
from app.schemas.jobs import JobAccepted, RunResponse, StatusResponse
from app.services.instagram_service import JobBusyError

router = APIRouter(prefix="/api")


def require_admin(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.settings.admin_api_key.get_secret_value()
    if not x_api_key or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/status", response_model=StatusResponse)
def status(request: Request):
    with request.app.state.sessions() as session:

        def latest(job_type: str):
            run = session.scalar(
                select(ETLRun)
                .where(ETLRun.job_type == job_type)
                .order_by(ETLRun.id.desc())
                .limit(1)
            )
            return RunResponse.model_validate(run) if run else None

        return StatusResponse(
            last_account_job=latest("account"),
            last_media_job=latest("media"),
            accounts_count=session.scalar(select(func.count()).select_from(InstagramAccount)),
            media_count=session.scalar(select(func.count()).select_from(InstagramMedia)),
            last_collection_at=session.scalar(
                select(func.max(ETLRun.finished_at)).where(
                    ETLRun.status.in_(["SUCCESS", "SUCCESS_WITH_WARNINGS"]),
                )
            ),
            collection_running=request.app.state.service.busy,
        )


async def start_job(request: Request, job_type: str) -> JobAccepted:
    try:
        ids = await request.app.state.service.submit(job_type)
    except JobBusyError:
        raise HTTPException(status_code=409, detail="Collection already running") from None
    return JobAccepted(run_ids=ids)


@router.post(
    "/jobs/account",
    status_code=202,
    response_model=JobAccepted,
    dependencies=[Depends(require_admin)],
)
async def account_job(request: Request):
    return await start_job(request, "account")


@router.post(
    "/jobs/media",
    status_code=202,
    response_model=JobAccepted,
    dependencies=[Depends(require_admin)],
)
async def media_job(request: Request):
    return await start_job(request, "media")


@router.post(
    "/jobs/all", status_code=202, response_model=JobAccepted, dependencies=[Depends(require_admin)]
)
async def all_jobs(request: Request):
    return await start_job(request, "all")
