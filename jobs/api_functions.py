# api_functions.py
import json
from typing import Optional
from firebase_functions import https_fn
from firebase_admin import initialize_app
from scripts.firebase_utils import db
from scripts import cache_utils  # 캐싱 레이어 추가
from scripts.beach_registry import load_locations
from scripts.path_utils import sanitize_firestore_id

# Firebase 앱 초기화
try:
    initialize_app()
except ValueError:
    pass

def _json_response(data: dict, status: int = 200, cache_status: Optional[str] = None) -> https_fn.Response:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*"
    }
    if cache_status is not None:
        headers["X-Cache"] = cache_status
    return https_fn.Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        headers=headers
    )

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


@https_fn.on_request()
def get_all_locations(req: https_fn.Request) -> https_fn.Response:
    """
    모든 지역과 해변 정보를 한 번에 반환
    GET /get_all_locations
    캐싱: 1시간 (거의 변경되지 않음)
    """
    try:
        # 캐시 확인
        cached_data = cache_utils.get("beaches", "all_locations")
        if cached_data:
            return _json_response(cached_data, status=200, cache_status="HIT")

        # 캐시 미스 - Firestore에서 조회
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

        # 캐시 저장
        cache_utils.set("beaches", "all_locations", data=response_data)
        
        return _json_response(response_data, status=200)
        
    except Exception as e:
        print(f"❌ Error in get_all_locations: {e}")
        return _json_response({"error": str(e)}, status=500)


@https_fn.on_request()
def get_regions(req: https_fn.Request) -> https_fn.Response:
    """
    모든 지역 목록 반환
    GET /get_regions
    캐싱: 1시간 (거의 변경되지 않음)
    """
    try:
        # 캐시 확인
        cached_data = cache_utils.get("regions", "all")
        if cached_data:
            return _json_response(cached_data, status=200, cache_status="HIT")

        # 캐시 미스 - 데이터 조회
        regions = get_regions_from_locations()
        response_data = {"regions": regions}

        # 캐시 저장
        cache_utils.set("regions", "all", data=response_data)

        return _json_response(response_data, status=200, cache_status="MISS")
        
    except Exception as e:
        print(f"❌ Error in get_regions: {e}")
        return _json_response({"error": str(e)}, status=500)


@https_fn.on_request()
def get_beaches_by_region(req: https_fn.Request) -> https_fn.Response:
    """
    특정 지역의 해변 목록 반환
    GET /get_beaches_by_region?region=busan
    캐싱: 1시간 (거의 변경되지 않음)
    """
    try:
        region = req.args.get("region")

        if not region:
            return _json_response({"error": "region parameter is required"}, status=400)

        # 캐시 확인
        cached_data = cache_utils.get("beaches", region)
        if cached_data:
            return _json_response(cached_data, status=200, cache_status="HIT")

        # 캐시 미스 - Firestore에서 조회
        clean_region = sanitize_firestore_id(region)

        beaches_ref = (db.collection("regions")
                      .document(clean_region)
                      .collection("_region_metadata")
                      .document("beaches"))

        doc = beaches_ref.get()
        
        if not doc.exists:
            return _json_response({"error": f"Region '{region}' not found"}, status=404)
        
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

        # 캐시 저장
        cache_utils.set("beaches", region, data=response_data)

        return _json_response(response_data, status=200, cache_status="MISS")
        
    except Exception as e:
        print(f"❌ Error in get_beaches_by_region: {e}")
        return _json_response({"error": str(e)}, status=500)


@https_fn.on_request()
def get_beach_info(req: https_fn.Request) -> https_fn.Response:
    """
    특정 해변의 상세 정보 반환 (메타데이터 포함)
    GET /get_beach_info?region=busan&beach_id=4001
    캐싱: 1시간 (메타데이터는 거의 변경되지 않음)
    """
    try:
        region = req.args.get("region")
        beach_id = req.args.get("beach_id")

        if not region or not beach_id:
            return _json_response({"error": "region and beach_id parameters are required"}, status=400)

        # 캐시 확인
        cached_data = cache_utils.get("metadata", region, beach_id)
        if cached_data:
            return _json_response(cached_data, status=200, cache_status="HIT")

        # 캐시 미스 - Firestore에서 조회
        clean_region = sanitize_firestore_id(region)
        beach_id_str = str(beach_id)

        metadata_ref = (db.collection("regions")
                       .document(clean_region)
                       .collection(beach_id_str)
                       .document("_metadata"))

        doc = metadata_ref.get()
        
        if not doc.exists:
            return _json_response({"error": f"Beach not found: {region}/{beach_id}"}, status=404)
        
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

        # 캐시 저장
        cache_utils.set("metadata", region, beach_id, data=response_data)

        return _json_response(response_data, status=200, cache_status="MISS")
        
    except Exception as e:
        print(f"❌ Error in get_beach_info: {e}")
        return _json_response({"error": str(e)}, status=500)
