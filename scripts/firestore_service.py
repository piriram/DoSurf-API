# firestore_service.py
import os, json, datetime
import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

# ==============================
# Firebase 초기화
# ==============================
# 로컬 개발 시 기본 폴백 경로 (프로젝트/secrets/serviceAccountKey.json)
# __file__ : 파이썬이 자동으로 제공하는 특별 변수,현재 파일의 경로 문자열 가짐
# resolve() : 절대 경로로 변환, parent : 상위 폴더 디렉토리 경로 반환
SERVICE_KEY_PATH = Path(__file__).resolve().parent.parent / "secrets" / "serviceAccountKey.json"

def init_firebase():
    """
    Firebase 초기화 (로컬 + 배포 공용)
    우선순위:
      1) 환경변수 FIREBASE_SERVICE_ACCOUNT_JSON (JSON 문자열)
      2) 환경변수 GOOGLE_APPLICATION_CREDENTIALS (경로) → ADC
      3) GCP 런타임의 내장 ADC (initialize_app() 빈 인자)
      4) 로컬 폴백 파일 (secrets/serviceAccountKey.json)
    """
    if firebase_admin._apps:  # 이미 초기화 된 경우
        return firestore.client()

    # 1) 환경변수에 JSON 문자열 주입
    inline_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if inline_json:
        info = json.loads(inline_json)
        cred = credentials.Certificate(info)
        firebase_admin.initialize_app(cred)
        return firestore.client()

    # 2) GOOGLE_APPLICATION_CREDENTIALS 경로 기반
    gac_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if gac_path and os.path.exists(gac_path):
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
        return firestore.client()

    # 3) GCP 런타임 기본 서비스 계정 (ADC)
    try:
        firebase_admin.initialize_app()
        return firestore.client()
    except Exception:
        pass

    # 4) 로컬 secrets/serviceAccountKey.json
    if SERVICE_KEY_PATH.exists():
        cred = credentials.Certificate(str(SERVICE_KEY_PATH))
        firebase_admin.initialize_app(cred)
        return firestore.client()

    # 다 실패하면 에러
    raise RuntimeError("❌ Firebase 인증 정보를 찾을 수 없습니다.")


# ==============================
# 예보 데이터 Firestore 저장
# ==============================
def save_weather_to_firestore(region, beach, forecast_data):
    """
    기상 예보 데이터를 Firestore에 저장
    구조: regions/{region}/{beach}/{YYYYMMDDHHMM}
    """
    db = init_firebase()
    time_groups = {}  # 시간별 데이터 묶음

    for item in forecast_data:
        dt_str = item["datetime"]
        if dt_str not in time_groups:
            time_groups[dt_str] = {
                "region": region,
                "beach": beach,
                "datetime": dt_str
            }

        category = item["category"]
        raw_value = item["value"]

        try:
            if category == "WSD":      # 풍속 (m/s)
                time_groups[dt_str]["wind_speed"] = float(raw_value)
            elif category == "VEC":    # 풍향 (deg)
                time_groups[dt_str]["wind_direction"] = float(raw_value)
            elif category == "WAV":    # 파고 (m)
                time_groups[dt_str]["wave_height"] = float(raw_value)
                print(f"-----파고: {raw_value} m")
            elif category == "TMP":    # 기온 (°C)
                time_groups[dt_str]["air_temperature"] = float(raw_value)
            elif category == "POP":    # 강수확률 (%)
                time_groups[dt_str]["precipitation_probability"] = float(raw_value)
            elif category == "PTY":    # 강수형태 (코드값)
                time_groups[dt_str]["precipitation_type"] = int(raw_value)
            elif category == "SKY":    # 하늘상태 (코드값)
                time_groups[dt_str]["sky_condition"] = int(raw_value)
            elif category == "REH":    # 습도 (%)
                time_groups[dt_str]["humidity"] = float(raw_value)
            elif category == "PCP":    # 강수량 (mm)
                if raw_value in ["강수없음", "0", "0.0"]:
                    time_groups[dt_str]["precipitation"] = 0.0
                elif "미만" in raw_value:
                    time_groups[dt_str]["precipitation"] = 0.0
                else:
                    clean_value = raw_value.replace("mm", "").strip()
                    time_groups[dt_str]["precipitation"] = float(clean_value)
            elif category == "SNO":    # 적설량 (cm)
                if raw_value in ["적설없음", "0", "0.0"]:
                    time_groups[dt_str]["snow"] = 0.0
                elif "미만" in raw_value:
                    time_groups[dt_str]["snow"] = 0.0
                else:
                    clean_value = raw_value.replace("cm", "").strip()
                    time_groups[dt_str]["snow"] = float(clean_value)

        except (ValueError, TypeError) as e:
            print(f"⚠ 변환 실패: {category}={raw_value} -> {e}")
            continue

    # 저장 루프
    saved_count = 0
    for datetime_str, data in time_groups.items():
        try:
            dt = datetime.datetime.fromisoformat(datetime_str)
            doc_id = dt.strftime("%Y%m%d%H%M")

            clean_region = region.replace("/", "_").replace(" ", "_")
            clean_beach = beach.replace("/", "_").replace(" ", "_")

            # 변경된 구조: regions/{region}/{beach}/{forecastId}
            ref = (db.collection("regions")
                     .document(clean_region)
                     .collection(clean_beach)
                     .document(doc_id))

            data["timestamp"] = dt
            ref.set(data)
            saved_count += 1

        except Exception as e:
            print(f"⚠ 저장 실패 ({datetime_str}): {e}")

    print(f"✅ {saved_count}개 시간대 데이터 저장 완료")


