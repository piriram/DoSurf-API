from flask import Flask, jsonify
import datetime
import os, json

from scripts.forecast_api import fetch_items_with_fallback, latlon_to_xy
from scripts.open_meteo import fetch_marine
from scripts.storage import save_forecasts_merged, update_region_beach_ids_list

app = Flask(__name__)

# 설정 로드
try:
    from scripts.config import get_forecast_days, get_allowed_hours
    ISSUE_HOURS = set(get_allowed_hours())
    FORECAST_DAYS = get_forecast_days()
except ImportError:
    ISSUE_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}
    FORECAST_DAYS = 3

def load_locations():
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "scripts", "locations.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def update_region_metadata(locations):
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
        
        print(f"[{i}/{len(locations)}] 🌊 {loc['region']} - {loc['beach']} (ID: {beach_id})")

        has_kma = False
        has_marine = False
        picked = []
        marine = []

        try:
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
                    print(f"   📊 KMA: {len(picked)}개")
                    has_kma = True

            try:
                marine = fetch_marine(float(loc["lat"]), float(loc["lon"]),
                                      timezone="Asia/Seoul", forecast_days=5)
                marine = [m for m in marine
                          if datetime.datetime.fromisoformat(m["om_datetime"]) <= end_dt]
                
                if marine:
                    print(f"   🌊 Open-Meteo: {len(marine)}개")
                    has_marine = True
            except Exception as e:
                print(f"   ⚠ Open-Meteo 실패: {e}")

            if has_kma or has_marine:
                save_forecasts_merged(loc["region"], loc["beach"], beach_id, picked, marine)
                
                if has_kma and has_marine:
                    successful_updates += 1
                    print(f"   ✅ 완료")
                else:
                    partial_updates += 1
                    print(f"   ⚠️ 부분 저장")
            else:
                failed_updates += 1

        except Exception as e:
            print(f"   ❌ 실패: {e}")
            failed_updates += 1

    return {
        "total": len(locations),
        "success": successful_updates,
        "partial": partial_updates,
        "failed": failed_updates
    }

@app.route('/', methods=['GET', 'POST'])
def collect():
    print("🌊 예보 수집 시작:", datetime.datetime.now().isoformat())
    
    try:
        result = run_collection()
        return jsonify({
            "success": True,
            "message": "완료",
            "result": result
        }), 200
    except Exception as e:
        print(f"❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)