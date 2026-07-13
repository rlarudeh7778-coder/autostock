"""전역 설정 및 기본 상수.

API 키는 환경변수 YOUTUBE_API_KEY 에서 읽는다. 없으면 같은 폴더의 .env 를 로드한다.
코드에 키를 하드코딩하지 않는다.
"""
import os

try:
    from dotenv import load_dotenv  # python-dotenv (선택)

    load_dotenv()
except ImportError:  # python-dotenv 미설치 시에도 환경변수만으로 동작
    pass


# ---- API ----
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
ENV_KEY_NAME = "YOUTUBE_API_KEY"

# YouTube Data API 배치 한도 (videos.list / channels.list 는 id 를 최대 50개까지 묶어서 호출 가능)
BATCH_SIZE = 50

# ---- 기본값 (CLI 로 덮어쓸 수 있음) ----
DEFAULT_MULTIPLIER = 4.0          # 아웃라이어 배수 임계값 (영상 조회수 >= 채널 평균 x N)
DEFAULT_ORDER = "relevance"       # search.list 정렬 (relevance | viewCount | date ...)
DEFAULT_MAX_SEARCH = 150          # 검색으로 모을 후보 영상 수
DEFAULT_RECENT = 30               # 채널 평균 산정에 쓸 최근 영상 수
DEFAULT_FORMAT = "all"            # short | long | all
DEFAULT_OUTPUT_DIR = "."

# ---- 분석 상수 ----
SHORTS_MAX_SECONDS = 60           # 이 이하이면 숏폼으로 간주
MIN_SAMPLE_FOR_CONFIDENCE = 5     # 형식별 비교 표본이 이보다 적으면 신뢰도 낮음 표시

# 구독자 규모 구간 (소/중/대)
SUBSCRIBER_TIERS = [
    ("소형 (<1만)", 0, 10_000),
    ("중형 (1만~10만)", 10_000, 100_000),
    ("대형 (10만~100만)", 100_000, 1_000_000),
    ("메가 (100만+)", 1_000_000, float("inf")),
]


def get_api_key() -> str:
    """API 키를 반환. 없으면 안내 메시지와 함께 예외."""
    key = os.getenv(ENV_KEY_NAME, "").strip()
    if not key:
        raise RuntimeError(
            f"환경변수 {ENV_KEY_NAME} 가 설정되지 않았습니다.\n"
            f"  - 방법 1) export {ENV_KEY_NAME}=발급받은_키\n"
            f"  - 방법 2) youtube-references/.env 파일에 {ENV_KEY_NAME}=발급받은_키 저장\n"
            f"키 발급 방법은 README.md 를 참고하세요."
        )
    return key
