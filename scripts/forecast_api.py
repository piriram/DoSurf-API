import os
import json
import time
import math
import datetime
from urllib.parse import urlencode, unquote

import requests

# -------- API & 설정 --------
VILAGE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
BASE_TIMES = [23, 20, 17, 14, 11, 8, 5, 2]

# 프로젝트 루트 경로
ROOT_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, os.pardir)))
SECRETS_PATH = os.path.join(ROOT_DIR, "secrets", "secrets.json")

def _load_api_key():
    """
    secrets.json 구조:
    {
      "API_KEY": "...."   # 퍼센트 인코딩된 키(%2B, %3D 등)
    }
    퍼센트 인코딩된 키를 unquote 해서 사용해야 '이중 인코딩' 문제를 피할 수 있음.
    """
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        secrets = json.load(f)
    raw = secrets["API_KEY"]
    return unquote(raw)

SERVICE_KEY = _load_api_key()

# -------- 좌표 변환 --------
def latlon_to_xy(lat, lon):
    """
    위경도 -> 기상청 격자 좌표 변환 (LCC)
    """
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

# -------- 발표시각 계산 --------
def pick_latest_basetime(now=None):
    if now is None:
        now = datetime.datetime.now()
    hour = now.hour
    for h in BASE_TIMES:
        if hour >= h:
            return now.strftime("%Y%m%d"), f"{h:02d}00"
    y = now - datetime.timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"

def prev_basetime(base_date, base_time):
    h = int(base_time[:2])
    idx = BASE_TIMES.index(h)
    if idx == len(BASE_TIMES) - 1:
        d = datetime.datetime.strptime(base_date, "%Y%m%d") - datetime.timedelta(days=1)
        return d.strftime("%Y%m%d"), "2300"
    return base_date, f"{BASE_TIMES[idx+1]:02d}00"

# -------- API 요청 --------
def request_vilage(base_date, base_time, nx, ny):
    """
    - secrets.json의 API_KEY는 퍼센트 인코딩된 값일 수 있으므로
      unquote 한 SERVICE_KEY를 그대로 넘긴다.
    - requests가 params를 다시 인코딩하므로 SERVICE_KEY는 '원문'이어야 함.
    """
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
    r = requests.get(VILAGE_URL, params=params, timeout=20)

    # 디버그용 URL (키 마스킹)
    dbg = dict(params)
    dbg["serviceKey"] = "***"
    print(f"  ↳ GET {VILAGE_URL}?{urlencode(dbg)} -> {r.status_code}")

    try:
        return r.json(), None
    except Exception:
        return None, r.text[:400]

def fetch_items_with_fallback(nx, ny, max_rollback=5, sleep_sec=0.4):
    base_date, base_time = pick_latest_basetime()
    for attempt in range(1, max_rollback + 1):
        print(f"[TRY {attempt}] base_date={base_date}, base_time={base_time}, nx,ny={nx},{ny}")
        data, raw_err = request_vilage(base_date, base_time, nx, ny)

        if data:
            header = data.get("response", {}).get("header", {})
            body = data.get("response", {}).get("body", {})
            code = header.get("resultCode")
            msg = header.get("resultMsg")
            if code == "00" and "items" in body and "item" in body["items"]:
                items = body["items"]["item"]
                print(f"   ✔ resultCode=00, items={len(items)}")
                return items, base_date, base_time
            else:
                print(f"   ⚠ resultCode={code}, resultMsg={msg}")
        else:
            print(f"   ⚠ Non-JSON response: {raw_err}")

        base_date, base_time = prev_basetime(base_date, base_time)
        time.sleep(sleep_sec)

    return None, None, None
