# main.py
import datetime
import os, json

from scripts.forecast_api import fetch_items_with_fallback, latlon_to_xy
from scripts.open_meteo import fetch_marine
from scripts.storage import save_forecasts_merged, update_region_beach_ids_list

# 3시간 간격 저장 시간 (0, 3, 6, 9, 12, 15, 18, 21시)
ISSUE_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

def load_locations():
    """
    scripts/locations.json 파일에서 위치 목록을 읽어오는 함수.
    각 위치는 beach_id, region(지역), beach(해수욕장), lat/lon(위경도) 정보를 포함.
    """
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "scripts", "locations.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def update_region_metadata(locations):
    """
    locations.json을 기반으로 각 지역의 해변 ID 목록을 메타데이터로 저장
    """
    region_beaches = {}
    
    # 지역별 해변 ID와 이름 그룹화
    for loc in locations:
        region = loc["region"]
        beach_id = loc["beach_id"]
        beach = loc["beach"]
        
        if region not in region_beaches:
            region_beaches[region] = []
        
        # 중복 체크
        existing_ids = [item["beach_id"] for item in region_beaches[region]]
        if beach_id not in existing_ids:
            region_beaches[region].append({
                "beach_id": beach_id,
                "beach": beach
            })
    
    # 각 지역별 해변 ID 목록을 Firestore에 저장
    for region, beach_data in region_beaches.items():
        update_region_beach_ids_list(region, beach_data)

def main():
    """
    메인 실행 함수:
    1. 위치 정보 로드
    2. 지역별 해변 ID 메타데이터 업데이트
    3. 각 해변별 예보 데이터 수집 및 저장 (Beach ID 사용)
    """
    # 예측 종료 시각: 지금부터 4일 뒤까지 데이터만 수집
    locations = load_locations()
    end_dt = datetime.datetime.now() + datetime.timedelta(days=4)

    print("🗂️  지역별 해변 ID 메타데이터 업데이트 중...")
    update_region_metadata(locations)
    print("✅ 메타데이터 업데이트 완료\n")

    successful_updates = 0
    failed_updates = 0

    for i, loc in enumerate(locations, 1):
        # 위경도 → 기상청 격자(nx, ny) 좌표 변환
        nx, ny = latlon_to_xy(float(loc["lat"]), float(loc["lon"]))
        beach_id = loc["beach_id"]
        
        print(f"[{i}/{len(locations)}] 🌊 {loc['region']} - {loc['beach']} (ID: {beach_id}) → 격자 {nx},{ny}")

        try:
            # --- KMA (기상청 단기예보) ---
            # API 호출 실패 시 일정 범위(max_rollback)까지 시각을 뒤로 물려서 재시도
            items, used_date, used_time = fetch_items_with_fallback(nx, ny, max_rollback=6)
            if not items:
                print("   ❌ KMA 예보 없음")
                failed_updates += 1
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

            print(f"   📊 KMA 예보: {len(picked)}개 시간대")

            # --- Open-Meteo API ---
            # 위경도를 기반으로 해양예보(파고, 풍속 등)를 요청
            # Asia/Seoul 기준 시간대 맞춰서 정렬
            marine = fetch_marine(float(loc["lat"]), float(loc["lon"]),
                                  timezone="Asia/Seoul", forecast_days=5)
            marine = [m for m in marine
                      if datetime.datetime.fromisoformat(m["om_datetime"]) <= end_dt]

            print(f"   🌊 Open-Meteo: {len(marine)}개 해양 예보")

            # --- 결과 병합 & 저장 (Beach ID 사용) ---
            # KMA + Open-Meteo 데이터를 병합 저장
            # merge=True 옵션으로 기존 문서 필드 보존
            # 저장 완료 후 해변별 메타데이터 자동 업데이트
            save_forecasts_merged(loc["region"], loc["beach"], beach_id, picked, marine)
            successful_updates += 1

        except Exception as e:
            print(f"   ❌ 예보 수집 실패: {e}")
            failed_updates += 1
            continue

        print()  # 빈 줄로 구분

    # 최종 결과 요약
    print("=" * 50)
    print(f"🎯 예보 수집 완료!")
    print(f"   ✅ 성공: {successful_updates}개 해변")
    print(f"   ❌ 실패: {failed_updates}개 해변")
    print(f"   📊 전체: {len(locations)}개 위치")

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

