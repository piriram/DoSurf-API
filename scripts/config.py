# scripts/config.py
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config.json")

# config.json에 marine 설정이 없을 때 쓰는 기본값.
# 파랑 변수는 지역별 모델에서, 보조 변수는 폴백 모델에서 받는다 —
# Open-Meteo가 models를 지정하면 수온·조석을 응답에서 빼기 때문이다.
DEFAULT_WAVE_VARIABLES = [
    "wave_height", "wave_direction", "wave_period",
    "swell_wave_height", "swell_wave_direction", "swell_wave_period",
    "wind_wave_height", "wind_wave_direction", "wind_wave_period",
]
DEFAULT_AUX_VARIABLES = ["sea_surface_temperature", "sea_level_height_msl"]
DEFAULT_PEAK_PERIOD_MODEL = "ecmwf_wam025"
DEFAULT_PEAK_PERIOD_VARIABLES = ["wave_peak_period"]

def load_config():
    """config.json 파일 로드"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # 기본값 반환
        return {
            "api": {
                "kma_retry_count": 5,
                "kma_retry_delay_seconds": 0.4,
                "open_meteo_retry_count": 3,
                "timeout_seconds": 20
            },
            "schedule": {
                "collect_interval_hours": 3,
                "forecast_days": 4
            },
            "storage": {
                "allowed_hours": [0, 3, 6, 9, 12, 15, 18, 21]
            },
            "marine": {
                "default_model": "best_match",
                "fallback_model": "best_match",
                "region_models": {},
                "wave_variables": DEFAULT_WAVE_VARIABLES,
                "aux_variables": DEFAULT_AUX_VARIABLES
            }
        }

# 전역 설정 객체
config = load_config()

# 편의 함수들
def get_kma_retry_count():
    """기상청 API 재시도 횟수"""
    return config["api"]["kma_retry_count"]

def get_kma_retry_delay():
    """기상청 API 재시도 대기 시간(초)"""
    return config["api"]["kma_retry_delay_seconds"]

def get_forecast_days():
    """예보 수집 일수"""
    return config["schedule"]["forecast_days"]

def get_allowed_hours():
    """저장 허용 시간"""
    return config["storage"]["allowed_hours"]


def get_open_meteo_retry_count():
    """Open-Meteo 재시도 횟수"""
    return config["api"].get("open_meteo_retry_count", 3)


def get_api_timeout():
    """외부 API 요청 타임아웃(초)"""
    return config["api"].get("timeout_seconds", 20)


# -------------------------
# 해양 예보 모델 설정
# -------------------------
# 지역마다 Windfinder에 가장 가까운 파랑 모델이 다르다.
# 근거와 측정값은 docs/marine-data-audit.md 「2차 검증」 참조.

def _marine_config():
    return config.get("marine", {})


def get_marine_model(region=None):
    """
    지역에 사용할 Open-Meteo 파랑 모델 이름.

    region_models에 지정이 없으면 default_model을 쓴다.
    모델은 코드가 아니라 config.json에서만 바꿀 것 —
    근거가 며칠치 표본이라 재조정 가능성이 높다.
    """
    marine = _marine_config()
    default = marine.get("default_model", "best_match")
    if not region:
        return default
    return marine.get("region_models", {}).get(region, default)


def get_marine_fallback_model():
    """
    보조 변수(수온·조석)를 받아올 모델.

    Open-Meteo는 models를 지정하면 수온·조석을 응답에서 뺀다.
    그래서 지역 모델과 별개로 한 번 더 호출해 빠진 필드를 채운다.
    """
    return _marine_config().get("fallback_model", "best_match")


def get_marine_wave_variables():
    """지역별 파랑 모델에서 받을 항목"""
    return _marine_config().get("wave_variables", DEFAULT_WAVE_VARIABLES)


def get_marine_aux_variables():
    """폴백 모델에서 받을 보조 항목 (수온·조석)"""
    return _marine_config().get("aux_variables", DEFAULT_AUX_VARIABLES)


def get_marine_peak_period_model():
    """
    첨두주기를 받아올 모델.

    첨두주기(wave_peak_period)는 ecmwf_wam025/ecmwf_wam만 준다. 나머지 모델은
    변수를 받아주기는 하되 값을 전부 None으로 돌려준다(2026-08-30 실측).
    fallback_model(best_match)로도 못 받으므로 전용 모델을 따로 호출한다.
    """
    return _marine_config().get("peak_period_model", DEFAULT_PEAK_PERIOD_MODEL)


def get_marine_peak_period_variables():
    """첨두주기 모델에서 받을 항목"""
    return _marine_config().get("peak_period_variables", DEFAULT_PEAK_PERIOD_VARIABLES)
