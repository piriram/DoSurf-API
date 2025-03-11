import requests, datetime, math, time
from urllib.parse import urlencode

API_KEY = "bRoGZNlBK4zuN6yB3SicHChMpZJZSq3Zsi7ZaDKRROgMia0fvxtkKq2gvEbsHmq6oY9+RIYNE0MjiPiE6PRkaQ=="
VILAGE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
BASE_TIMES = [23, 20, 17, 14, 11, 8, 5, 2]

def latlon_to_xy(lat, lon):
    """위경도 → 격자 변환"""
    RE, GRID = 6371.00877, 5.0
    SLAT1, SLAT2, OLON, OLAT = 30.0, 60.0, 126.0, 38.0
    XO, YO = 43, 136
    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1 = SLAT1 * DEGRAD; slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD;  olat = OLAT * DEGRAD
    sn = math.tan(math.pi*0.25 + slat2*0.5) / math.tan(math.pi*0.25 + slat1*0.5)
    sn = math.log(math.cos(slat1)/math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi*0.25 + slat1*0.5); sf = (sf**sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi*0.25 + olat*0.5); ro = (re*sf) / (ro**sn)
    ra = math.tan(math.pi*0.25 + lat*DEGRAD*0.5); ra = (re*sf) / (ra**sn)
    theta = (lon*DEGRAD - olon); 
    if theta > math.pi: theta -= 2.0*math.pi
    if theta < -math.pi: theta += 2.0*math.pi
    theta *= sn
    x = int(ra*math.sin(theta) + XO + 0.5)
    y = int(ro - ra*math.cos(theta) + YO + 0.5)
    return x, y

def pick_latest_basetime(now=None):
    """발표시각 계산"""
    if now is None: now = datetime.datetime.now()
    hour = now.hour
    for h in BASE_TIMES:
        if hour >= h: return now.strftime("%Y%m%d"), f"{h:02d}00"
    y = now - datetime.timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"

def prev_basetime(base_date, base_time):
    """이전 발표시각 계산"""
    h = int(base_time[:2]); idx = BASE_TIMES.index(h)
    if idx == len(BASE_TIMES) - 1:
        d = datetime.datetime.strptime(base_date, "%Y%m%d") - datetime.timedelta(days=1)
        return d.strftime("%Y%m%d"), "2300"
    return base_date, f"{BASE_TIMES[idx+1]:02d}00"

def request_vilage(base_date, base_time, nx, ny):
    """기상청 API 요청"""
    params = {
        "serviceKey": API_KEY,
        "numOfRows": 1000,
        "pageNo": 1,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx, "ny": ny,
    }
    r = requests.get(VILAGE_URL, params=params, timeout=20)
    url_dbg = VILAGE_URL + "?" + urlencode({**params, "serviceKey": "***"})
    print(f"  ↳ GET {url_dbg} -> {r.status_code}")

    try:
        j = r.json()
        return j, None
    except Exception:
        return None, r.text[:400]

def fetch_items_with_fallback(nx, ny, max_rollback=5):
    """기상청 데이터 가져오기 (실패 시 이전 시각으로 재시도)"""
    base_date, base_time = pick_latest_basetime()
    for attempt in range(1, max_rollback+1):
        print(f"[TRY {attempt}] base_date={base_date}, base_time={base_time}, nx,ny={nx},{ny}")
        data, raw_err = request_vilage(base_date, base_time, nx, ny)

        if data:
            header = data.get("response", {}).get("header", {})
            body = data.get("response", {}).get("body", {})
            code = header.get("resultCode")
            msg  = header.get("resultMsg")
            if code == "00" and "items" in body and "item" in body["items"]:
                items = body["items"]["item"]
                print(f"   ✔ resultCode=00, items={len(items)}")
                return items, base_date, base_time
            else:
                print(f"   ⚠ resultCode={code}, resultMsg={msg}")
        else:
            print(f"   ⚠ Non-JSON response: {raw_err}")

        base_date, base_time = prev_basetime(base_date, base_time)
        time.sleep(0.4)

    return None, None, None