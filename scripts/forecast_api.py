# scripts/forecast_api.py
import os
import json
import time
import math
import datetime
from urllib.parse import urlencode, unquote
import requests

# config.py에서 설정 가져오기
try:
    from .config import get_kma_retry_count, get_kma_retry_delay
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    print("⚠ config.py를 찾을 수 없습니다. 기본 재시도 설정을 사용합니다.")

# -------- API & 설정 --------
VILAGE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
BASE_TIMES = [23, 20, 17, 14, 11, 8, 5, 2]
ROOT_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, os.pardir)))
SECRETS_PATH = os.path.join(ROOT_DIR, "secrets", "secrets.json")

# -------- 에러 코드 분류 --------
# 재시도 불가능한 에러 (설정 문제, 권한 문제)
FATAL_ERRORS = {
    "10": "잘못된 요청 파라메터",
    "11": "필수 파라메터 없음",
    "12": "해당 서비스 없음/폐기",
    "20": "서비스 접근 거부",
    "30": "등록되지 않은 서비스키",
    "31": "기한 만료된 서비스키",
    "32": "등록되지 않은 IP",
    "33": "서명되지 않은 호출"
}

# 재시도 가능한 에러 (일시적 문제)
RETRYABLE_ERRORS = {
    "01": "어플리케이션 에러",
    "02": "데이터베이스 에러",
    "04": "HTTP 에러",
    "05": "서비스 연결실패",
    "21": "일시적으로 사용 불가한 서비스키",
    "22": "서비스 요청 제한 초과",
    "99": "기타 에러"
}

# 특별 처리 에러
SPECIAL_ERRORS = {
    "03": "데이터 없음"  # 정상이지만 데이터가 없는 경우
}


def _load_api_key():
    """secrets.json 파일에서 API_KEY를 읽어옴"""
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        secrets = json.load(f)
    raw = secrets["API_KEY"]
    return unquote(raw)

SERVICE_KEY = _load_api_key()


def latlon_to_xy(lat, lon):
    """위도(lat), 경도(lon) → 기상청 격자 좌표(nx, ny) 변환"""
    RE, GRID = 6371.00877, 5.0
    SLAT1, SLAT2, OLON, OLAT = 30.0, 60.0, 126.0, 38.0
    XO, YO = 43, 136
    DEGRAD = math.pi / 180.0

    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD
    sn = math.tan(math.pi*0.25 + slat2*0.5) / math.tan(math.pi*0.25 + slat1*0.5)
    sn = math.log(math.cos(slat1)/math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi*0.25 + slat1*0.5)
    sf = (sf**sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi*0.25 + olat*0.5)
    ro = (re*sf) / (ro**sn)
    ra = math.tan(math.pi*0.25 + lat*DEGRAD*0.5)
    ra = (re*sf) / (ra**sn)
    theta = (lon*DEGRAD - olon)
    if theta > math.pi:  theta -= 2.0*math.pi
    if theta < -math.pi: theta += 2.0*math.pi
    theta *= sn

    x = int(ra*math.sin(theta) + XO + 0.5)
    y = int(ro - ra*math.cos(theta) + YO + 0.5)
    return x, y


def pick_latest_basetime(now=None):
    """현재 시각을 기준으로 가장 최근 발표 시각 선택"""
    if now is None:
        now = datetime.datetime.now()
    hour = now.hour

    for h in BASE_TIMES:
        if hour >= h:
            return now.strftime("%Y%m%d"), f"{h:02d}00"

    y = now - datetime.timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def prev_basetime(base_date, base_time):
    """직전 발표 시각 계산"""
    h = int(base_time[:2])
    idx = BASE_TIMES.index(h)
    if idx == len(BASE_TIMES) - 1:
        d = datetime.datetime.strptime(base_date, "%Y%m%d") - datetime.timedelta(days=1)
        return d.strftime("%Y%m%d"), "2300"
    return base_date, f"{BASE_TIMES[idx+1]:02d}00"


def is_fatal_error(result_code):
    """재시도 불가능한 에러인지 확인"""
    return result_code in FATAL_ERRORS


def is_retryable_error(result_code):
    """재시도 가능한 에러인지 확인"""
    return result_code in RETRYABLE_ERRORS


