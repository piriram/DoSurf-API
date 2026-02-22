# scripts/storage.py
import datetime
import math
from zoneinfo import ZoneInfo  # Python 3.9+에서 사용 가능
from .firebase_utils import db  # Firestore 클라이언트
from .beach_registry import (
    get_all_beach_ids_in_region as _registry_get_all_beach_ids_in_region,
    load_locations,
)
from . import cache_utils  # 캐싱 레이어
from .config import get_allowed_hours, get_wave_height_offset
from .path_utils import sanitize_firestore_id

# 3시간 간격 저장 시간 (0, 3, 6, 9, 12, 15, 18, 21시)
ALLOWED_HOURS = set(get_allowed_hours())
# Open-Meteo 파고 보정값(기본 0.5m): config.json(storage.wave_height_offset)에서 조정 가능.
WAVE_HEIGHT_OFFSET = float(get_wave_height_offset())

# 한국 시간대 설정
KST = ZoneInfo("Asia/Seoul")

def get_kst_now():
    """현재 한국 시간을 반환"""
    return datetime.datetime.now(tz=KST)


def _sanitize_id(value):
    return sanitize_firestore_id(value)

def save_forecasts_merged(region, beach, beach_id, picked, marine):
    """
    기상청(KMA) 예보 데이터 + Open-Meteo 데이터를 병합해서 Firestore에 저장.

    - Beach ID를 컬렉션 이름으로 사용
    - 발표시각(02,05,08,11,14,17,20,23) 데이터만 허용
    - 같은 시각의 KMA 데이터에 Open-Meteo 보조 데이터(wave, 수온)를 합침
    - Firestore에 merge=True 옵션으로 저장 (기존 필드 유지)
    - 저장 완료 후 해변별 메타데이터 업데이트
    """
    time_groups = {}

    # -------------------------
    # 1) 기상청(KMA) 데이터 병합
    # -------------------------
    for chart in picked:  # picked: 기상청에서 가져온 데이터 목록
        dt_str = chart["datetime"]               # "YYYY-MM-DDTHH:MM:SS"
        dt_obj = datetime.datetime.fromisoformat(dt_str)

        # 발표시각이 아니거나, 분 단위가 00이 아니면 저장하지 않음
        if dt_obj.minute != 0 or dt_obj.hour not in ALLOWED_HOURS:
            continue

        # 처음 보는 시간대라면 기본 구조 생성
        if dt_str not in time_groups:
            time_groups[dt_str] = {
                "beach_id": beach_id,
                "region": region,
                "beach": beach,
                "datetime": dt_str
            }

        # 카테고리별 값 매핑
        category, raw_value = chart["category"], chart["value"]
        try:
            if category == "WSD":      # 풍속 (m/s)
                time_groups[dt_str]["wind_speed"] = float(raw_value)
            elif category == "VEC":    # 풍향 (deg)
                time_groups[dt_str]["wind_direction"] = float(raw_value)
            elif category == "WAV":    # 파고 (m)
                time_groups[dt_str]["wave_height"] = float(raw_value)
            elif category == "TMP":    # 기온 (°C)
                time_groups[dt_str]["air_temperature"] = float(raw_value)
            elif category == "POP":    # 강수확률 (%)
                time_groups[dt_str]["precipitation_probability"] = float(raw_value)
            elif category == "PTY":    # 강수형태 (코드값)
                time_groups[dt_str]["precipitation_type"] = int(raw_value)
            elif category == "SKY":    # 하늘 상태 (코드값)
                time_groups[dt_str]["sky_condition"] = int(raw_value)
            elif category == "REH":    # 습도 (%)
                time_groups[dt_str]["humidity"] = float(raw_value)
            elif category == "PCP":    # 강수량 (mm)
                if raw_value in ["강수없음", "0", "0.0"]:
                    val = 0.0
                elif "미만" in raw_value:
                    val = 0.0
                else:
                    val = float(raw_value.replace("mm", "").strip())
                time_groups[dt_str]["precipitation"] = val
            elif category == "SNO":    # 적설량 (cm)
                if raw_value in ["적설없음", "0", "0.0"]:
                    val = 0.0
                elif "미만" in raw_value:
                    val = 0.0
                else:
                    val = float(raw_value.replace("cm", "").strip())
                time_groups[dt_str]["snow"] = val
            elif category == "UUU":    # 동서 바람 성분 (m/s)
                time_groups[dt_str]["wind_u"] = float(raw_value)
            elif category == "VVV":    # 남북 바람 성분 (m/s)
                time_groups[dt_str]["wind_v"] = float(raw_value)
                # wind_u, wind_v 성분이 모두 있으면 풍향을 계산
                u = time_groups[dt_str].get("wind_u")
                v = time_groups[dt_str].get("wind_v")
                if u is not None and v is not None:
                    # atan2(u, v) → 각도 변환 후 0~360도로 정규화
                    direction = (math.degrees(math.atan2(u, v)) + 180) % 360
                    time_groups[dt_str]["wind_direction_calc"] = round(direction, 2)
        except Exception as e:
            print(f"   ⚠ 값 변환 실패: {category}={raw_value} -> {e}")
            continue

    # -------------------------
    # 2) Open-Meteo 데이터 병합 (개선!)
    # -------------------------
    for r in marine:  # marine: Open-Meteo 결과 리스트
        dt_str = r["om_datetime"]
        dt_obj = datetime.datetime.fromisoformat(dt_str)
        
        # ALLOWED_HOURS 확인
        if dt_obj.minute != 0 or dt_obj.hour not in ALLOWED_HOURS:
            continue
        
        # KMA 데이터가 있으면 병합, 없으면 새로 생성
        if dt_str not in time_groups:
            time_groups[dt_str] = {
                "beach_id": beach_id,
                "region": region,
                "beach": beach,
                "datetime": dt_str
            }
        
        # Open-Meteo 데이터 추가
        raw_wave_height = r.get("om_wave_height")
        time_groups[dt_str]["om_wave_height"] = (
            (float(raw_wave_height) if raw_wave_height is not None else 0.0) + WAVE_HEIGHT_OFFSET
        )
        time_groups[dt_str]["om_wave_direction"] = r.get("om_wave_direction")
        time_groups[dt_str]["om_sea_surface_temperature"] = r.get("om_sea_surface_temperature")

    # -------------------------
    # 3) Firestore에 배치 저장
    # -------------------------
    batch = db.batch()
    saved_count = 0
    earliest_forecast_time = None
    latest_forecast_time = None

    for dt_str, data in time_groups.items():
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
            # 시간대가 없는 경우 KST로 설정
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            
            doc_id = dt.strftime("%Y%m%d%H%M")  # 문서 ID는 YYYYMMDDHHMM

            # Firestore에서 사용할 region 이름 정리 (특수문자 제거)
            clean_region = _sanitize_id(region)
            # Beach ID를 문자열로 변환 (컬렉션 이름으로 사용)
            beach_id_str = str(beach_id)

            # Beach ID 기반 구조: regions/{region}/{beach_id}/{doc_id}
            ref = (db.collection("regions")
                     .document(clean_region)
                     .collection(beach_id_str)
                     .document(doc_id))

            # Firestore timestamp 필드 추가
            data["timestamp"] = dt

            # merge=True → 기존 필드 유지, 새로운 필드만 추가/업데이트
            batch.set(ref, data, merge=True)
            saved_count += 1
            
            # 가장 이른/늦은 예보 시간 추적
            if earliest_forecast_time is None or dt < earliest_forecast_time:
                earliest_forecast_time = dt
            if latest_forecast_time is None or dt > latest_forecast_time:
                latest_forecast_time = dt
                
        except Exception as e:
            print(f"   ⚠ 저장 실패 {dt_str}: {e}")

    if saved_count > 0:
        # -------------------------
        # 4) 메타데이터를 같은 배치에 추가 (배치 쓰기 통합)
        # -------------------------
        clean_region = _sanitize_id(region)
        beach_id_str = str(beach_id)
        kst_now = get_kst_now()

        metadata_ref = (db.collection("regions")
                         .document(clean_region)
                         .collection(beach_id_str)
                         .document("_metadata"))

        metadata = {
            "beach_id": beach_id,
            "region": region,
            "beach": beach,
            "last_updated": kst_now,
            "total_forecasts": saved_count,
            "status": "active"
        }

        if earliest_forecast_time:
            metadata["earliest_forecast"] = earliest_forecast_time
        if latest_forecast_time:
            metadata["latest_forecast"] = latest_forecast_time

        # 메타데이터도 배치에 추가
        batch.set(metadata_ref, metadata)

        # 배치 커밋 (예보 + 메타데이터 한 번에 저장)
        batch.commit()
        print(f"   ✅ {saved_count}개 시간대(발표시각) + 메타데이터 배치 저장 완료")
        print(f"   📊 메타데이터 업데이트: {region}-{beach}({beach_id}) at {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")

        # 캐시 무효화 (새 데이터가 저장되었으므로)
        cache_utils.invalidate_pattern(f"forecast:{region}:{beach_id}")
        cache_utils.invalidate_pattern(f"current:{region}:{beach_id}")
        cache_utils.invalidate_pattern(f"metadata:{region}:{beach_id}")
        print(f"   🔄 캐시 무효화 완료: {region}-{beach}({beach_id})")
    else:
        print("   ⚠ 저장할 데이터 없음")


