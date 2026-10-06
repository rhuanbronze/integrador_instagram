from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InstagramMedia
from app.utils.dates import parse_timestamp

MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,timestamp,like_count,"
    "comments_count,thumbnail_url,media_url"
)
METADATA_COLUMNS = (
    "caption",
    "media_type",
    "media_product_type",
    "permalink",
    "thumbnail_url",
    "media_url",
    "like_count",
    "comments_count",
)


def upsert_media(
    session: Session, account_id: int, data: dict, now: datetime
) -> tuple[InstagramMedia, bool]:
    media_id = str(data["id"])
    if not media_id.isdigit():
        raise ValueError("Invalid media identity")
    published_at = parse_timestamp(data["timestamp"])
    media = session.scalar(
        select(InstagramMedia).where(
            InstagramMedia.instagram_media_id == media_id,
        )
    )
    inserted = media is None
    if media is None:
        media = InstagramMedia(
            account_id=account_id,
            instagram_media_id=media_id,
            first_seen_at=now,
            published_at=published_at,
        )
        session.add(media)
    if media.account_id != account_id:
        raise ValueError("Media belongs to another monitored account")
    for field in METADATA_COLUMNS:
        setattr(media, field, data.get(field))
    media.published_at = published_at
    media.last_seen_at = now
    session.flush()
    return media, inserted
