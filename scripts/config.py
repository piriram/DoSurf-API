# scripts/config.py
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config.json")

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