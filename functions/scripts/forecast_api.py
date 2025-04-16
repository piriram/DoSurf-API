import os
import json
import time
import math
import datetime
import requests

try:
    from .config import get_kma_retry_count, get_kma_retry_delay
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False

VILAGE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
BASE_TIMES = [23, 20, 17, 14, 11, 8, 5, 2]

def _load_api_key():
    """환경 변수에서 API_KEY 읽기 (Cloud Run용)"""
    api_key = os.environ.get('KMA_API_KEY')
    if api_key:
        print("✅ API_KEY loaded from environment")
        return api_key
    
    # 환경 변수 없으면 에러
    raise ValueError("❌ KMA_API_KEY environment variable not found")

AUTH_KEY = _load_api_key()

def latlon_to_xy(lat, lon):
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

def request_vilage(base_date, base_time, nx, ny):
    params = {
        "authKey": AUTH_KEY,
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
        return None, "타임아웃"
    except Exception as e:
        return None, f"에러: {str(e)}"

def fetch_items_with_fallback(nx, ny, max_rollback=None, sleep_sec=None):
    if max_rollback is None:
        max_rollback = 5 if not CONFIG_AVAILABLE else get_kma_retry_count()
    if sleep_sec is None:
        sleep_sec = 0.4 if not CONFIG_AVAILABLE else get_kma_retry_delay()
    if max_rollback == 0:
        max_rollback = 1
    
    base_date, base_time = pick_latest_basetime()
    
    for attempt in range(1, max_rollback + 1):
        data, raw_err = request_vilage(base_date, base_time, nx, ny)
        if data is None:
            print(f"   ⚠ {raw_err}")
            if attempt >= max_rollback:
                break
            base_date, base_time = prev_basetime(base_date, base_time)
            if sleep_sec > 0:
                time.sleep(sleep_sec)
            continue

        header = data.get("response", {}).get("header", {})
        body = data.get("response", {}).get("body", {})
        code = header.get("resultCode", "99")
        
        if code == "00" and "items" in body and "item" in body["items"]:
            items = body["items"]["item"]
            print(f"   ✔ resultCode=00, items={len(items)}")
            return items, base_date, base_time
        
        print(f"   ⚠ resultCode={code}")
        if attempt >= max_rollback:
            break
        base_date, base_time = prev_basetime(base_date, base_time)
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    
    print(f"   ❌ 실패")
    return None, None, None
