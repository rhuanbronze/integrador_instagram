"""Central API metric-to-column mapping; unsupported names remain NULL."""

ACCOUNT_INSIGHT_METRICS = {
    name: name
    for name in (
        "views",
        "reach",
        "accounts_engaged",
        "total_interactions",
        "likes",
        "comments",
        "shares",
        "saves",
        "profile_visits",
        "profile_links_taps",
        "reposts",
    )
}
ACCOUNT_INSIGHT_METRICS["follows_and_unfollows"] = "follows_and_unfollows"
MEDIA_INSIGHT_METRICS = {
    name: name
    for name in (
        "views",
        "reach",
        "saved",
        "shares",
        "total_interactions",
        "follows",
        "profile_visits",
        "likes",
        "comments",
    )
}
REEL_INSIGHT_METRICS = {
    "ig_reels_avg_watch_time": "avg_watch_time_ms",
    "ig_reels_video_view_total_time": "total_watch_time_ms",
    "reels_skip_rate": "skip_rate",
}
# Empirically validated for the monitored account; skipped without API requests or warnings.
REEL_NOT_APPLICABLE_METRICS = frozenset({"follows", "profile_visits"})
ACCOUNT_EXPECTED_UNSUPPORTED_METRICS = frozenset({"profile_visits"})
AUDIENCE_METRICS = {
    "follower_demographics": "followers",
    "engaged_audience_demographics": "engaged",
    "reached_audience_demographics": "reached",
}
