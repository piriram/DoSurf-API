# scripts/open_meteo.py
import datetime
import requests
from typing import List, Dict, Optional

# Open-Meteo Marine API 기본 URL
BASE_URL = "https://marine-api.open-meteo.com/v1/marine"

def fetch_marine(lat: float, lon: float, *,
                 timezone: str = "Asia/Seoul",
                 forecast_days: int = 5) -> List[Dict]:
    """
    Open-Meteo Marine API에서 해양 예보 데이터를 가져옴.
    
    반환 형식: 리스트[딕셔너리]
    각 원소는 다음 필드를 포함:
      - datetime: ISO 형식 문자열 (예: "2025-09-25T12:00:00")
      - om_wave_height: 파고 (m)
      - om_wave_direction: 파향 (deg, 0~360)
      - sea_surface_temperature: 수온 (°C)
      - source: 데이터 출처 (여기서는 "open-meteo")
    """

    # API 요청 파라미터
    params = {
        "latitude": lat,        # 위도
        "longitude": lon,       # 경도
        "hourly": ",".join([    # 시간별로 가져올 항목 지정
            "wave_height",              # 파고 (m)
            "wave_direction",           # 파향 (deg)
            "sea_surface_temperature",  # 해수면 온도 (°C)
        ]),
        "timezone": timezone,           # 시간대 (기본: 서울)
        "forecast_days": forecast_days, # 예보 일수 (최대 8일)
        "cell_selection": "sea",        # 바다 격자(cell) 우선 선택
    }

    # API 호출
    r = requests.get(BASE_URL, params=params, timeout=20)
    r.raise_for_status()  # HTTP 에러 발생 시 예외 던짐
    data = r.json()       # JSON 파싱

    # 응답에서 hourly 데이터 추출
    hourly = data.get("hourly", {})
    times = hourly.get("time") or []                       # 시간 (ISO8601 문자열)
    wh = hourly.get("wave_height") or []                   # 파고 리스트
    wd = hourly.get("wave_direction") or []                # 파향 리스트
    sst = hourly.get("sea_surface_temperature") or []      # 수온 리스트

    # 결과를 담을 리스트
    out = []
    for t, h, d, temp in zip(times, wh, wd, sst):
        # t: "YYYY-MM-DDTHH:MM" 형식
        # Firestore에 저장할 때는 datetime.fromisoformat()으로 변환해서 timestamp 사용 가능
        out.append({
            "om_datetime": f"{t}:00",  # 원래가 "YYYY-MM-DDTHH:MM", 분 단위 맞추려고 ":00" 붙임
            "om_wave_height": float(h) if h is not None else None,        # 파고 (m)
            "om_wave_direction": float(d) if d is not None else None,     # 파향 (deg)
            "om_sea_surface_temperature": float(temp) if temp is not None else None,  # 수온 (°C)
            "om_source": "open-meteo"  # 데이터 출처 표시
        })

    return out