# -------------------------
# 전역 해변 목록 관리
# -------------------------

def update_global_beaches_list(all_beaches):
    """
    전체 해변 목록을 최상위 메타데이터로 저장
    all_beaches: BEACH_REGISTRY 전체 데이터
    
    iOS 클라이언트는 이 문서 하나만 조회하면 모든 해변 정보를 얻을 수 있습니다.
    """
    try:
        ref = (db.collection("_global_metadata")
                 .document("all_beaches"))
        
        kst_now = get_kst_now()
        
        # iOS에서 필요한 필드만 추출하여 간결하게 구성
        beaches_for_client = []
        for beach in all_beaches:
            beaches_for_client.append({
                "id": str(beach["beach_id"]),
                "region": beach["region"],
                "region_name": beach["region_name"],
                "region_order": beach["region_order"],
                "place": beach["display_name"],
                "lat": beach["lat"],
                "lon": beach["lon"]
            })
        
        # region_order 순으로 정렬
        beaches_for_client.sort(key=lambda x: (x["region_order"], x["id"]))
        
        ref.set({
            "beaches": beaches_for_client,
            "total_beaches": len(beaches_for_client),
            "updated_at": kst_now
        })
        
        print(f"✅ 전역 해변 목록 업데이트: {len(beaches_for_client)}개 at {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")
    except Exception as e:
        print(f"⚠ 전역 해변 목록 업데이트 실패: {e}")


