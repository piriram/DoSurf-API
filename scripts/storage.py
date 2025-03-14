# scripts/storage.py
import datetime
import math
from zoneinfo import ZoneInfo  # Python 3.9+에서 사용 가능
from .firebase_utils import db  # Firestore 클라이언트

# 3시간 간격 저장 시간 (0, 3, 6, 9, 12, 15, 18, 21시)
ALLOWED_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

# 한국 시간대 설정
KST = ZoneInfo("Asia/Seoul")

def get_kst_now():
    """현재 한국 시간을 반환"""
    return datetime.datetime.now(tz=KST)

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
    # 2) Open-Meteo 데이터 병합
    # -------------------------
    kma_datetimes = set(time_groups.keys())  # 기상청 발표 시각 집합
    for r in marine:  # marine: Open-Meteo 결과 리스트
        dt_str = r["om_datetime"]
        if dt_str not in kma_datetimes:  # KMA에 없는 시간대는 무시
            continue
        # 같은 시간대라면 Open-Meteo 데이터 추가
        time_groups[dt_str]["om_wave_height"] = r.get("om_wave_height") + 0.5
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
            clean_region = region.replace("/", "_").replace(" ", "_")
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
        batch.commit()  # 배치 작업 실행
        print(f"   ✅ {saved_count}개 시간대(발표시각) 병합 저장 완료")
        
        # -------------------------
        # 4) 해변별 메타데이터 업데이트
        # -------------------------
        update_beach_metadata(region, beach, beach_id, saved_count, earliest_forecast_time, latest_forecast_time)
    else:
        print("   ⚠ 저장할 데이터 없음")


def update_beach_metadata(region, beach, beach_id, forecast_count, earliest_time=None, latest_time=None):
    """
    해변별 메타데이터 문서 업데이트 (Beach ID 사용)
    - 마지막 업데이트 시간을 한국 시간으로 설정
    - 예보 개수
    - 첫 번째/마지막 예보 시간
    """
    try:
        clean_region = region.replace("/", "_").replace(" ", "_")
        beach_id_str = str(beach_id)
        
        metadata_ref = (db.collection("regions")
                         .document(clean_region)
                         .collection(beach_id_str)
                         .document("_metadata"))
        
        # 한국 시간으로 업데이트 시간 설정
        kst_now = get_kst_now()
        
        metadata = {
            "beach_id": beach_id,
            "region": region,
            "beach": beach,
            "last_updated": kst_now,  # 한국 시간 사용
            "total_forecasts": forecast_count,
            "status": "active"
        }
        
        # 예보 시간 범위 정보
        if earliest_time:
            metadata["earliest_forecast"] = earliest_time
        if latest_time:
            metadata["latest_forecast"] = latest_time
            
        # 다음 예보 시간 (현재 한국 시간 이후 가장 가까운 예보)
        next_forecast_ref = (db.collection("regions")
                              .document(clean_region)
                              .collection(beach_id_str)
                              .where("timestamp", ">=", kst_now)
                              .order_by("timestamp")
                              .limit(1))
        
        next_docs = list(next_forecast_ref.stream())
        if next_docs:
            next_forecast_data = next_docs[0].to_dict()
            metadata["next_forecast_time"] = next_forecast_data.get("timestamp")
        
        metadata_ref.set(metadata)
        print(f"   📊 메타데이터 업데이트: {region}-{beach}({beach_id}) at {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")
        
    except Exception as e:
        print(f"   ⚠ 메타데이터 업데이트 실패: {e}")


# -------------------------
# 조회 유틸 함수들 (Beach ID 기반) - 시간대 수정
# -------------------------

def get_beach_forecast_by_id(region, beach_id, hours=24):
    """
    Beach ID를 사용해 특정 해변의 앞으로 hours시간 동안 예보 조회
    """
    kst_now = get_kst_now()
    start_time = kst_now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)

    clean_region = region.replace("/", "_").replace(" ", "_")
    beach_id_str = str(beach_id)

    # Beach ID 기반 구조: regions/{region}/{beach_id}
    ref = (db.collection("regions").document(clean_region)
             .collection(beach_id_str)
             .where("timestamp", ">=", start_time)
             .where("timestamp", "<=", end_time)
             .order_by("timestamp"))

    return [doc.to_dict() for doc in ref.stream()]


def get_beach_metadata_by_id(region, beach_id):
    """
    Beach ID를 사용해 특정 해변의 메타데이터 조회
    """
    try:
        clean_region = region.replace("/", "_").replace(" ", "_")
        beach_id_str = str(beach_id)
        
        metadata_ref = (db.collection("regions")
                         .document(clean_region)
                         .collection(beach_id_str)
                         .document("_metadata"))
        
        doc = metadata_ref.get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print(f"메타데이터 조회 실패: {e}")
        return None