def get_error_description(result_code):
    """에러 코드에 대한 설명 반환"""
    if result_code in FATAL_ERRORS:
        return FATAL_ERRORS[result_code]
    elif result_code in RETRYABLE_ERRORS:
        return RETRYABLE_ERRORS[result_code]
    elif result_code in SPECIAL_ERRORS:
        return SPECIAL_ERRORS[result_code]
    else:
        return "알 수 없는 에러"


def request_vilage(base_date, base_time, nx, ny):
    """기상청 단기예보 API 요청"""
    params = {
        "serviceKey": SERVICE_KEY,
        "numOfRows": 1000,
        "pageNo": 1,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    
    try:
        r = requests.get(VILAGE_URL, params=params, timeout=20)
        return r.json(), None
    except requests.exceptions.Timeout:
        return None, "요청 시간 초과 (Timeout)"
    except requests.exceptions.ConnectionError:
        return None, "연결 실패 (Connection Error)"
    except Exception as e:
        return None, f"요청 실패: {str(e)}"


def fetch_items_with_fallback(nx, ny, max_rollback=None, sleep_sec=None):
    """
    좌표(nx, ny)에 대해 최신 발표시각부터 API 요청 시도
    - 에러 코드별 적절한 대응
    - 재시도 불가능한 에러는 즉시 중단
    """
    # 설정 파일에서 기본값 가져오기
    if max_rollback is None:
        if CONFIG_AVAILABLE:
            max_rollback = get_kma_retry_count()
        else:
            max_rollback = 5
    
    if sleep_sec is None:
        if CONFIG_AVAILABLE:
            sleep_sec = get_kma_retry_delay()
        else:
            sleep_sec = 0.4
    
    if max_rollback == 0:
        max_rollback = 1
    
    base_date, base_time = pick_latest_basetime()
    
    for attempt in range(1, max_rollback + 1):
        data, raw_err = request_vilage(base_date, base_time, nx, ny)

        # JSON 파싱 실패 (서버 응답 없음)
        if data is None:
            print(f"   ⚠ {raw_err}")
            if attempt >= max_rollback:
                break
            base_date, base_time = prev_basetime(base_date, base_time)
            if sleep_sec > 0:
                time.sleep(sleep_sec)
            continue

        # API 응답 파싱
        header = data.get("response", {}).get("header", {})
        body = data.get("response", {}).get("body", {})
        code = header.get("resultCode", "99")
        msg = header.get("resultMsg", "Unknown")

        # ===== 성공 =====
        if code == "00" and "items" in body and "item" in body["items"]:
            items = body["items"]["item"]
            print(f"   ✔ resultCode=00, items={len(items)}")
            return items, base_date, base_time
        
        # ===== 데이터 없음 (특별 처리) =====
        if code == "03":
            print(f"   ℹ️ 데이터 없음 (해당 시간대 예보 미발표)")
            if attempt >= max_rollback:
                break
            base_date, base_time = prev_basetime(base_date, base_time)
            if sleep_sec > 0:
                time.sleep(sleep_sec)
            continue

        # ===== 치명적 에러 (재시도 불가) =====
        if is_fatal_error(code):
            error_desc = get_error_description(code)
            print(f"   🚫 FATAL ERROR [{code}]: {error_desc}")
            print(f"   ⚠️ 설정 문제로 재시도 불가능. 즉시 중단합니다.")
            if code in ["30", "31"]:
                print(f"   💡 secrets.json의 API_KEY를 확인하세요.")
            elif code == "32":
                print(f"   💡 공공데이터포털에서 IP 등록을 확인하세요.")
            return None, None, None

        # ===== 재시도 가능한 에러 =====
        if is_retryable_error(code):
            error_desc = get_error_description(code)
            print(f"   ⚠ 재시도 가능 [{code}]: {error_desc} (시도 {attempt}/{max_rollback})")
            
            # 특별 처리: 요청 제한 초과는 더 오래 대기
            if code == "22":
                print(f"   ⏳ 요청 제한 초과. 5초 대기 후 재시도...")
                time.sleep(5)
            
            if attempt >= max_rollback:
                break
            base_date, base_time = prev_basetime(base_date, base_time)
            if sleep_sec > 0:
                time.sleep(sleep_sec)
            continue

        # ===== 알 수 없는 에러 =====
        print(f"   ⚠ 알 수 없는 에러 [{code}]: {msg}")
        if attempt >= max_rollback:
            break
        base_date, base_time = prev_basetime(base_date, base_time)
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    # 모든 시도 실패 시
    print(f"   ❌ {max_rollback}번 시도 후 실패")
    return None, None, None