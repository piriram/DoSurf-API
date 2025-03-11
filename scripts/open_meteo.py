# scripts/open_meteo.py
import datetime
import requests
from typing import List, Dict, Optional

BASE_URL = "https://marine-api.open-meteo.com/v1/marine"

def fetch_marine(lat: float, lon: float, *,
                 timezone: str = "Asia/Seoul",
                 forecast_days: int = 5) -> List[Dict]:
    """
    Open-Meteo Marine API에서 파도/수온 시간별 예보를 가져와
    [{datetime, om_wave_height, om_wave_direction, sea_surface_temperature}] 리스트로 반환.
    datetime은 ISO 문자열.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "wave_height",
            "wave_direction",
            "sea_surface_temperature",
        ]),
        "timezone": timezone,
        "forecast_days": forecast_days,  # 최대 8일
        # 근해 격자 우선: 바다 격자 선호
        "cell_selection": "sea",
    }

    r = requests.get(BASE_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time") or []
    wh = hourly.get("wave_height") or []
    wd = hourly.get("wave_direction") or []
    sst = hourly.get("sea_surface_temperature") or []

    out = []
    for t, h, d, temp in zip(times, wh, wd, sst):
        # t는 "YYYY-MM-DDTHH:MM"
        # Firestore에 저장 시 fromisoformat으로 파싱해서 timestamp로 쓰면 좋음
        out.append({
            "datetime": f"{t}:00",  # 분 해상도 맞추기 위해 ":00" 붙임
            "om_wave_height": float(h) if h is not None else None,        # meters
            "om_wave_direction": float(d) if d is not None else None,     # degrees (0~360)
            "sea_surface_temperature": float(temp) if temp is not None else None,  # °C
            "source": "open-meteo"
        })
    return out
