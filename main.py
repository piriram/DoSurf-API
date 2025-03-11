# # main.py
# import datetime
# import os, json

# from scripts.forecast_api import fetch_items_with_fallback, latlon_to_xy
# from scripts.open_meteo import fetch_marine
# from scripts.storage import save_forecasts_merged

# ISSUE_HOURS = {2, 5, 8, 11, 14, 17, 20, 23}  # ← 발표시각만 허용

# def load_locations():
#     base_dir = os.path.dirname(__file__)
#     path = os.path.join(base_dir, "scripts", "locations.json")
#     with open(path, "r", encoding="utf-8") as f:
#         return json.load(f)

# def main():
#     locations = load_locations()
#     end_dt = datetime.datetime.now() + datetime.timedelta(days=4)

#     for loc in locations:
#         nx, ny = latlon_to_xy(float(loc["lat"]), float(loc["lon"]))
#         print(f"\n🌊 {loc['region']} - {loc['beach']} → 격자 {nx},{ny}")

#         # --- KMA ---
#         items, used_date, used_time = fetch_items_with_fallback(nx, ny, max_rollback=6)
#         if not items:
#             print("   ❌ KMA 예보 없음")
#             continue

#         picked = []
#         for it in items:
#             dt = datetime.datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M")
#             if dt <= end_dt and dt.minute == 0 and dt.hour in ISSUE_HOURS:
#                 picked.append({
#                     "datetime": dt.isoformat(),
#                     "category": it["category"],
#                     "value": it["fcstValue"]
#                 })

#         # --- Open-Meteo (KST로 정렬) ---
#         marine = fetch_marine(float(loc["lat"]), float(loc["lon"]),
#                               timezone="Asia/Seoul", forecast_days=5)
#         marine = [m for m in marine
#                   if datetime.datetime.fromisoformat(m["datetime"]) <= end_dt]

#         # --- 병합 저장 (merge=True로 기존 필드 보존) ---
#         save_forecasts_merged(loc["region"], loc["beach"], picked, marine)

# if __name__ == "__main__":
#     main()
# main.py — Cloud Functions (Gen2) HTTP 함수
import datetime
from google.cloud import firestore

# GCF에서는 Application Default Credentials가 자동 제공됩니다.
db = firestore.Client()

def log_update_time(request):
    """
    Cloud Scheduler가 HTTP POST로 호출
    meta_updates (루트 컬렉션)에 현재 시간을 기록
    """
    now = datetime.datetime.now()
    doc_id = now.strftime("%Y%m%d%H%M%S")

    ref = db.collection("meta_updates").document(doc_id)
    ref.set({
        "timestamp": now,  # Firestore Timestamp로 저장됨
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "Cloud Scheduler test update"
    })

    return ("OK", 200)
