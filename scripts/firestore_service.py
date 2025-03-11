import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# Firebase 초기화 (한 번만 실행)
def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate("/Users/ram/do-surf-functions/serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
    return firestore.client()

def save_weather_to_firestore(region, beach, forecast_data):
    """
    기상 예보 데이터를 Firestore에 저장
    구조: regions/{region}/beaches/{beach}/forecasts/{YYYYMMDDHHMM}
    """
    db = init_firebase()
    
    # 시간별로 데이터 그룹화 (같은 시간의 여러 카테고리를 하나로 묶음)
    time_groups = {}
    
    for item in forecast_data:
        dt_str = item["datetime"]
        if dt_str not in time_groups:
            time_groups[dt_str] = {
                "region": region,
                "beach": beach,
                "datetime": dt_str
            }
        
        # 카테고리별 데이터 매핑
        category = item["category"]
        raw_value = item["value"]
        
        # 값 변환 및 검증
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
            elif category == "SKY":    # 하늘상태 (코드값)
                time_groups[dt_str]["sky_condition"] = int(raw_value)
            elif category == "REH":    # 습도 (%)
                time_groups[dt_str]["humidity"] = float(raw_value)
            elif category == "PCP":    # 강수량 (mm)
                # 다양한 강수량 표현 처리
                if raw_value in ["강수없음", "0", "0.0"]:
                    time_groups[dt_str]["precipitation"] = 0.0
                elif "미만" in raw_value:  # "1mm 미만", "0.1mm 미만" 등
                    time_groups[dt_str]["precipitation"] = 0.0
                else:
                    # "1.0mm", "10mm" 등에서 숫자만 추출
                    clean_value = raw_value.replace("mm", "").strip()
                    time_groups[dt_str]["precipitation"] = float(clean_value)
            elif category == "SNO":    # 적설량 (cm)
                # 적설량 표현 처리
                if raw_value in ["적설없음", "0", "0.0"]:
                    time_groups[dt_str]["snow"] = 0.0
                elif "미만" in raw_value:  # "1cm 미만" 등
                    time_groups[dt_str]["snow"] = 0.0
                else:
                    clean_value = raw_value.replace("cm", "").strip()
                    time_groups[dt_str]["snow"] = float(clean_value)
            elif category == "UUU":    # 동서바람성분 (m/s)
                time_groups[dt_str]["wind_u"] = float(raw_value)
            elif category == "VVV":    # 남북바람성분 (m/s)
                time_groups[dt_str]["wind_v"] = float(raw_value)
        
        except (ValueError, TypeError) as e:
            print(f"   ⚠ 값 변환 실패: {category}={raw_value} -> {e}")
            continue
    
    # 시간별로 문서 저장
    saved_count = 0
    for datetime_str, data in time_groups.items():
        try:
            dt = datetime.datetime.fromisoformat(datetime_str)
            doc_id = dt.strftime("%Y%m%d%H%M")
            
            # 계층 구조 경로 정리 (슬래시나 공백 문제 해결)
            clean_region = region.replace("/", "_").replace(" ", "_")
            clean_beach = beach.replace("/", "_").replace(" ", "_")
            
            # 계층 구조: regions/{region}/beaches/{beach}/forecasts/{YYYYMMDDHHMM}
            ref = (db.collection("regions")
                    .document(clean_region)
                    .collection("beaches")
                    .document(clean_beach)
                    .collection("forecasts")
                    .document(doc_id))
            
            # timestamp 필드 추가
            data["timestamp"] = dt
            
            ref.set(data)
            saved_count += 1
            
        except Exception as e:
            print(f"   ⚠ 저장 실패 ({datetime_str}): {e}")
    
    print(f"   ✅ {saved_count}개 시간대 데이터 저장 완료")

def get_beach_forecast(region, beach, hours=24):
    """특정 해변의 최신 예보 조회"""
    db = init_firebase()
    now = datetime.datetime.now()
    start_time = now.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=hours)
    
    # 경로 정리
    clean_region = region.replace("/", "_").replace(" ", "_")
    clean_beach = beach.replace("/", "_").replace(" ", "_")
    
    ref = (db.collection("regions")
            .document(clean_region)
            .collection("beaches")
            .document(clean_beach)
            .collection("forecasts")
            .where("timestamp", ">=", start_time)
            .where("timestamp", "<=", end_time)
            .order_by("timestamp"))
    
    docs = ref.stream()
    forecasts = []
    for doc in docs:
        data = doc.to_dict()
        forecasts.append(data)
    
    return forecasts

def get_all_beaches_in_region(region):
    """특정 지역의 모든 해변 목록 조회"""
    db = init_firebase()
    clean_region = region.replace("/", "_").replace(" ", "_")
    
    ref = db.collection("regions").document(clean_region).collection("beaches")
    docs = ref.stream()
    
    beaches = []
    for doc in docs:
        beaches.append(doc.id)
    
    return beaches

def get_current_conditions(region, beach):
    """현재 시간 기준 가장 가까운 예보 데이터 조회"""
    db = init_firebase()
    now = datetime.datetime.now()
    
    # 경로 정리
    clean_region = region.replace("/", "_").replace(" ", "_")
    clean_beach = beach.replace("/", "_").replace(" ", "_")
    
    # 현재 시간 이후의 가장 가까운 예보 찾기
    ref = (db.collection("regions")
            .document(clean_region)
            .collection("beaches")
            .document(clean_beach)
            .collection("forecasts")
            .where("timestamp", ">=", now)
            .order_by("timestamp")
            .limit(1))
    
    docs = list(ref.stream())
    if docs:
        return docs[0].to_dict()
    
    return None