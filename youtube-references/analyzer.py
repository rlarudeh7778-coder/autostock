"""수집 데이터 분석: 형식 분류, 채널 평균/중앙값, 아웃라이어 배수, 보조 지표, 필터·정렬.

정확도 원칙:
  - 숏폼(<=60초)과 롱폼은 조회수 스케일이 다르므로 분리해서 비교한다.
  - 채널 평균은 전체가 아닌 "최근 N개" 로 산정한다 (호출 측에서 최근 N개만 넘겨줌).
  - 평균은 한 영상의 떡상으로 부풀려지므로 중앙값도 함께 계산한다.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import config

# ISO8601 duration (예: PT1H2M3S, PT45S)
_DURATION_RE = re.compile(
    r"PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?"
)


def parse_duration_seconds(iso: str) -> int:
    m = _DURATION_RE.fullmatch(iso or "")
    if not m:
        return 0
    h = int(m.group("h") or 0)
    mi = int(m.group("m") or 0)
    s = int(m.group("s") or 0)
    return h * 3600 + mi * 60 + s


def is_short(duration_seconds: int) -> bool:
    return 0 < duration_seconds <= config.SHORTS_MAX_SECONDS


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class VideoRecord:
    video_id: str
    title: str
    url: str
    thumbnail: str
    channel_id: str
    channel_title: str
    published_at: str          # ISO8601
    duration_seconds: int
    is_short: bool
    view_count: int
    like_count: int | None     # 비공개면 None
    comment_count: int | None  # 비공개면 None
    subscriber_count: int | None

    # 분석 결과 (나중에 채워짐)
    channel_mean: float = 0.0
    channel_median: float = 0.0
    sample_size: int = 0
    low_confidence: bool = False
    outlier_mean: float = 0.0
    outlier_median: float = 0.0
    velocity: float = 0.0        # 일일 조회수
    engagement_rate: float | None = None
    views_per_subscriber: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def build_video_record(item: dict, subscriber_count: int | None) -> VideoRecord:
    """videos.list item 을 VideoRecord 로 변환."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    vid = item.get("id", "")
    thumbs = snippet.get("thumbnails", {})
    thumb = (
        thumbs.get("maxres")
        or thumbs.get("high")
        or thumbs.get("medium")
        or thumbs.get("default")
        or {}
    ).get("url", "")

    dur = parse_duration_seconds(content.get("duration", ""))
    # 비공개 지표는 응답에 아예 키가 없다 → None 으로 구분
    like = _to_int(stats["likeCount"]) if "likeCount" in stats else None
    comment = _to_int(stats["commentCount"]) if "commentCount" in stats else None

    return VideoRecord(
        video_id=vid,
        title=snippet.get("title", ""),
        url=f"https://www.youtube.com/watch?v={vid}",
        thumbnail=thumb,
        channel_id=snippet.get("channelId", ""),
        channel_title=snippet.get("channelTitle", ""),
        published_at=snippet.get("publishedAt", ""),
        duration_seconds=dur,
        is_short=is_short(dur),
        view_count=_to_int(stats.get("viewCount")),
        like_count=like,
        comment_count=comment,
        subscriber_count=subscriber_count,
    )


def channel_baselines(recent_records: list[VideoRecord]) -> dict[bool, dict]:
    """채널의 최근 영상들로 형식별(숏폼/롱폼) 평균·중앙값·표본수를 계산.

    반환: {is_short: {"mean": .., "median": .., "n": ..}}
    """
    result: dict[bool, dict] = {}
    for short_flag in (True, False):
        views = [
            r.view_count
            for r in recent_records
            if r.is_short == short_flag and r.view_count > 0
        ]
        if views:
            result[short_flag] = {
                "mean": statistics.mean(views),
                "median": statistics.median(views),
                "n": len(views),
            }
        else:
            result[short_flag] = {"mean": 0.0, "median": 0.0, "n": 0}
    return result


def enrich(record: VideoRecord, baseline: dict, now: datetime | None = None) -> VideoRecord:
    """한 영상 레코드에 아웃라이어 배수와 보조 지표를 채운다.

    baseline: 해당 영상 형식(숏폼/롱폼)에 맞는 {"mean","median","n"}.
    """
    now = now or datetime.now(timezone.utc)

    record.channel_mean = baseline.get("mean", 0.0)
    record.channel_median = baseline.get("median", 0.0)
    record.sample_size = baseline.get("n", 0)
    record.low_confidence = record.sample_size < config.MIN_SAMPLE_FOR_CONFIDENCE

    if record.channel_mean > 0:
        record.outlier_mean = round(record.view_count / record.channel_mean, 2)
    if record.channel_median > 0:
        record.outlier_median = round(record.view_count / record.channel_median, 2)

    # velocity = 조회수 / 경과일
    days = _days_since(record.published_at, now)
    record.velocity = round(record.view_count / max(1, days), 1)

    # 참여율 = (좋아요 + 댓글) / 조회수 (둘 중 하나라도 공개일 때만)
    if record.view_count > 0 and (
        record.like_count is not None or record.comment_count is not None
    ):
        likes = record.like_count or 0
        comments = record.comment_count or 0
        record.engagement_rate = round((likes + comments) / record.view_count, 4)

    # 구독자 대비 조회수
    if record.subscriber_count and record.subscriber_count > 0:
        record.views_per_subscriber = round(
            record.view_count / record.subscriber_count, 2
        )

    return record


def _days_since(iso: str, now: datetime) -> int:
    try:
        published = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 1
    delta = now - published
    return max(0, delta.days)


def filter_and_sort(
    records: list[VideoRecord],
    multiplier: float,
    fmt: str = "all",
) -> list[VideoRecord]:
    """아웃라이어 배수(평균 기준) >= multiplier 인 것만, 조회수 내림차순."""
    kept = []
    for r in records:
        if fmt == "short" and not r.is_short:
            continue
        if fmt == "long" and r.is_short:
            continue
        if r.outlier_mean >= multiplier:
            kept.append(r)
    kept.sort(key=lambda r: r.view_count, reverse=True)
    return kept
