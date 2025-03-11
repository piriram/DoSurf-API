# main.py
import datetime
import os
import json

from scripts.forecast_api import fetch_items_with_fallback, latlon_to_xy
from scripts.open_meteo import fetch_marine
from scripts.storage import save_forecasts_merged


def load_locations():
    """
    scripts/locations.json 파일을 읽어서
    [{"region": "제주", "beach": "중문해변", "lat": "33.24", "lon": "126.41"}, ...] 형태 반환
    """
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "scripts", "locations.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    # 저장할 예보의 범위 (현재 ~ 4일 후까지)
    locations = load_locations()
    end_dt = datetime.datetime.now() + datetime.timedelta(days=4)

    for loc in locations:
        nx, ny = latlon_to_xy(float(loc["lat"]), float(loc["lon"]))
        print(f"\n🌊 {loc['region']} - {loc['beach']} → 격자 {nx},{ny}")

        # --- 1) KMA 예보 가져오기 ---
        items, used_date, used_time = fetch_items_with_fallback(nx, ny, max_rollback=6)
        if not items:
            print("   ❌ KMA 예보 없음")
            continue

        picked = []
        for it in items:
            dt = datetime.datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M")
            if dt <= end_dt:
                picked.append({
                    "datetime": dt.isoformat(),
                    "category": it["category"],
                    "value": it["fcstValue"]
                })

        # --- 2) Open-Meteo 예보 가져오기 ---
        marine = fetch_marine(float(loc["lat"]), float(loc["lon"]),
                              timezone="Asia/Seoul", forecast_days=5)
        marine = [m for m in marine if datetime.datetime.fromisoformat(m["datetime"]) <= end_dt]

        # --- 3) Firestore에 병합 저장 ---
        save_forecasts_merged(loc["region"], loc["beach"], picked, marine)


if __name__ == "__main__":
    main()
