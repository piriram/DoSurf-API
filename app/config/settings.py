"""Runtime settings and constants."""

# 설정 로드
try:
    from scripts.config import get_forecast_days, get_allowed_hours

    ISSUE_HOURS = set(get_allowed_hours())
    FORECAST_DAYS = get_forecast_days()
except ImportError:
    ISSUE_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}
    FORECAST_DAYS = 3
    print("⚠ config.py를 찾을 수 없습니다. 기본 설정을 사용합니다.")

# 예상 데이터 크기 (단기예보 3일 기준)
EXPECTED_ITEM_COUNT = 72 * 11  # 72시간 * 11개 카테고리 = 792개
EXPECTED_FORECAST_HOURS = 28   # 28개 시간대 (3일 * 8시간 + 4시간)
