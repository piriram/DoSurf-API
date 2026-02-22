# scripts/add_location.py
import json

from scripts.beach_registry import LOCATIONS_PATH, clear_locations_cache, load_locations


def save_locations(locations):
    with open(LOCATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(locations, f, ensure_ascii=False, indent=2)
    clear_locations_cache()

def get_next_beach_id(locations, region):
    """해당 지역의 다음 beach_id 생성"""
    region_beaches = [loc for loc in locations if loc["region"] == region]
    if not region_beaches:
        existing_regions = set(loc["region"] for loc in locations)
        region_count = len(existing_regions)
        base_id = (region_count + 1) * 1000
        return base_id + 1
    
    max_id = max(loc["beach_id"] for loc in region_beaches)
    return max_id + 1

def get_next_region_order(locations):
    """다음 지역 order 번호 생성"""
    if not locations:
        return 1
    max_order = max(loc.get("region_order", 0) for loc in locations)
    return max_order + 1

def add_beach(region, region_name, beach, display_name, lat, lon, region_order=None):
    """새 해변 추가"""
    locations = load_locations()
    
    beach_id = get_next_beach_id(locations, region)
    
    existing_region = next((loc for loc in locations if loc["region"] == region), None)
    
    if existing_region and region_order is None:
        region_order = existing_region["region_order"]
    elif region_order is None:
        region_order = get_next_region_order(locations)
    
    new_beach = {
        "beach_id": beach_id,
        "region": region,
        "region_name": region_name,
        "region_order": region_order,
        "beach": beach,
        "display_name": display_name,
        "lat": lat,
        "lon": lon
    }
    
    locations.append(new_beach)
    save_locations(locations)
    
    is_new_region = existing_region is None
    
    print(f"✅ 해변 추가 완료!")
    if is_new_region:
        print(f"   🆕 새 지역 추가됨!")
    print(f"   Beach ID: {beach_id}")
    print(f"   지역: {region_name} ({region}) - Order: {region_order}")
    print(f"   해변: {display_name} ({beach})")
    print(f"   좌표: {lat}, {lon}")
    print()
    print("📝 다음 단계:")
    print("1. python main.py 실행 (데이터 수집)")
    print("2. firebase deploy --only functions (API 배포)")

def list_beaches():
    """모든 해변 목록 출력"""
    locations = load_locations()
    
    by_region = {}
    for loc in locations:
        region = loc["region"]
        if region not in by_region:
            by_region[region] = {
                "name": loc["region_name"],
                "order": loc.get("region_order", 999),
                "beaches": []
            }
        by_region[region]["beaches"].append(loc)
    
    sorted_regions = sorted(by_region.items(), key=lambda x: x[1]["order"])
    
    print("\n🏖️  전체 해변 목록\n")
    for region_id, region_data in sorted_regions:
        print(f"📍 {region_data['name']} ({region_id}) - Order: {region_data['order']}")
        for beach in region_data["beaches"]:
            print(f"   {beach['beach_id']}: {beach['display_name']} ({beach['beach']})")
        print()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python scripts/add_location.py list")
        print("  python scripts/add_location.py add <region> <region_name> <beach> <display_name> <lat> <lon> [region_order]")
        print()
        print("예시:")
        print("  python scripts/add_location.py list")
        print("  python scripts/add_location.py add busan 부산 haeundae 해운대 35.1587 129.1603")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        list_beaches()
    elif command == "add":
        if len(sys.argv) < 8:
            print("❌ 잘못된 인자 개수")
            sys.exit(1)
        
        region = sys.argv[2]
        region_name = sys.argv[3]
        beach = sys.argv[4]
        display_name = sys.argv[5]
        lat = float(sys.argv[6])
        lon = float(sys.argv[7])
        region_order = int(sys.argv[8]) if len(sys.argv) > 8 else None
        
        add_beach(region, region_name, beach, display_name, lat, lon, region_order)
    else:
        print(f"❌ 알 수 없는 명령어: {command}")
        sys.exit(1)
