# scripts/storage.py
import datetime
import math
from .firebase_utils import db  # Firestore 클라이언트

# 기상청 발표 시각 (예보가 발표되는 기준 시간)
ALLOWED_HOURS = {2, 5, 8, 11, 14, 17, 20, 23}

def save_forecasts_merged(region, beach, picked, marine):
    """
    기상청(KMA) 예보 데이터 + Open-Meteo 데이터를 병합해서 Firestore에 저장.

    - 발표시각(02,05,08,11,14,17,20,23) 데이터만 허용
    - 같은 시각의 KMA 데이터에 Open-Meteo 보조 데이터(wave, 수온)를 합침
    - Firestore에 merge=True 옵션으로 저장 (기존 필드 유지)
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

    for dt_str, data in time_groups.items():
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
            doc_id = dt.strftime("%Y%m%d%H%M")  # 문서 ID는 YYYYMMDDHHMM

            # Firestore에서 사용할 region/beach 이름 정리 (특수문자 제거)
            clean_region = region.replace("/", "_").replace(" ", "_")
            clean_beach = beach.replace("/", "_").replace(" ", "_")

            # Firestore 문서 경로: regions/{region}/beaches/{beach}/forecasts/{doc_id}
            ref = (db.collection("regions")
                     .document(clean_region)
                     .collection("beaches")
                     .document(clean_beach)
                     .collection("forecasts")
                     .document(doc_id))

            # Firestore timestamp 필드 추가
            data["timestamp"] = dt

            # merge=True → 기존 필드 유지, 새로운 필드만 추가/업데이트
            batch.set(ref, data, merge=True)
            saved_count += 1
        except Exception as e:
            print(f"   ⚠ 저장 실패 {dt_str}: {e}")

    if saved_count > 0:
        batch.commit()  # 배치 작업 실행
        print(f"   ✅ {saved_count}개 시간대(발표시각) 병합 저장 완료")
    else:
        print("   ⚠ 저장할 데이터 없음")


# -------------------------
# 조회 유틸 함수들
# -------------------------

def get_beach_forecast(region, beach, hours=24):
    """
    특정 해변의 앞으로 hours시간 동안 예보 조회
    """
    now = datetime.datetime.now()
    start_time = now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)

    ref = (db.collection("regions").document(region)
             .collection("beaches").document(beach)
             .collection("forecasts")
             .where("timestamp", ">=", start_time)
             .where("timestamp", "<=", end_time)
             .order_by("timestamp"))

    return [doc.to_dict() for doc in ref.stream()]


def get_all_beaches_in_region(region):
    """
    특정 지역(region)의 모든 해변 이름 조회
    """
    ref = db.collection("regions").document(region).collection("beaches")
    return [doc.id for doc in ref.stream()]


def get_current_conditions(region, beach):
    """
    특정 해변의 현재 시간 이후 가장 가까운 예보 1건 조회
    """
    now = datetime.datetime.now()
    ref = (db.collection("regions").document(region)
             .collection("beaches").document(beach)
             .collection("forecasts")
             .where("timestamp", ">=", now)
             .order_by("timestamp")
             .limit(1))
    docs = list(ref.stream())
    return docs[0].to_dict() if docs else None
