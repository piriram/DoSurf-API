# api_functions.py
import json
import os
from firebase_functions import https_fn
from firebase_admin import initialize_app
from scripts.firebase_utils import db

# Firebase 앱 초기화
try:
    initialize_app()
except ValueError:
    pass

# locations.json 경로
LOCATIONS_FILE = os.path.join(os.path.dirname(__file__), "scripts", "locations.json")

def load_locations():
    """locations.json 파일 로드"""
    with open(LOCATIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_regions_from_locations():
    """
    locations.json에서 지역 목록 추출 (중복 제거)
    반환: [{"id": "busan", "name": "부산", "order": 4}, ...]
    """
    locations = load_locations()
    regions_dict = {}
    
    for loc in locations:
        region_id = loc["region"]
        if region_id not in regions_dict:
            regions_dict[region_id] = {
                "id": region_id,
                "name": loc["region_name"],
                "order": loc.get("region_order", 999)
            }
    
    regions_list = sorted(regions_dict.values(), key=lambda x: x["order"])
    return regions_list

def get_region_name_mapping():
    """
    지역 ID -> 한글 이름 매핑 생성
    반환: {"busan": "부산", "jeju": "제주", ...}
    """
    locations = load_locations()
    mapping = {}
    for loc in locations:
        if loc["region"] not in mapping:
            mapping[loc["region"]] = loc["region_name"]
    return mapping

def get_beach_name_mapping():
    """
    해변 영문 이름 -> 한글 이름 매핑 생성
    반환: {"songjeong": "송정", "jungmun": "중문", ...}
    """
    locations = load_locations()
    mapping = {}
    for loc in locations:
        mapping[loc["beach"]] = loc["display_name"]
    return mapping


@https_fn.on_request(cors=https_fn.CorsOptions(
    cors_origins="*",
    cors_methods=["get", "post"]
))
def get_all_locations(req: https_fn.Request) -> https_fn.Response:
    """
    모든 지역과 해변 정보를 한 번에 반환
    GET /get_all_locations
    """
    try:
        locations = load_locations()
        regions_dict = {}
        
        for loc in locations:
            region_id = loc["region"]
            if region_id not in regions_dict:
                regions_dict[region_id] = {
                    "region_id": region_id,
                    "region_name": loc["region_name"],
                    "region_order": loc.get("region_order", 999),
                    "beaches": []
                }
            
            regions_dict[region_id]["beaches"].append({
                "beach_id": loc["beach_id"],
                "beach": loc["beach"],
                "display_name": loc["display_name"]
            })
        
        all_data = sorted(regions_dict.values(), key=lambda x: x["region_order"])
        
        for region in all_data:
            region.pop("region_order", None)
        
        response_data = {"data": all_data}
        
        return https_fn.Response(
            json.dumps(response_data, ensure_ascii=False),
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        print(f"❌ Error in get_all_locations: {e}")
        return https_fn.Response(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status=500,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )


@https_fn.on_request(cors=https_fn.CorsOptions(
    cors_origins="*",
    cors_methods=["get", "post"]
))
def get_regions(req: https_fn.Request) -> https_fn.Response:
    """
    모든 지역 목록 반환
    GET /get_regions
    """
    try:
        regions = get_regions_from_locations()
        
        return https_fn.Response(
            json.dumps({"regions": regions}, ensure_ascii=False),
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        print(f"❌ Error in get_regions: {e}")
        return https_fn.Response(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status=500,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )


@https_fn.on_request(cors=https_fn.CorsOptions(
    cors_origins="*",
    cors_methods=["get", "post"]
))
def get_beaches_by_region(req: https_fn.Request) -> https_fn.Response:
    """
    특정 지역의 해변 목록 반환
    GET /get_beaches_by_region?region=busan
    """
    try:
        region = req.args.get("region")
        
        if not region:
            return https_fn.Response(
                json.dumps({
                    "error": "region parameter is required"
                }, ensure_ascii=False),
                status=400,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"
                }
            )
        
        clean_region = region.replace("/", "_").replace(" ", "_")
        
        beaches_ref = (db.collection("regions")
                      .document(clean_region)
                      .collection("_region_metadata")
                      .document("beaches"))
        
        doc = beaches_ref.get()
        
        if not doc.exists:
            return https_fn.Response(
                json.dumps({
                    "error": f"Region '{region}' not found"
                }, ensure_ascii=False),
                status=404,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"
                }
            )
        
        data = doc.to_dict()
        beach_ids = data.get("beach_ids", [])
        beach_mapping = data.get("beach_mapping", {})
        display_name_mapping = data.get("display_name_mapping", {})
        
        beaches = []
        for beach_id in beach_ids:
            beach_en = beach_mapping.get(str(beach_id))
            if beach_en:
                beaches.append({
                    "beach_id": beach_id,
                    "beach": beach_en,
                    "display_name": display_name_mapping.get(str(beach_id), beach_en)
                })
        
        region_names = get_region_name_mapping()
        
        response_data = {
            "region": region,
            "region_name": region_names.get(region, region),
            "beaches": beaches,
            "total": len(beaches)
        }
        
        return https_fn.Response(
            json.dumps(response_data, ensure_ascii=False),
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        print(f"❌ Error in get_beaches_by_region: {e}")
        return https_fn.Response(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status=500,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )


@https_fn.on_request(cors=https_fn.CorsOptions(
    cors_origins="*",
    cors_methods=["get", "post"]
))
def get_beach_info(req: https_fn.Request) -> https_fn.Response:
    """
    특정 해변의 상세 정보 반환 (메타데이터 포함)
    GET /get_beach_info?region=busan&beach_id=4001
    """
    try:
        region = req.args.get("region")
        beach_id = req.args.get("beach_id")
        
        if not region or not beach_id:
            return https_fn.Response(
                json.dumps({
                    "error": "region and beach_id parameters are required"
                }, ensure_ascii=False),
                status=400,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"
                }
            )
        
        clean_region = region.replace("/", "_").replace(" ", "_")
        beach_id_str = str(beach_id)
        
        metadata_ref = (db.collection("regions")
                       .document(clean_region)
                       .collection(beach_id_str)
                       .document("_metadata"))
        
        doc = metadata_ref.get()
        
        if not doc.exists:
            return https_fn.Response(
                json.dumps({
                    "error": f"Beach not found: {region}/{beach_id}"
                }, ensure_ascii=False),
                status=404,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"
                }
            )
        
        metadata = doc.to_dict()
        beach_en = metadata.get("beach", "")
        
        region_names = get_region_name_mapping()
        beach_names = get_beach_name_mapping()
        
        response_data = {
            "beach_id": int(beach_id),
            "region": region,
            "region_name": region_names.get(region, region),
            "beach": beach_en,
            "display_name": beach_names.get(beach_en, beach_en),
            "metadata": {
                "last_updated": metadata.get("last_updated").isoformat() if metadata.get("last_updated") else None,
                "total_forecasts": metadata.get("total_forecasts", 0),
                "earliest_forecast": metadata.get("earliest_forecast").isoformat() if metadata.get("earliest_forecast") else None,
                "latest_forecast": metadata.get("latest_forecast").isoformat() if metadata.get("latest_forecast") else None,
                "status": metadata.get("status", "unknown")
            }
        }
        
        return https_fn.Response(
            json.dumps(response_data, ensure_ascii=False),
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        print(f"❌ Error in get_beach_info: {e}")
        return https_fn.Response(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status=500,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            }
        )