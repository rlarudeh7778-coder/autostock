"""YouTube Data API v3 호출 래퍼.

쿼터 절약 원칙:
  - search.list 는 100유닛/회로 비싸다 → 필요한 페이지만 돈다.
  - videos.list / channels.list 는 1유닛/회 → id 를 50개씩 묶어 배치 호출한다.
"""
from __future__ import annotations

from typing import Callable, Iterable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config


class QuotaExceededError(RuntimeError):
    """일일 쿼터 초과 시 발생. 부분 수집 결과를 저장하고 종료하기 위해 사용."""


def _is_quota_error(err: HttpError) -> bool:
    text = str(err)
    return "quotaExceeded" in text or "dailyLimitExceeded" in text


class YouTubeClient:
    def __init__(self, api_key: str):
        self._yt = build(
            config.API_SERVICE_NAME,
            config.API_VERSION,
            developerKey=api_key,
            cache_discovery=False,
        )

    # ---- 1) 검색 ----
    def search_videos(
        self,
        query: str,
        max_results: int,
        order: str = config.DEFAULT_ORDER,
        published_after: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> list[str]:
        """주제어로 영상 ID 목록을 수집한다. pageToken 으로 max_results 까지 반복."""
        video_ids: list[str] = []
        page_token: str | None = None
        while len(video_ids) < max_results:
            per_page = min(50, max_results - len(video_ids))
            params = dict(
                q=query,
                part="id",
                type="video",
                maxResults=per_page,
                order=order,
            )
            if page_token:
                params["pageToken"] = page_token
            if published_after:
                params["publishedAfter"] = published_after

            resp = self._execute(self._yt.search().list(**params))
            for item in resp.get("items", []):
                vid = item.get("id", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            if progress:
                progress(f"  검색 중... 후보 {len(video_ids)}개 수집")

            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        # 중복 제거 (순서 유지)
        return list(dict.fromkeys(video_ids))

    # ---- 2) 영상 상세 ----
    def get_videos(
        self,
        video_ids: Iterable[str],
        progress: Callable[[str], None] | None = None,
    ) -> list[dict]:
        """videos.list 배치 호출로 상세 통계 수집."""
        ids = list(dict.fromkeys(video_ids))
        results: list[dict] = []
        for i, batch in enumerate(_chunks(ids, config.BATCH_SIZE)):
            resp = self._execute(
                self._yt.videos().list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(batch),
                    maxResults=config.BATCH_SIZE,
                )
            )
            results.extend(resp.get("items", []))
            if progress:
                progress(f"  통계 수집 중... {len(results)}/{len(ids)}개")
        return results

    # ---- 3) 채널 정보 ----
    def get_channels(
        self,
        channel_ids: Iterable[str],
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, dict]:
        """channels.list 배치 호출. {channel_id: channel_resource} 로 반환."""
        ids = list(dict.fromkeys(channel_ids))
        out: dict[str, dict] = {}
        for batch in _chunks(ids, config.BATCH_SIZE):
            resp = self._execute(
                self._yt.channels().list(
                    part="statistics,contentDetails,snippet",
                    id=",".join(batch),
                    maxResults=config.BATCH_SIZE,
                )
            )
            for item in resp.get("items", []):
                out[item["id"]] = item
            if progress:
                progress(f"  채널 정보 수집 중... {len(out)}/{len(ids)}개")
        return out

    # ---- 4) 업로드 재생목록에서 최근 영상 ID ----
    def get_recent_uploads(self, uploads_playlist_id: str, limit: int) -> list[str]:
        """uploads 재생목록에서 최근 영상 ID 를 limit 개까지 가져온다."""
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < limit:
            params = dict(
                part="contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=min(50, limit - len(ids)),
            )
            if page_token:
                params["pageToken"] = page_token
            resp = self._execute(self._yt.playlistItems().list(**params))
            for item in resp.get("items", []):
                vid = item.get("contentDetails", {}).get("videoId")
                if vid:
                    ids.append(vid)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    # ---- 내부 실행 헬퍼 (에러/쿼터 처리) ----
    @staticmethod
    def _execute(request):
        try:
            return request.execute()
        except HttpError as err:
            if _is_quota_error(err):
                raise QuotaExceededError(
                    "YouTube API 일일 쿼터를 초과했습니다. "
                    "부분 수집된 결과만 저장합니다. 내일 다시 시도하거나 쿼터를 늘리세요."
                ) from err
            raise RuntimeError(f"YouTube API 오류: {err}") from err


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