# -------------------------
# 지역별 해변 ID 목록 관리 (호환성 유지)
# -------------------------

def update_region_beach_ids_list(region, beach_data_list):
    """
    특정 지역의 해변 ID 목록을 메타데이터로 저장
    beach_data_list: [{"beach_id": 1001, "beach": "jukdo", "display_name": "죽도"}, ...]
    
    주의: 이 함수는 호환성을 위해 유지되지만, 
    새로운 앱 버전에서는 update_global_beaches_list()를 사용하는 것을 권장합니다.
    """
    try:
        clean_region = _sanitize_id(region)
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
        print(f"✅ {region} 지역 해변 ID 목록 업데이트: {beach_ids} at {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")
    except Exception as e:
        print(f"⚠ 지역 해변 ID 목록 업데이트 실패: {e}")

def get_all_beach_ids_in_region(region):
    """특정 지역의 모든 해변 ID 목록 조회 (beach_registry 구현 위임)."""
    return _registry_get_all_beach_ids_in_region(region)


# -------------------------
# 조회 유틸 함수들 (Beach ID 기반)
# -------------------------

def get_beach_forecast_by_id(region, beach_id, hours=24):
    """
    Beach ID를 사용해 특정 해변의 앞으로 hours시간 동안 예보 조회
    안전 제한: 최대 100개 문서
    캐싱: 15분 (예보 데이터는 정기적으로 업데이트)
    """
    # 캐시 확인
    cached_data = cache_utils.get("forecast", region, beach_id, hours)
    if cached_data:
        return cached_data

    # 캐시 미스 - Firestore에서 조회
    kst_now = get_kst_now()
    start_time = kst_now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)

    clean_region = _sanitize_id(region)
    beach_id_str = str(beach_id)

    # Beach ID 기반 구조: regions/{region}/{beach_id}
    # 안전 제한 추가: .limit(100)
    ref = (db.collection("regions").document(clean_region)
             .collection(beach_id_str)
             .where("timestamp", ">=", start_time)
             .where("timestamp", "<=", end_time)
             .order_by("timestamp")
             .limit(100))

    result = [doc.to_dict() for doc in ref.stream()]

    # 캐시 저장
    cache_utils.set("forecast", region, beach_id, hours, data=result)

    return result


