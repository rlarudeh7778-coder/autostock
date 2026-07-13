#!/usr/bin/env python3
"""유튜브 레퍼런스 수집기 (Outlier Finder).

주제어를 입력하면 관련 영상을 수집해, "채널 평균 대비 유난히 잘 터진 영상(아웃라이어)"만
골라 보여준다. 절대 조회수가 아니라 '평소 대비 몇 배 터졌나'가 아이디어의 힘을 보여준다.

사용법:
  python main.py "홈카페"
  python main.py "재테크 초보" --multiplier 4 --order viewCount --since-months 6
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import config
import analyzer
import output
from youtube_api import YouTubeClient, QuotaExceededError


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="유튜브에서 '채널 평균 대비 잘 터진' 레퍼런스 영상을 찾아준다.",
    )
    p.add_argument("topic", help="검색할 주제어 (예: 퇴사, 재테크 초보, 홈카페)")
    p.add_argument("--multiplier", type=float, default=config.DEFAULT_MULTIPLIER,
                   help=f"아웃라이어 배수 임계값 (기본 {config.DEFAULT_MULTIPLIER})")
    p.add_argument("--order", choices=["relevance", "viewCount", "date", "rating"],
                   default=config.DEFAULT_ORDER, help="검색 정렬 기준")
    p.add_argument("--max-search", type=int, default=config.DEFAULT_MAX_SEARCH,
                   help=f"검색으로 모을 후보 영상 수 (기본 {config.DEFAULT_MAX_SEARCH})")
    p.add_argument("--recent", type=int, default=config.DEFAULT_RECENT,
                   help=f"채널 평균 산정용 최근 영상 수 (기본 {config.DEFAULT_RECENT})")
    p.add_argument("--since-months", type=int, default=None,
                   help="업로드 기간 필터: 최근 N개월 영상만 (선택)")
    p.add_argument("--format", choices=["short", "long", "all"],
                   default=config.DEFAULT_FORMAT, help="숏폼/롱폼 필터 (기본 all)")
    p.add_argument("--output-dir", default=config.DEFAULT_OUTPUT_DIR,
                   help="CSV/JSON 저장 폴더")
    return p.parse_args(argv)


def _published_after(since_months: int | None) -> str | None:
    if not since_months:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_months * 30)
    return cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collect(client: YouTubeClient, args, out_records: list) -> None:
    """수집 파이프라인. 후보 레코드를 먼저 만들어 out_records 에 채우고, 채널별로 그 자리에서
    enrich 한다. 이렇게 하면 중간에 쿼터가 터져도 이미 처리된 채널의 결과는 out_records 에 남아
    호출부가 부분 결과를 저장할 수 있다."""
    published_after = _published_after(args.since_months)

    # 1) 검색
    log(f"[1/4] '{args.topic}' 검색 중 (order={args.order})...")
    video_ids = client.search_videos(
        args.topic, args.max_search, args.order, published_after, progress=log
    )
    log(f"  → 후보 영상 {len(video_ids)}개")
    if not video_ids:
        return

    # 2) 영상 상세 → 후보 레코드 즉시 생성 (아직 enrich 전)
    log("[2/4] 영상 통계 수집 중...")
    video_items = client.get_videos(video_ids, progress=log)

    channel_ids = {
        it.get("snippet", {}).get("channelId")
        for it in video_items
        if it.get("snippet", {}).get("channelId")
    }

    # 3) 채널 정보 (구독자 수, uploads 재생목록)
    log(f"[3/4] 채널 {len(channel_ids)}개 정보 수집 중...")
    channels = client.get_channels(channel_ids, progress=log)

    # 후보 레코드 생성 (채널별로 묶어둔다)
    by_channel: dict[str, list[analyzer.VideoRecord]] = {}
    for it in video_items:
        cid = it.get("snippet", {}).get("channelId", "")
        subs = _subscriber_count(channels.get(cid))
        rec = analyzer.build_video_record(it, subs)
        out_records.append(rec)
        by_channel.setdefault(cid, []).append(rec)

    # 4) 채널별 최근 영상으로 형식별 평균 산정 → 해당 채널 후보들 enrich
    log(f"[4/4] 채널별 최근 {args.recent}개 영상으로 평균 조회수 계산 중...")
    for idx, cid in enumerate(by_channel, 1):
        ch = channels.get(cid)
        uploads = (
            (ch or {})
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if uploads:
            recent_ids = client.get_recent_uploads(uploads, args.recent)
            recent_items = client.get_videos(recent_ids)
            recent_records = [analyzer.build_video_record(it, None) for it in recent_items]
            baselines = analyzer.channel_baselines(recent_records)
        else:
            baselines = analyzer.channel_baselines([])

        for rec in by_channel[cid]:
            baseline = baselines.get(rec.is_short, {"mean": 0.0, "median": 0.0, "n": 0})
            analyzer.enrich(rec, baseline)
        log(f"  채널 평균 계산 {idx}/{len(by_channel)}")


def _subscriber_count(channel: dict | None) -> int | None:
    if not channel:
        return None
    stats = channel.get("statistics", {})
    if stats.get("hiddenSubscriberCount"):
        return None
    try:
        return int(stats.get("subscriberCount"))
    except (TypeError, ValueError):
        return None


def finalize(records, args) -> None:
    kept = analyzer.filter_and_sort(records, args.multiplier, args.format)
    log(f"\n아웃라이어 배수 x{args.multiplier} 이상: {len(kept)}개 (전체 후보 {len(records)}개 중)")
    output.print_console(kept)
    output.print_pattern_summary(kept)
    csv_path, json_path = output.save_files(kept, args.topic, args.output_dir)
    log(f"\n저장 완료:\n  - {csv_path}\n  - {json_path}")


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        api_key = config.get_api_key()
    except RuntimeError as e:
        log(str(e))
        return 2

    client = YouTubeClient(api_key)
    records: list[analyzer.VideoRecord] = []
    try:
        collect(client, args, records)
    except QuotaExceededError as e:
        log(f"\n[쿼터 초과] {e}")
        # 부분 결과라도 저장
        if records:
            finalize(records, args)
        return 1
    except RuntimeError as e:
        log(f"\n[오류] {e}")
        if records:
            finalize(records, args)
        return 1
    except KeyboardInterrupt:
        log("\n중단되었습니다.")
        return 130

    if not records:
        log("수집된 영상이 없습니다. 주제어나 옵션을 바꿔보세요.")
        return 0

    finalize(records, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
