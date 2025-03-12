# main.py
import datetime
import os, json

from scripts.forecast_api import fetch_items_with_fallback, latlon_to_xy
from scripts.open_meteo import fetch_marine
from scripts.storage import save_forecasts_merged

# 기상청 단기예보는 특정 시간대(발표 시각)만 존재하므로,
# 허용 가능한 예보 발표 시각을 미리 정의
ISSUE_HOURS = {2, 5, 8, 11, 14, 17, 20, 23}

def load_locations():
    """
    scripts/locations.json 파일에서 위치 목록을 읽어오는 함수.
    각 위치는 region(지역), beach(해수욕장), lat/lon(위경도) 정보를 포함.
    """
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "scripts", "locations.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    # 예측 종료 시각: 지금부터 4일 뒤까지 데이터만 수집
    locations = load_locations()
    end_dt = datetime.datetime.now() + datetime.timedelta(days=4)

    for loc in locations:
        # 위경도 → 기상청 격자(nx, ny) 좌표 변환
        nx, ny = latlon_to_xy(float(loc["lat"]), float(loc["lon"]))
        # print(f"\n🌊 {loc['region']} - {loc['beach']} → 격자 {nx},{ny}")

        # --- KMA (기상청 단기예보) ---
        # API 호출 실패 시 일정 범위(max_rollback)까지 시각을 뒤로 물려서 재시도
        items, used_date, used_time = fetch_items_with_fallback(nx, ny, max_rollback=6)
        if not items:
            print("   ❌ KMA 예보 없음")
            continue

        # 기상청 데이터 중에서 end_dt까지의 시간만 선별
        # 조건: 발표 시각(ISSUE_HOURS) & 분 단위가 0인 시각만 포함
        picked = []
        for it in items:
            dt = datetime.datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M")
            if dt <= end_dt and dt.minute == 0 and dt.hour in ISSUE_HOURS:
                picked.append({
                    "datetime": dt.isoformat(),     # ISO8601 형식 시간
                    "category": it["category"],     # 예보 항목 (e.g. 파고, 기온 등)
                    "value": it["fcstValue"]        # 값
                })

        # --- Open-Meteo API ---
        # 위경도를 기반으로 해양예보(파고, 풍속 등)를 요청
        # Asia/Seoul 기준 시간대 맞춰서 정렬
        marine = fetch_marine(float(loc["lat"]), float(loc["lon"]),
                              timezone="Asia/Seoul", forecast_days=5)
        marine = [m for m in marine
                  if datetime.datetime.fromisoformat(m["om_datetime"]) <= end_dt]

        # --- 결과 병합 & 저장 ---
        # KMA + Open-Meteo 데이터를 병합 저장
        # merge=True 옵션으로 기존 문서 필드 보존
        save_forecasts_merged(loc["region"], loc["beach"], picked, marine)

if __name__ == "__main__":
    # 로컬 실행 시 main() 수행
    main()

# main.py — Cloud Functions (Gen2) HTTP 함수
# import datetime
# from zoneinfo import ZoneInfo
# from google.cloud import firestore

# db = firestore.Client()

# def log_update_time(request):
#     # 한국시간(KST)으로 현재 시각
#     now = datetime.datetime.now(tz=ZoneInfo("Asia/Seoul"))

#     # 문서 ID도 한국시간 기준으로 생성
#     doc_id = now.strftime("%Y%m%d%H%M")

#     ref = db.collection("meta_updates").document(doc_id)
#     ref.set({
#         # Firestore Timestamp도 KST 기준 datetime 전달
#         "timestamp": now,
#         "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
#         "note": "Cloud Scheduler test update (KST)"
#     })

#     return ("OK", 200)

