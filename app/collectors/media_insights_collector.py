import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.clients.instagram_client import InstagramClient
from app.collectors.insights_parser import scalar
from app.collectors.metrics import (
    MEDIA_INSIGHT_METRICS,
    REEL_INSIGHT_METRICS,
    REEL_NOT_APPLICABLE_METRICS,
)
from app.models import InstagramMedia, InstagramMediaInsights
from app.utils.dates import snapshot_date

logger = logging.getLogger(__name__)


async def collect_media_insights(
    client: InstagramClient,
    session: Session,
    media: InstagramMedia,
    now: datetime,
    warning: Callable[[str], None],
) -> None:
    metrics = dict(MEDIA_INSIGHT_METRICS)
    is_reel = media.media_product_type == "REELS" or media.media_type == "REELS"
    if is_reel:
        for metric in REEL_NOT_APPLICABLE_METRICS:
            metrics.pop(metric)
            logger.debug(
                "Metric %s NOT_APPLICABLE for REELS media %s", metric, media.instagram_media_id
            )
    if media.media_type in {"VIDEO", "REELS"} or media.media_product_type == "REELS":
        metrics.update(REEL_INSIGHT_METRICS)
    else:
        for metric in REEL_INSIGHT_METRICS:
            logger.debug(
                "Metric %s NOT_APPLICABLE for media %s (%s/%s)",
                metric,
                media.instagram_media_id,
                media.media_product_type,
                media.media_type,
            )
    values = {}
    for metric, column in metrics.items():
        item = await client.optional_metric(media.instagram_media_id, metric, {}, warning)
        values[column] = scalar(item)
        if item and values[column] is None:
            warning(f"Metric {metric} has no numeric total for media {media.instagram_media_id}")
    session.add(
        InstagramMediaInsights(
            media_id=media.id,
            collected_at=now,
            snapshot_date=snapshot_date(now, client.settings.timezone),
            **values,
        )
    )
