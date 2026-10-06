from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobAccepted(BaseModel):
    status: str = "accepted"
    run_ids: list[int]


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    records_read: int
    records_inserted: int
    records_updated: int
    warnings_count: int
    errors_count: int
    error_message: str | None


class StatusResponse(BaseModel):
    last_account_job: RunResponse | None
    last_media_job: RunResponse | None
    accounts_count: int
    media_count: int
    last_collection_at: datetime | None
    collection_running: bool
