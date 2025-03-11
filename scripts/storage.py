# scripts/storage.py
import datetime
import math
from .firebase_utils import db

def save_forecasts_merged(region, beach, picked, marine):
    """
    KMA와 Open-Meteo 데이터를 시간 단위로 합쳐 Firestore에 batch 저장
    :param region: 지역명
    :param beach: 해변명
    :param picked: KMA 예보 리스트 [{datetime, category, value}, ...]
    :param marine: Open-Meteo 예보 리스트 [{datetime, om_wave_height, om_wave_direction, sea_surface_temperature}, ...]
    """
    time_groups = {}

    # 1) KMA 데이터 병합
    for chart in picked:
        dt_str = chart["datetime"]
        if dt_str not in time_groups:
            time_groups[dt_str] = {"region": region, "beach": beach, "datetime": dt_str}

        category, raw_value = chart["category"], chart["value"]
        try:
            if category == "WSD":
                time_groups[dt_str]["wind_speed"] = float(raw_value)
            elif category == "VEC":
                time_groups[dt_str]["wind_direction"] = float(raw_value)
            elif category == "WAV":
                time_groups[dt_str]["wave_height"] = float(raw_value)
            elif category == "TMP":
                time_groups[dt_str]["air_temperature"] = float(raw_value)
            elif category == "POP":
                time_groups[dt_str]["precipitation_probability"] = float(raw_value)
            elif category == "PTY":
                time_groups[dt_str]["precipitation_type"] = int(raw_value)
            elif category == "SKY":
                time_groups[dt_str]["sky_condition"] = int(raw_value)
            elif category == "REH":
                time_groups[dt_str]["humidity"] = float(raw_value)
            elif category == "PCP":
                if raw_value in ["강수없음", "0", "0.0"]:
                    val = 0.0
                elif "미만" in raw_value:
                    val = 0.0
                else:
                    val = float(raw_value.replace("mm", "").strip())
                time_groups[dt_str]["precipitation"] = val
            elif category == "SNO":
                if raw_value in ["적설없음", "0", "0.0"]:
                    val = 0.0
                elif "미만" in raw_value:
                    val = 0.0
                else:
                    val = float(raw_value.replace("cm", "").strip())
                time_groups[dt_str]["snow"] = val
            elif category == "UUU":
                time_groups[dt_str]["wind_u"] = float(raw_value)
            elif category == "VVV":
                time_groups[dt_str]["wind_v"] = float(raw_value)
                u = time_groups[dt_str].get("wind_u")
                v = time_groups[dt_str].get("wind_v")
                if u is not None and v is not None:
                    direction = (math.degrees(math.atan2(u, v)) + 360) % 360
                    time_groups[dt_str]["wind_direction_calc"] = round(direction, 2)
        except Exception as e:
            print(f"   ⚠ 값 변환 실패: {category}={raw_value} -> {e}")
            continue

    # 2) Open-Meteo 데이터 병합
    kma_datetimes = set(time_groups.keys())   # KMA에서 수집된 시간대만 기준

    for r in marine:
        dt_str = r["datetime"]
        if dt_str not in kma_datetimes:
            continue  # KMA에 없는 시간대는 버린다 ✅

        if dt_str not in time_groups:
            time_groups[dt_str] = {"region": region, "beach": beach, "datetime": dt_str}

        time_groups[dt_str]["om_wave_height"] = r.get("om_wave_height")
        time_groups[dt_str]["om_wave_direction"] = r.get("om_wave_direction")
        time_groups[dt_str]["sea_surface_temperature"] = r.get("sea_surface_temperature")

    # 3) Firestore 배치 저장
    batch = db.batch()
    saved_count = 0

    for dt_str, data in time_groups.items():
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
            doc_id = dt.strftime("%Y%m%d%H%M")
            clean_region = region.replace("/", "_").replace(" ", "_")
            clean_beach = beach.replace("/", "_").replace(" ", "_")

            ref = (db.collection("regions")
                     .document(clean_region)
                     .collection("beaches")
                     .document(clean_beach)
                     .collection("forecasts")
                     .document(doc_id))

            data["timestamp"] = dt
            batch.set(ref, data, merge=True)
            saved_count += 1
        except Exception as e:
            print(f"   ⚠ 저장 실패 {dt_str}: {e}")

    if saved_count > 0:
        batch.commit()
        print(f"   ✅ {saved_count}개 시간대 데이터 병합 저장 완료")
    else:
        print("   ⚠ 저장할 데이터 없음")


# 조회 유틸 (있으면 그대로 두세요)
def get_beach_forecast(region, beach, hours=24):
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
    ref = db.collection("regions").document(region).collection("beaches")
    return [doc.id for doc in ref.stream()]

def get_current_conditions(region, beach):
    now = datetime.datetime.now()
    ref = (db.collection("regions").document(region)
             .collection("beaches").document(beach)
             .collection("forecasts")
             .where("timestamp", ">=", now)
             .order_by("timestamp")
             .limit(1))
    docs = list(ref.stream())
    return docs[0].to_dict() if docs else None
