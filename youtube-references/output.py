"""결과 출력: 콘솔 표 + CSV/JSON 저장 + 제목/구독자 패턴 요약."""
from __future__ import annotations

import json
import os
import re
from datetime import date

import pandas as pd

try:
    from tabulate import tabulate
    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False

import config
from analyzer import VideoRecord


# ---- 제목 패턴 규칙 (레퍼런스 패턴 분석용) ----
_QUESTION_HINTS = ("?", "？", "왜", "어떻게", "무엇", "뭐", "how", "why", "what")
_CURIOSITY_HINTS = ("충격", "소름", "경악", "실화", "레전드", "미친", "역대급", "결국", "이유", "진실", "폭로", "반전")


def classify_title(title: str) -> list[str]:
    tags = []
    if re.search(r"\d", title):
        tags.append("숫자형")
    low = title.lower()
    if any(h in title or h in low for h in _QUESTION_HINTS):
        tags.append("질문형")
    if any(h in title for h in _CURIOSITY_HINTS):
        tags.append("호기심/자극")
    if not tags:
        tags.append("일반")
    return tags


def _fmt_num(n) -> str:
    if n is None:
        return "비공개"
    return f"{int(n):,}"


def _short_title(title: str, width: int = 40) -> str:
    return title if len(title) <= width else title[: width - 1] + "…"


def print_console(records: list[VideoRecord]) -> None:
    if not records:
        print("\n조건(아웃라이어)을 만족하는 영상이 없습니다. --multiplier 를 낮춰보세요.")
        return

    rows = []
    for i, r in enumerate(records, 1):
        flag = " ⚠" if r.low_confidence else ""
        rows.append([
            i,
            _short_title(r.title),
            _fmt_num(r.view_count),
            _fmt_num(r.like_count),
            _fmt_num(r.comment_count),
            f"x{r.outlier_mean}{flag}",
            _fmt_num(r.velocity),
            _short_title(r.channel_title, 18),
            _fmt_num(r.subscriber_count),
            (r.published_at or "")[:10],
            "숏폼" if r.is_short else "롱폼",
        ])

    headers = ["순위", "제목", "조회수", "좋아요", "댓글", "아웃라이어",
               "일일조회", "채널", "구독자", "업로드", "형식"]

    print()
    if _HAS_TABULATE:
        print(tabulate(rows, headers=headers, tablefmt="github"))
    else:
        print("\t".join(headers))
        for row in rows:
            print("\t".join(str(c) for c in row))
    print("\n(⚠ = 채널 비교 표본 부족으로 신뢰도 낮음)")


def print_pattern_summary(records: list[VideoRecord]) -> None:
    if not records:
        return
    print("\n===== 패턴 요약 (레퍼런스는 모으는 게 아니라 패턴을 찾는 것) =====")

    # 제목 패턴
    title_counts: dict[str, int] = {}
    for r in records:
        for tag in classify_title(r.title):
            title_counts[tag] = title_counts.get(tag, 0) + 1
    print("\n[제목 앵글 분포]")
    for tag, cnt in sorted(title_counts.items(), key=lambda x: -x[1]):
        print(f"  - {tag}: {cnt}개")

    # 구독자 규모 구간
    print("\n[구독자 규모별 아웃라이어 분포]  (작은 채널의 아웃라이어가 가장 베낄 가치가 큼)")
    for label, lo, hi in config.SUBSCRIBER_TIERS:
        subset = [
            r for r in records
            if r.subscriber_count is not None and lo <= r.subscriber_count < hi
        ]
        if subset:
            avg_mult = sum(r.outlier_mean for r in subset) / len(subset)
            print(f"  - {label}: {len(subset)}개 (평균 아웃라이어 x{avg_mult:.1f})")

    # 형식 분포
    shorts = sum(1 for r in records if r.is_short)
    longs = len(records) - shorts
    print(f"\n[형식 분포] 숏폼 {shorts}개 / 롱폼 {longs}개")


def _records_to_dataframe(records: list[VideoRecord]) -> pd.DataFrame:
    data = []
    for i, r in enumerate(records, 1):
        d = r.to_dict()
        d["rank"] = i
        d["title_patterns"] = ", ".join(classify_title(r.title))
        data.append(d)
    cols = [
        "rank", "title", "view_count", "like_count", "comment_count",
        "outlier_mean", "outlier_median", "velocity", "engagement_rate",
        "views_per_subscriber", "channel_title", "subscriber_count",
        "is_short", "duration_seconds", "published_at", "sample_size",
        "low_confidence", "title_patterns", "thumbnail", "url",
        "channel_mean", "channel_median", "video_id", "channel_id",
    ]
    df = pd.DataFrame(data)
    if not df.empty:
        df = df[[c for c in cols if c in df.columns]]
    return df


def save_files(records: list[VideoRecord], topic: str, output_dir: str) -> tuple[str, str]:
    """CSV + JSON 저장. (csv_path, json_path) 반환."""
    os.makedirs(output_dir, exist_ok=True)
    safe_topic = re.sub(r"[^\w가-힣]+", "_", topic).strip("_") or "topic"
    stamp = date.today().isoformat()
    base = f"references_{safe_topic}_{stamp}"
    csv_path = os.path.join(output_dir, base + ".csv")
    json_path = os.path.join(output_dir, base + ".json")

    df = _records_to_dataframe(records)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")  # 엑셀 한글 호환

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            [r.to_dict() for r in records],
            f,
            ensure_ascii=False,
            indent=2,
        )
    return csv_path, json_path