# ==============================
# 특정 해변 예보 조회
# ==============================
def get_beach_forecast(region, beach, hours=24):
    """특정 해변의 앞으로 hours시간 예보 조회"""
    db = init_firebase()
    now = datetime.datetime.now()
    start_time = now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)

    clean_region = region.replace("/", "_").replace(" ", "_")
    clean_beach = beach.replace("/", "_").replace(" ", "_")

    # 변경된 구조: regions/{region}/{beach}
    ref = (db.collection("regions")
             .document(clean_region)
             .collection(clean_beach)
             .where("timestamp", ">=", start_time)
             .where("timestamp", "<=", end_time)
             .order_by("timestamp"))

    docs = ref.stream()
    return [doc.to_dict() for doc in docs]


# ==============================
# 지역 내 모든 해변 목록 조회
# ==============================
def get_all_beaches_in_region(region):
    """특정 지역(region)의 모든 해변 이름 반환"""
    db = init_firebase()
    clean_region = region.replace("/", "_").replace(" ", "_")

    # 변경된 구조에서는 regions/{region} 아래의 모든 컬렉션이 해변임
    # Firestore에서 컬렉션 목록을 직접 조회하는 것은 제한적이므로
    # 별도의 beaches 메타데이터 문서를 관리하거나 다른 방법 필요
    
    # 임시 해결책: 알려진 해변들을 하드코딩하거나 별도 관리
    # 또는 regions/{region}/beaches_metadata 문서에 해변 목록 저장
    ref = db.collection("regions").document(clean_region).collection("beaches_metadata")
    docs = ref.stream()
    return [doc.id for doc in docs]


# ==============================
# 특정 해변 현재 상태 조회
# ==============================
def get_current_conditions(region, beach):
    """현재 시간 이후 가장 가까운 예보 데이터 반환"""
    db = init_firebase()
    now = datetime.datetime.now()

    clean_region = region.replace("/", "_").replace(" ", "_")
    clean_beach = beach.replace("/", "_").replace(" ", "_")

    # 변경된 구조: regions/{region}/{beach}
    ref = (db.collection("regions")
             .document(clean_region)
             .collection(clean_beach)
             .where("timestamp", ">=", now)
             .order_by("timestamp")
             .limit(1))

    docs = list(ref.stream())
    return docs[0].to_dict() if docs else None