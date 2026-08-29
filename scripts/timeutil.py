# scripts/timeutil.py
"""
시간대 유틸리티

Cloud Run 컨테이너는 UTC로 동작하지만 우리가 다루는 예보 시각은 전부 KST다:
  - 기상청 단기예보의 fcstDate/fcstTime → KST (naive)
  - Open-Meteo는 timezone=Asia/Seoul로 요청 → KST (naive)

따라서 예보 시각을 필터링할 때 datetime.now()를 그대로 쓰면 9시간 어긋난다.
naive KST 기준 '지금'이 필요할 때는 kst_naive_now()를 쓸 것.
"""
import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def kst_now():
    """timezone이 붙은 현재 한국 시각"""
    return datetime.datetime.now(tz=KST)


def kst_naive_now():
    """
    timezone 정보를 뗀 현재 한국 시각.

    KMA/Open-Meteo가 주는 naive KST 예보 시각과 직접 비교하기 위한 값이다.
    """
    return datetime.datetime.now(tz=KST).replace(tzinfo=None)
