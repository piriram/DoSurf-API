import os
import json
import time
import math
import datetime
from urllib.parse import urlencode, unquote
import requests

# -------- API & 설정 --------
# 기상청 단기예보 API URL
VILAGE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

# API에서 제공하는 발표 기준 시각 (하루 8번)
# 23시, 20시, 17시, 14시, 11시, 8시, 5시, 2시
BASE_TIMES = [23, 20, 17, 14, 11, 8, 5, 2]

# 프로젝트 루트 경로 계산
ROOT_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, os.pardir)))
# secrets.json 위치 (API 키 저장)
SECRETS_PATH = os.path.join(ROOT_DIR, "secrets", "secrets.json")


def _load_api_key():
    """
    secrets.json 파일에서 API_KEY를 읽어옴.

    secrets.json 구조:
    {
      "API_KEY": "...."   # 퍼센트 인코딩된 키 (%2B, %3D 등)
    }

    퍼센트 인코딩된 문자열을 unquote()로 원래 키로 변환해야
    '이중 인코딩' 문제를 피할 수 있음.
    """
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        secrets = json.load(f)
    raw = secrets["API_KEY"]
    return unquote(raw)  # 퍼센트 인코딩 제거

# API 요청에 사용할 서비스 키 (원래 형태)
SERVICE_KEY = _load_api_key()


# -------- 좌표 변환 --------
def latlon_to_xy(lat, lon):
    """
    위도(lat), 경도(lon) → 기상청 격자 좌표(nx, ny) 변환
    (Lambert Conformal Conic 투영법 사용)
    """
    RE, GRID = 6371.00877, 5.0  # 지구 반경(km), 격자 간격(km)
    SLAT1, SLAT2, OLON, OLAT = 30.0, 60.0, 126.0, 38.0  # 표준위도, 기준 경위도
    XO, YO = 43, 136  # 기준 좌표
    DEGRAD = math.pi / 180.0

    # 기본 계산 (투영법 수식)
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

    # 최종 격자 좌표
    x = int(ra*math.sin(theta) + XO + 0.5)
    y = int(ro - ra*math.cos(theta) + YO + 0.5)
    return x, y


# -------- 발표시각 계산 --------
def pick_latest_basetime(now=None):
    """
    현재 시각을 기준으로 가장 최근 발표 시각(base_time)을 선택.
    """
    if now is None:
        now = datetime.datetime.now()
    hour = now.hour

    # 현재 시각보다 같거나 작은 발표 기준 시각을 찾음
    for h in BASE_TIMES:
        if hour >= h:
            return now.strftime("%Y%m%d"), f"{h:02d}00"

    # 못 찾으면 전날 23시를 반환
    y = now - datetime.timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def prev_basetime(base_date, base_time):
    """
    직전 발표 시각(base_time)을 계산.
    예: 14:00 → 17:00, 02:00 → 전날 23:00
    """
    h = int(base_time[:2])
    idx = BASE_TIMES.index(h)
    if idx == len(BASE_TIMES) - 1:  # 마지막(02시)이면 전날 23시
        d = datetime.datetime.strptime(base_date, "%Y%m%d") - datetime.timedelta(days=1)
        return d.strftime("%Y%m%d"), "2300"
    return base_date, f"{BASE_TIMES[idx+1]:02d}00"


# -------- API 요청 --------
def request_vilage(base_date, base_time, nx, ny):
    """
    기상청 단기예보 API 요청.
    - secrets.json의 API_KEY는 퍼센트 인코딩된 값일 수 있음
    - unquote 한 SERVICE_KEY를 그대로 params에 넣어야 함
    """
    params = {
        "serviceKey": SERVICE_KEY,  # 원래 형태의 키
        "numOfRows": 1000,
        "pageNo": 1,
        "dataType": "JSON",  # JSON 형식 요청
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    r = requests.get(VILAGE_URL, params=params, timeout=20)

    # 디버그용 URL 출력 (키는 마스킹 처리)
    dbg = dict(params)
    dbg["serviceKey"] = "***"
    # print(f"  ↳ GET {VILAGE_URL}?{urlencode(dbg)} -> {r.status_code}")

    # JSON 응답 반환, 실패 시 텍스트 일부 반환
    try:
        return r.json(), None
    except Exception:
        return None, r.text[:400]


def fetch_items_with_fallback(nx, ny, max_rollback=5, sleep_sec=0.4):
    """
    주어진 좌표(nx, ny)에 대해 최신 발표시각부터 API 요청을 시도.
    - 실패하면 직전(base_time 이전) 발표시각으로 롤백
    - 최대 max_rollback 번 시도
    """
    base_date, base_time = pick_latest_basetime()
    for attempt in range(1, max_rollback + 1):
        # print(f"[TRY {attempt}] base_date={base_date}, base_time={base_time}, nx,ny={nx},{ny}")
        data, raw_err = request_vilage(base_date, base_time, nx, ny)

        if data:
            header = data.get("response", {}).get("header", {})
            body = data.get("response", {}).get("body", {})
            code = header.get("resultCode")
            msg = header.get("resultMsg")

            # 성공 조건: resultCode=00, items 존재
            if code == "00" and "items" in body and "item" in body["items"]:
                items = body["items"]["item"]
                print(f"   ✔ resultCode=00, items={len(items)}")
                return items, base_date, base_time
            else:
                print(f"   ⚠ resultCode={code}, resultMsg={msg}")
        else:
            print(f"   ⚠ Non-JSON response: {raw_err}")

        # 실패 시: 직전 발표시각으로 이동
        base_date, base_time = prev_basetime(base_date, base_time)
        time.sleep(sleep_sec)  # 잠시 대기 (API 호출 제한 방지)

    # 모든 시도 실패 시
    return None, None, None
