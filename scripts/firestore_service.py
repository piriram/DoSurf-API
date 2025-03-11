# scripts/firestore_utils.py
import os, datetime
from typing import List, Dict, Optional

import firebase_admin
from firebase_admin import credentials, firestore

# --- Firebase 초기화 ---
def _init_db():
    if not firebase_admin._apps:
        root = os.path.dirname(os.path.dirname(__file__))  # 프로젝트 루트
        key_path = os.path.join(root, "serviceAccountKey.json")
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = _init_db()

# --- 저장/조회 함수 ---
def save_chart_to_firestore(region: str, beach: str, picked: List[Dict]) -> None:
    """
    regions/{region}/beaches/{beach}/forecasts/{YYYYMMDDHHMM}
    """
    time_groups: Dict[str, Dict] = {}

    for chart in picked:
        dt_str = chart["datetime"]
        if dt_str not in time_groups:
            time_groups[dt_str] = {
                "region": region,
                "beach": beach,
                "datetime": dt_str
            }

        category = chart["category"]
        raw_value = chart["value"]

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
        except (ValueError, TypeError) as e:
            print(f"   ⚠ 값 변환 실패: {category}={raw_value} -> {e}")
            continue

    saved = 0
    for datetime_str, data in time_groups.items():
        try:
            dt = datetime.datetime.fromisoformat(datetime_str)
            doc_id = dt.strftime("%Y%m%d%H%M")

            clean_region = region.replace("/", "_").replace(" ", "_")
            clean_beach  = beach.replace("/", "_").replace(" ", "_")

            ref = (db.collection("regions")
                     .document(clean_region)
                     .collection("beaches")
                     .document(clean_beach)
                     .collection("forecasts")
                     .document(doc_id))

            data["timestamp"] = dt
            ref.set(data)
            saved += 1
        except Exception as e:
            print(f"   ⚠ 저장 실패 ({datetime_str}): {e}")

    print(f"   ✅ {saved}개 시간대 데이터 저장 완료")

def get_beach_forecast(region: str, beach: str, hours: int = 24) -> List[Dict]:
    now = datetime.datetime.now()
    start_time = now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)

    ref = (db.collection("regions")
             .document(region)
             .collection("beaches")
             .document(beach)
             .collection("forecasts")
             .where("timestamp", ">=", start_time)
             .where("timestamp", "<=", end_time)
             .order_by("timestamp"))

    return [d.to_dict() for d in ref.stream()]

def get_all_beaches_in_region(region: str) -> List[str]:
    ref = db.collection("regions").document(region).collection("beaches")
    return [doc.id for doc in ref.stream()]

def get_current_conditions(region: str, beach: str) -> Optional[Dict]:
    now = datetime.datetime.now()
    ref = (db.collection("regions")
             .document(region)
             .collection("beaches")
             .document(beach)
             .collection("forecasts")
             .where("timestamp", ">=", now)
             .order_by("timestamp")
             .limit(1))
    docs = list(ref.stream())
    return docs[0].to_dict() if docs else None
