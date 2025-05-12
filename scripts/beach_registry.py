"""
해변 레지스트리 관리 모듈
- locations.json 로드
- 전역 해변 목록 메타데이터 관리
- 지역별 해변 목록 메타데이터 관리
"""
import os
import json
from zoneinfo import ZoneInfo
import datetime
from .firebase_utils import db

KST = ZoneInfo("Asia/Seoul")

def get_kst_now():
    """현재 한국 시간을 반환"""
    return datetime.datetime.now(tz=KST)


def load_locations():
    """locations.json 파일에서 해변 정보 로드"""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base_dir, "scripts", "locations.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_global_beach_list(locations):
    """
    전체 해변 목록을 최상위 메타데이터로 저장
    Firestore 구조: _global_metadata/all_beaches
    
    locations: locations.json에서 로드한 전체 해변 데이터
    """
    try:
        ref = db.collection("_global_metadata").document("all_beaches")
        
        # 해변 목록 생성
        beaches = []
        for loc in locations:
            beaches.append({
                "id": str(loc["beach_id"]),
                "region": loc["region"],
                "region_name": loc["region_name"],
                "region_order": loc["region_order"],
                "beach": loc["beach"],
                "display_name": loc["display_name"],
                "lat": loc["lat"],
                "lon": loc["lon"]
            })
        
        # region_order 기준으로 정렬
        beaches.sort(key=lambda x: (x["region_order"], x["id"]))
        
        kst_now = get_kst_now()
        
        data = {
            "beaches": beaches,
            "total_beaches": len(beaches),
            "updated_at": kst_now,
            "version": "1.0"
        }
        
        ref.set(data)
        print(f"✅ 전체 해변 목록 업데이트 완료: {len(beaches)}개 at {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")
        
        return True
    except Exception as e:
        print(f"⚠ 전체 해변 목록 업데이트 실패: {e}")
        return False


def update_region_beach_ids_list(region, beach_data_list):
    """
    특정 지역의 해변 ID 목록을 메타데이터로 저장
    Firestore 구조: regions/{region}/_region_metadata/beaches
    
    beach_data_list: [{"beach_id": 1001, "beach": "jukdo", "display_name": "죽도"}, ...]
    """
    try:
        clean_region = region.replace("/", "_").replace(" ", "_")
        ref = (db.collection("regions")
                 .document(clean_region)
                 .collection("_region_metadata")
                 .document("beaches"))
        
        beach_ids = [item["beach_id"] for item in beach_data_list]
        beach_names = [item["beach"] for item in beach_data_list]
        beach_mapping = {str(item["beach_id"]): item["beach"] for item in beach_data_list}
        display_name_mapping = {str(item["beach_id"]): item.get("display_name", item["beach"]) for item in beach_data_list}
        
        kst_now = get_kst_now()
        
        ref.set({
            "beach_ids": beach_ids,
            "beach_names": beach_names,
            "beach_mapping": beach_mapping,
            "display_name_mapping": display_name_mapping,
            "updated_at": kst_now,
            "total_beaches": len(beach_data_list)
        })
        print(f"   ✅ {region} 지역 해변 ID 목록 업데이트: {beach_ids}")
    except Exception as e:
        print(f"   ⚠ {region} 지역 해변 ID 목록 업데이트 실패: {e}")


def update_all_metadata(locations):
    """
    전체 해변 목록과 지역별 해변 목록을 모두 업데이트
    
    locations: locations.json에서 로드한 전체 해변 데이터
    """
    print("🗂️  해변 메타데이터 업데이트 중...")
    
    # 1. 전체 해변 목록 업데이트
    update_global_beach_list(locations)
    
    # 2. 지역별 해변 목록 업데이트
    region_beaches = {}
    for loc in locations:
        region = loc["region"]
        beach_id = loc["beach_id"]
        beach = loc["beach"]
        display_name = loc.get("display_name", beach)
        
        if region not in region_beaches:
            region_beaches[region] = []
        
        # 중복 체크
        existing_ids = [item["beach_id"] for item in region_beaches[region]]
        if beach_id not in existing_ids:
            region_beaches[region].append({
                "beach_id": beach_id,
                "beach": beach,
                "display_name": display_name
            })
    
    for region, beach_data in region_beaches.items():
        update_region_beach_ids_list(region, beach_data)
    
    print("✅ 메타데이터 업데이트 완료\n")


def get_all_beaches():
    """
    전체 해변 목록 조회
    """
    try:
        ref = db.collection("_global_metadata").document("all_beaches")
        doc = ref.get()
        if doc.exists:
            data = doc.to_dict()
            return {
                "beaches": data.get("beaches", []),
                "total_beaches": data.get("total_beaches", 0),
                "updated_at": data.get("updated_at"),
                "version": data.get("version", "1.0")
            }
    except Exception as e:
        print(f"전체 해변 목록 조회 실패: {e}")
    
    return {"beaches": [], "total_beaches": 0}


def get_all_beach_ids_in_region(region):
    """
    특정 지역의 모든 해변 ID 목록 조회
    """
    try:
        clean_region = region.replace("/", "_").replace(" ", "_")
        beaches_ref = (db.collection("regions")
                        .document(clean_region)
                        .collection("_region_metadata")
                        .document("beaches"))
        doc = beaches_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return {
                "beach_ids": data.get("beach_ids", []),
                "beach_mapping": data.get("beach_mapping", {}),
                "display_name_mapping": data.get("display_name_mapping", {}),
                "total_beaches": data.get("total_beaches", 0)
            }
    except Exception as e:
        print(f"해변 ID 목록 조회 실패: {e}")
    
    return {"beach_ids": [], "beach_mapping": {}, "display_name_mapping": {}, "total_beaches": 0}