def get_current_conditions_by_id(region, beach_id):
    """
    Beach ID를 사용해 특정 해변의 현재 시간 이후 가장 가까운 예보 1건 조회
    """
    kst_now = get_kst_now()
    clean_region = region.replace("/", "_").replace(" ", "_")
    beach_id_str = str(beach_id)
    
    # Beach ID 기반 구조: regions/{region}/{beach_id}
    ref = (db.collection("regions").document(clean_region)
             .collection(beach_id_str)
             .where("timestamp", ">=", kst_now)
             .order_by("timestamp")
             .limit(1))
    
    docs = list(ref.stream())
    return docs[0].to_dict() if docs else None


# -------------------------
# 지역별 해변 ID 목록 관리 - 시간대 수정
# -------------------------

def update_region_beach_ids_list(region, beach_data_list):
    """
    특정 지역의 해변 ID 목록을 메타데이터로 저장
    beach_data_list: [{"beach_id": 1001, "beach": "jukdo"}, ...]
    """
    try:
        clean_region = region.replace("/", "_").replace(" ", "_")
        ref = (db.collection("regions")
                 .document(clean_region)
                 .collection("_region_metadata")
                 .document("beaches"))
        
        # Beach ID와 이름을 모두 저장
        beach_ids = [item["beach_id"] for item in beach_data_list]
        beach_names = [item["beach"] for item in beach_data_list]
        beach_mapping = {str(item["beach_id"]): item["beach"] for item in beach_data_list}
        
        # 한국 시간으로 업데이트 시간 설정
        kst_now = get_kst_now()
        
        ref.set({
            "beach_ids": beach_ids,           # Beach ID 리스트
            "beach_names": beach_names,       # Beach 이름 리스트
            "beach_mapping": beach_mapping,   # ID -> 이름 매핑
            "updated_at": kst_now,            # 한국 시간 사용
            "total_beaches": len(beach_data_list)
        })
        print(f"✅ {region} 지역 해변 ID 목록 업데이트: {beach_ids} at {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")
    except Exception as e:
        print(f"⚠ 지역 해변 ID 목록 업데이트 실패: {e}")


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
                "total_beaches": data.get("total_beaches", 0)
            }
    except Exception as e:
        print(f"해변 ID 목록 조회 실패: {e}")
    
    # 기본값 반환
    return {"beach_ids": [], "beach_mapping": {}, "total_beaches": 0}


# -------------------------
# 기존 함수들 (호환성 유지) - 시간대 수정
# -------------------------

def get_beach_forecast(region, beach, hours=24):
    """
    기존 beach 이름 기반 조회 (호환성 유지)
    """
    kst_now = get_kst_now()
    start_time = kst_now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)

    clean_region = region.replace("/", "_").replace(" ", "_")
    clean_beach = beach.replace("/", "_").replace(" ", "_")

    ref = (db.collection("regions").document(clean_region)
             .collection(clean_beach)
             .where("timestamp", ">=", start_time)
             .where("timestamp", "<=", end_time)
             .order_by("timestamp"))

    return [doc.to_dict() for doc in ref.stream()]


def get_beach_metadata(region, beach):
    """
    기존 beach 이름 기반 메타데이터 조회 (호환성 유지)
    """
    try:
        clean_region = region.replace("/", "_").replace(" ", "_")
        clean_beach = beach.replace("/", "_").replace(" ", "_")
        
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
        beaches_ref = db.collection("regions").document(region).collection("_region_metadata").document("beaches")
        doc = beaches_ref.get()
        if doc.exists:
            return doc.to_dict().get("beach_names", [])
    except:
        pass
    
    beach_defaults = {
        "busan": ["songjeong", "haeundae", "gwangalli"],
        "jeju": ["hyeopjae", "jungmun", "hamdeok"]
    }
    return beach_defaults.get(region, [])


def get_current_conditions(region, beach):
    """
    기존 beach 이름 기반 현재 상태 조회 (호환성 유지)
    """
    kst_now = get_kst_now()
    clean_region = region.replace("/", "_").replace(" ", "_")
    clean_beach = beach.replace("/", "_").replace(" ", "_")
    
    ref = (db.collection("regions").document(clean_region)
             .collection(clean_beach)
             .where("timestamp", ">=", kst_now)
             .order_by("timestamp")
             .limit(1))
    
    docs = list(ref.stream())
    return docs[0].to_dict() if docs else None