def get_beach_metadata_by_id(region, beach_id):
    """
    Beach ID를 사용해 특정 해변의 메타데이터 조회
    캐싱: 1시간 (메타데이터는 거의 변경되지 않음)
    """
    # 캐시 확인
    cached_data = cache_utils.get("metadata", region, beach_id)
    if cached_data:
        return cached_data

    # 캐시 미스 - Firestore에서 조회
    try:
        clean_region = _sanitize_id(region)
        beach_id_str = str(beach_id)

        metadata_ref = (db.collection("regions")
                         .document(clean_region)
                         .collection(beach_id_str)
                         .document("_metadata"))

        doc = metadata_ref.get()
        result = doc.to_dict() if doc.exists else None

        # 캐시 저장 (존재하는 경우에만)
        if result:
            cache_utils.set("metadata", region, beach_id, data=result)

        return result
    except Exception as e:
        print(f"메타데이터 조회 실패: {e}")
        return None


def get_current_conditions_by_id(region, beach_id):
    """
    Beach ID를 사용해 특정 해변의 현재 시간 이후 가장 가까운 예보 1건 조회
    캐싱: 10분 (현재 상태는 자주 조회됨)
    """
    # 캐시 확인
    cached_data = cache_utils.get("current", region, beach_id)
    if cached_data:
        return cached_data

    # 캐시 미스 - Firestore에서 조회
    kst_now = get_kst_now()
    clean_region = _sanitize_id(region)
    beach_id_str = str(beach_id)

    # Beach ID 기반 구조: regions/{region}/{beach_id}
    ref = (db.collection("regions").document(clean_region)
             .collection(beach_id_str)
             .where("timestamp", ">=", kst_now)
             .order_by("timestamp")
             .limit(1))

    docs = list(ref.stream())
    result = docs[0].to_dict() if docs else None

    # 캐시 저장 (존재하는 경우에만)
    if result:
        cache_utils.set("current", region, beach_id, data=result)

    return result


# -------------------------
# 기존 함수들 (호환성 유지)
# -------------------------

def get_beach_forecast(region, beach, hours=24):
    """
    기존 beach 이름 기반 조회 (호환성 유지)
    안전 제한: 최대 100개 문서
    """
    kst_now = get_kst_now()
    start_time = kst_now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)

    clean_region = _sanitize_id(region)
    clean_beach = _sanitize_id(beach)

    # 안전 제한 추가: .limit(100)
    ref = (db.collection("regions").document(clean_region)
             .collection(clean_beach)
             .where("timestamp", ">=", start_time)
             .where("timestamp", "<=", end_time)
             .order_by("timestamp")
             .limit(100))

    return [doc.to_dict() for doc in ref.stream()]


def get_beach_metadata(region, beach):
    """
    기존 beach 이름 기반 메타데이터 조회 (호환성 유지)
    """
    try:
        clean_region = _sanitize_id(region)
        clean_beach = _sanitize_id(beach)
        
        metadata_ref = (db.collection("regions")
                         .document(clean_region)
                         .collection(clean_beach)
                         .document("_metadata"))
        
        doc = metadata_ref.get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print(f"메타데이터 조회 실패: {e}")
        return None


def get_all_beaches_in_region(region):
    """
    기존 beach 이름 기반 조회 (호환성 유지)
    """
    try:
        clean_region = _sanitize_id(region)
        beaches_ref = (db.collection("regions")
                       .document(clean_region)
                       .collection("_region_metadata")
                       .document("beaches"))
        doc = beaches_ref.get()
        if doc.exists:
            return doc.to_dict().get("beach_names", [])
    except Exception:
        pass

    defaults = {}
    for loc in load_locations():
        defaults.setdefault(loc["region"], []).append(loc["beach"])
    return defaults.get(region, [])


def get_current_conditions(region, beach):
    """
    기존 beach 이름 기반 현재 상태 조회 (호환성 유지)
    """
    kst_now = get_kst_now()
    clean_region = _sanitize_id(region)
    clean_beach = _sanitize_id(beach)
    
    ref = (db.collection("regions").document(clean_region)
             .collection(clean_beach)
             .where("timestamp", ">=", kst_now)
             .order_by("timestamp")
             .limit(1))
    
    docs = list(ref.stream())
    return docs[0].to_dict() if docs else None
