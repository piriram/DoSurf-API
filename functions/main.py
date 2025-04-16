import functions_framework
import datetime
import os, json

from scripts.forecast_api import fetch_items_with_fallback, latlon_to_xy
from scripts.open_meteo import fetch_marine
from scripts.storage import save_forecasts_merged, update_region_beach_ids_list

# 설정 로드
try:
    from scripts.config import get_forecast_days, get_allowed_hours
    ISSUE_HOURS = set(get_allowed_hours())
    FORECAST_DAYS = get_forecast_days()
except ImportError:
    ISSUE_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}
    FORECAST_DAYS = 3

def load_locations():
    """locations.json 파일에서 위치 목록을 읽어오는 함수"""
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "scripts", "locations.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def update_region_metadata(locations):
    """각 지역의 해변 ID 목록을 메타데이터로 저장"""
    region_beaches = {}
    
    for loc in locations:
        region = loc["region"]
        beach_id = loc["beach_id"]
        beach = loc["beach"]
        display_name = loc.get("display_name", beach)
        
        if region not in region_beaches:
            region_beaches[region] = []
        
        existing_ids = [item["beach_id"] for item in region_beaches[region]]
        if beach_id not in existing_ids:
            region_beaches[region].append({
                "beach_id": beach_id,
                "beach": beach,
                "display_name": display_name
            })
    
    for region, beach_data in region_beaches.items():
        update_region_beach_ids_list(region, beach_data)

def run_collection():
    """실제 예보 수집 로직"""
    locations = load_locations()
    end_dt = datetime.datetime.now() + datetime.timedelta(days=FORECAST_DAYS)

    print("🗂️  지역별 해변 ID 메타데이터 업데이트 중...")
    update_region_metadata(locations)
    print("✅ 메타데이터 업데이트 완료\n")

    successful_updates = 0
    partial_updates = 0
    failed_updates = 0

    for i, loc in enumerate(locations, 1):
        nx, ny = latlon_to_xy(float(loc["lat"]), float(loc["lon"]))
        beach_id = loc["beach_id"]
        
        print(f"[{i}/{len(locations)}] 🌊 {loc['region']} - {loc['beach']} (ID: {beach_id}) → 격자 {nx},{ny}")

        has_kma = False
        has_marine = False
        picked = []
        marine = []

        try:
            # KMA (기상청 단기예보)
            items, used_date, used_time = fetch_items_with_fallback(nx, ny)
            
            if items:
                for it in items:
                    dt = datetime.datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M")
                    if dt <= end_dt and dt.minute == 0 and dt.hour in ISSUE_HOURS:
                        picked.append({
                            "datetime": dt.isoformat(),
                            "category": it["category"],
                            "value": it["fcstValue"]
                        })
                
                if picked:
                    print(f"   📊 KMA 예보: {len(picked)}개")
                    has_kma = True

            # Open-Meteo API
            try:
                marine = fetch_marine(float(loc["lat"]), float(loc["lon"]),
                                      timezone="Asia/Seoul", forecast_days=5)
                marine = [m for m in marine
                          if datetime.datetime.fromisoformat(m["om_datetime"]) <= end_dt]
                
                if marine:
                    print(f"   🌊 Open-Meteo: {len(marine)}개 해양 예보")
                    has_marine = True
            except Exception as e:
                print(f"   ⚠ Open-Meteo 수집 실패: {e}")

            # 결과 병합 & 저장
            if has_kma or has_marine:
                save_forecasts_merged(loc["region"], loc["beach"], beach_id, picked, marine)
                
                if has_kma and has_marine:
                    successful_updates += 1
                    print(f"   ✅ 전체 저장 완료")
                else:
                    partial_updates += 1
                    print(f"   ⚠️ 부분 저장 (KMA: {has_kma}, Marine: {has_marine})")
            else:
                print("   ❌ 저장할 데이터 없음")
                failed_updates += 1

        except Exception as e:
            print(f"   ❌ 예보 수집 실패: {e}")
            failed_updates += 1
            continue

        print()

    # 최종 결과
    print("=" * 50)
    print(f"🎯 예보 수집 완료!")
    print(f"   ✅ 전체 성공: {successful_updates}개 해변")
    print(f"   ⚠️ 부분 성공: {partial_updates}개 해변")
    print(f"   ❌ 완전 실패: {failed_updates}개 해변")
    print(f"   📊 전체: {len(locations)}개 위치")
    
    return {
        "total": len(locations),
        "success": successful_updates,
        "partial": partial_updates,
        "failed": failed_updates
    }

# HTTP 트리거 (수동 실행)
@functions_framework.http
def collect_forecast(request):
    """HTTP로 호출 가능한 함수"""
    print("🌊 수동 예보 수집 시작:", datetime.datetime.now().isoformat())
    
    try:
        result = run_collection()
        return {
            "success": True,
            "message": "예보 수집 완료",
            "result": result
        }, 200
    except Exception as e:
        print(f"❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }, 500

# Cloud Scheduler 트리거 (스케줄 실행)
@functions_framework.cloud_event
def scheduled_forecast_collect(cloud_event):
    """Cloud Scheduler에서 호출하는 함수"""
    print("🌊 스케줄 예보 수집 시작:", datetime.datetime.now().isoformat())
    
    try:
        result = run_collection()
        print(f"✅ 스케줄 수집 완료: {result}")
    except Exception as e:
        print(f"❌ 스케줄 수집 실패: {e}")
        import traceback
        traceback.print_exc()
        raise

# 로컬 테스트용
if __name__ == "__main__":
    print("로컬 테스트 실행")
    run_collection()