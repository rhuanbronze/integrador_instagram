from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.instagram_client import InstagramAPIError, InstagramClient
from app.models import InstagramAccount, InstagramAccountDaily
from app.utils.dates import snapshot_date

ACCOUNT_FIELDS = (
    "name",
    "profile_picture_url",
    "followers_count",
    "follows_count",
    "media_count",
)


def followers_delta(current: int | None, previous: int | None) -> int | None:
    return current - previous if current is not None and previous is not None else None


async def collect_metadata(client: InstagramClient, warning: Callable[[str], None]) -> dict:
    identity = await client.get("me", {"fields": "id,username"})
    user_id = str(identity.get("id", ""))
    if not user_id.isdigit():
        raise InstagramAPIError()
    configured = client.settings.instagram_user_id
    if configured and configured != user_id:
        raise ValueError("Configured Instagram user ID differs from authenticated account")
    try:
        fields = await client.get("me", {"fields": "id,username," + ",".join(ACCOUNT_FIELDS)})
        identity.update(fields)
    except InstagramAPIError as error:
        if not error.unsupported:
            raise
        # A rejected optional field must not hide all follower counters.
        for field in ACCOUNT_FIELDS:
            try:
                value = await client.get("me", {"fields": field})
                identity[field] = value.get(field)
            except InstagramAPIError as field_error:
                if not field_error.unsupported:
                    raise
                identity[field] = None
    for field in ACCOUNT_FIELDS:
        if identity.get(field) is None:
            warning(f"Account field {field} unavailable")
    return identity


def upsert_account(session: Session, data: dict) -> tuple[InstagramAccount, bool]:
    account = session.scalar(
        select(InstagramAccount).where(InstagramAccount.instagram_user_id == str(data["id"]))
    )
    inserted = account is None
    if account is None:
        account = InstagramAccount(instagram_user_id=str(data["id"]))
        session.add(account)
    for field in ("username", "name", "profile_picture_url"):
        # Identity-only validation must not erase previously collected metadata.
        if field in data:
            setattr(account, field, data[field])
    session.flush()
    return account, inserted


def save_daily(session: Session, account_id: int, data: dict, now: datetime, timezone: str) -> bool:
    day = snapshot_date(now, timezone)
    daily = session.scalar(
        select(InstagramAccountDaily).where(
            InstagramAccountDaily.account_id == account_id,
            InstagramAccountDaily.snapshot_date == day,
        )
    )
    previous = session.scalar(
        select(InstagramAccountDaily)
        .where(
            InstagramAccountDaily.account_id == account_id,
            InstagramAccountDaily.snapshot_date < day,
        )
        .order_by(InstagramAccountDaily.snapshot_date.desc())
        .limit(1)
    )
    inserted = daily is None
    if daily is None:
        daily = InstagramAccountDaily(account_id=account_id, snapshot_date=day, collected_at=now)
        session.add(daily)
    for field in ("followers_count", "follows_count", "media_count"):
        setattr(daily, field, data.get(field))
    daily.followers_delta = followers_delta(
        daily.followers_count,
        previous.followers_count if previous else None,
    )
    daily.collected_at = now
    session.flush()
    return inserted
