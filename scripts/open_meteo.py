# scripts/open_meteo.py
import math
import time

import requests
from typing import Dict, List, Optional, Tuple

try:
    from .config import (get_marine_model, get_marine_fallback_model,
                         get_marine_wave_variables, get_marine_aux_variables,
                         get_marine_peak_period_model,
                         get_marine_peak_period_variables,
                         get_open_meteo_retry_count, get_api_timeout)
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False

from .timeutil import kst_now

# Open-Meteo Marine API 기본 URL
BASE_URL = "https://marine-api.open-meteo.com/v1/marine"

# config.json을 못 읽을 때 쓰는 기본값
FALLBACK_WAVE_VARIABLES = [
    "wave_height", "wave_direction", "wave_period",
    "swell_wave_height", "swell_wave_direction", "swell_wave_period",
    "wind_wave_height", "wind_wave_direction", "wind_wave_period",
]
FALLBACK_AUX_VARIABLES = ["sea_surface_temperature", "sea_level_height_msl"]
FALLBACK_PEAK_PERIOD_MODEL = "ecmwf_wam025"
FALLBACK_PEAK_PERIOD_VARIABLES = ["wave_peak_period"]
DEFAULT_MODEL = "best_match"
DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 20

# 물리적으로 불가능한 값을 걸러내기 위한 범위
VALUE_RANGES = {
    "wave_height": (0.0, 30.0),
    "swell_wave_height": (0.0, 30.0),
    "wind_wave_height": (0.0, 30.0),
    "wave_period": (0.0, 30.0),
    "swell_wave_period": (0.0, 30.0),
    "wind_wave_period": (0.0, 30.0),
    "wave_direction": (0.0, 360.0),
    "swell_wave_direction": (0.0, 360.0),
    "wind_wave_direction": (0.0, 360.0),
    "wave_peak_period": (0.0, 30.0),
    "sea_surface_temperature": (-2.0, 40.0),
    "sea_level_height_msl": (-10.0, 10.0),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이의 대권 거리(km)"""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _series(hourly: Dict, name: str) -> List:
    """
    hourly 응답에서 변수 시계열을 꺼낸다.

    models 파라미터를 넘기면 Open-Meteo가 키에 모델명을 붙여서 준다
    (예: wave_height → wave_height_ecmwf_wam025). 둘 다 처리한다.
    """
    if name in hourly:
        return hourly[name] or []
    prefix = name + "_"
    for key in hourly:
        if key.startswith(prefix):
            return hourly[key] or []
    return []


def _num(value, name: str) -> Optional[float]:
    """숫자로 변환하고 범위를 벗어나면 None. 결측은 None 그대로 둔다."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    lo, hi = VALUE_RANGES.get(name, (float("-inf"), float("inf")))
    if v < lo or v > hi:
        return None
    return v


def _request(lat, lon, variables, model, timezone, forecast_days, timeout, retries):
    """
    Open-Meteo 호출. 네트워크 오류는 지수 백오프로 재시도한다.

    수집기는 3시간마다 무인으로 도는데, 일시적인 타임아웃 한 번에
    해당 해변이 통째로 빠지면 안 된다.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(variables),
        "timezone": timezone,
        "forecast_days": forecast_days,
        "cell_selection": "sea",   # 해변 좌표는 대개 육지 격자라 바다 격자로 옮겨야 한다
    }
    if model and model != DEFAULT_MODEL:
        params["models"] = model

    last_error = None
    for attempt in range(max(1, retries)):
        try:
            r = requests.get(BASE_URL, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                # 잘못된 모델명 같은 요청 오류는 재시도해도 같다
                raise RuntimeError(f"Open-Meteo 오류({model}): {data.get('reason', 'unknown')}")
            return data
        except RuntimeError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < max(1, retries) - 1:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Open-Meteo 호출 실패({model}): {last_error}")


def _extract(data, variables):
    """응답에서 {변수: 시계열} 과 시각 목록을 뽑는다. 값 검증도 여기서."""
    hourly = data.get("hourly", {})
    times = _series(hourly, "time")
    series = {}
    for name in variables:
        raw = _series(hourly, name)
        series[name] = [_num(v, name) for v in raw]
    return times, series


def _has_data(values: List) -> bool:
    return any(v is not None for v in values)


def fetch_marine(lat: float, lon: float, *,
                 timezone: str = "Asia/Seoul",
                 forecast_days: int = 5,
                 region: Optional[str] = None,
                 model: Optional[str] = None,
                 timeout: Optional[int] = None,
                 retries: Optional[int] = None) -> Tuple[List[Dict], Dict]:
    """
    Open-Meteo Marine API에서 해양 예보를 가져온다.

    반환: (hours, meta)

    hours: 시각별 딕셔너리 리스트. 각 원소는
      - om_datetime: "YYYY-MM-DDTHH:MM:SS" (naive KST)
      - wave_height / wave_direction / wave_period
      - swell_wave_height / swell_wave_direction / swell_wave_period
      - wind_wave_height / wind_wave_direction / wind_wave_period
      - wave_peak_period  (첨두주기)
      - sea_surface_temperature
      - sea_level_height_msl  (조석, 평균해수면 기준)
      결측이거나 범위를 벗어난 값은 None으로 남긴다.

    meta: 어느 모델·어느 격자에서 받았는지 추적하기 위한 정보.
      model, grid_lat, grid_lon, snap_distance_km, fetched_at,
      fallback_model, fallback_fields (폴백에서 채운 필드 목록)

    ── 왜 세 번 호출하나 ──
    Open-Meteo는 models 파라미터를 지정하면 수온·조석을 응답에서 뺀다.
    ecmwf_wam025는 스웰 분해(swell_*, wind_wave_*)도 주지 않는다.
    그래서 지역 모델로 파랑 변수를 받고, 폴백 모델(best_match)로 한 번 더 호출해
    빠진 필드를 채운다. 어느 필드를 폴백에서 가져왔는지는 meta에 남긴다 —
    출처가 섞인 것을 나중에 알 수 있어야 하기 때문이다.

    세 번째는 첨두주기다. wave_peak_period 는 ecmwf 계열만 주고 폴백(best_match)
    으로도 안 온다. 그런데 Windfinder·서핑 앱이 화면에 쓰는 파주기가 첨두주기라
    (wave_period 는 평균주기 계열) 이 값이 없으면 우리 파주기는 구조적으로 낮게
    나온다 — 제주 대조에서 MAE 2.6~3.1초 대 1.08초였다.
    그래서 전용 모델을 한 번 더 부른다. 어느 모델에서 왔는지는
    meta.peak_period_model 에 남는다.

    지역 모델이 폴백 모델이나 첨두주기 모델과 같으면 그만큼 호출이 줄어든다.

    지역별 모델 선택 근거는 docs/marine-data-audit.md 「2차 검증」 참조.
    """
    if model is None:
        model = get_marine_model(region) if CONFIG_AVAILABLE else DEFAULT_MODEL
    fallback_model = get_marine_fallback_model() if CONFIG_AVAILABLE else DEFAULT_MODEL
    wave_vars = get_marine_wave_variables() if CONFIG_AVAILABLE else FALLBACK_WAVE_VARIABLES
    aux_vars = get_marine_aux_variables() if CONFIG_AVAILABLE else FALLBACK_AUX_VARIABLES
    peak_model = (get_marine_peak_period_model() if CONFIG_AVAILABLE
                  else FALLBACK_PEAK_PERIOD_MODEL)
    peak_vars = (get_marine_peak_period_variables() if CONFIG_AVAILABLE
                 else FALLBACK_PEAK_PERIOD_VARIABLES)
    all_vars = list(wave_vars) + list(aux_vars) + list(peak_vars)
    if timeout is None:
        timeout = get_api_timeout() if CONFIG_AVAILABLE else DEFAULT_TIMEOUT
    if retries is None:
        retries = get_open_meteo_retry_count() if CONFIG_AVAILABLE else DEFAULT_RETRIES

    # 지역 모델이 폴백과 같으면 보조 변수까지 한 번에 받을 수 있다
    single_call = (model == fallback_model)
    # 지역 모델이 이미 첨두주기를 주는 모델이면 따로 부르지 않는다
    peak_in_primary = (model == peak_model)

    primary_vars = list(wave_vars)
    if single_call:
        primary_vars += list(aux_vars)
    if peak_in_primary:
        primary_vars += list(peak_vars)
    primary = _request(lat, lon, primary_vars, model, timezone,
                       forecast_days, timeout, retries)
    times, series = _extract(primary, primary_vars)

    grid_lat, grid_lon = primary.get("latitude"), primary.get("longitude")
    meta = {
        "model": model,
        "grid_lat": grid_lat,
        "grid_lon": grid_lon,
        "snap_distance_km": (
            round(haversine_km(lat, lon, grid_lat, grid_lon), 2)
            if grid_lat is not None and grid_lon is not None else None
        ),
        "fetched_at": kst_now(),
        "fallback_model": None,
        "fallback_fields": [],
        "peak_period_model": model if peak_in_primary else None,
        "peak_period_fields": list(peak_vars) if peak_in_primary else [],
    }

    if not single_call:
        # 지역 모델이 안 주는 필드를 폴백 모델로 채운다.
        missing = [v for v in wave_vars if not _has_data(series.get(v, []))]
        needed = list(aux_vars) + missing
        try:
            aux = _request(lat, lon, needed, fallback_model, timezone,
                           forecast_days, timeout, retries)
            aux_times, aux_series = _extract(aux, needed)
            # 시각 축이 어긋나면 채우지 않는다 (잘못 정렬된 값보다 결측이 낫다)
            if aux_times == times:
                for name in needed:
                    values = aux_series.get(name, [])
                    if _has_data(values):
                        series[name] = values
                        meta["fallback_fields"].append(name)
                meta["fallback_model"] = fallback_model
                meta["fallback_grid_lat"] = aux.get("latitude")
                meta["fallback_grid_lon"] = aux.get("longitude")
        except Exception as exc:
            # 보조 변수가 없어도 파고는 살아 있으므로 수집을 중단하지는 않는다
            print(f"   ⚠ 보조 변수 수집 실패({fallback_model}): {exc}")

    if not peak_in_primary and peak_vars:
        # ── 세 번째 호출: 첨두주기 ──
        # 첨두주기는 ecmwf 계열만 준다. 폴백(best_match)으로도 안 오기 때문에
        # 수온·조석 호출에 얹을 수 없고 전용 모델을 따로 불러야 한다.
        # 왜 첨두주기가 필요한지는 config.json 의 peak_period_why 참조.
        try:
            peak = _request(lat, lon, peak_vars, peak_model, timezone,
                            forecast_days, timeout, retries)
            peak_times, peak_series = _extract(peak, peak_vars)
            # 시각 축이 어긋나면 채우지 않는다 (잘못 정렬된 값보다 결측이 낫다)
            if peak_times == times:
                for name in peak_vars:
                    values = peak_series.get(name, [])
                    if _has_data(values):
                        series[name] = values
                        meta["peak_period_fields"].append(name)
                if meta["peak_period_fields"]:
                    meta["peak_period_model"] = peak_model
                    meta["peak_grid_lat"] = peak.get("latitude")
                    meta["peak_grid_lon"] = peak.get("longitude")
        except Exception as exc:
            # 첨두주기가 없어도 파고·평균주기는 살아 있다
            print(f"   ⚠ 첨두주기 수집 실패({peak_model}): {exc}")

    out = []
    for i, t in enumerate(times):
        # t는 "YYYY-MM-DDTHH:MM" 형식이라 초 단위를 붙여 맞춘다
        row = {"om_datetime": f"{t}:00" if len(t) == 16 else t}
        for name in all_vars:
            values = series.get(name) or []
            row[name] = values[i] if i < len(values) else None
        out.append(row)

    return out, meta
