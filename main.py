# main.py - 서버 오류와 부분 데이터를 명확히 구분하는 버전
import datetime

from scripts.forecast_api import fetch_items_with_fallback, latlon_to_xy
from scripts.open_meteo import fetch_marine
from scripts.storage import save_forecasts_merged, update_region_beach_ids_list
from scripts.beach_registry import load_locations
from scripts.alerts import send_telegram_alert
from cleanup_old_forecasts import cleanup_old_forecasts

# 설정 로드
try:
    from scripts.config import get_forecast_days, get_allowed_hours
    ISSUE_HOURS = set(get_allowed_hours())
    FORECAST_DAYS = get_forecast_days()
except ImportError:
    ISSUE_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}
    FORECAST_DAYS = 3
    print("⚠ config.py를 찾을 수 없습니다. 기본 설정을 사용합니다.")

# 예상 데이터 크기 (단기예보 3일 기준)
EXPECTED_ITEM_COUNT = 72 * 11  # 72시간 * 11개 카테고리 = 792개
EXPECTED_FORECAST_HOURS = 28   # 28개 시간대 (3일 * 8시간 + 4시간)

def update_region_metadata(locations):
    """각 지역의 해변 ID 목록을 메타데이터로 저장"""
    region_beaches = {}
    
    for loc in locations:
        region = loc["region"]
        beach_id = loc["beach_id"]
        beach = loc["beach"]
        display_name = loc.get("display_name", beach)
        
        if region not in region_beaches:
            region_beaches[region] = []
        
        existing_ids = [item["beach_id"] for item in region_beaches[region]]
        if beach_id not in existing_ids:
            region_beaches[region].append({
                "beach_id": beach_id,
                "beach": beach,
                "display_name": display_name
            })
    
    for region, beach_data in region_beaches.items():
        update_region_beach_ids_list(region, beach_data)

def run_collection():
    """
    메인 실행 함수
    
    개선사항:
    - 서버 오류와 부분 데이터를 명확히 구분
    - 부분 데이터도 저장 (다음 실행 때 자동 병합)
    - 명확한 로그 메시지
    """
    locations = load_locations()
    end_dt = datetime.datetime.now() + datetime.timedelta(days=FORECAST_DAYS)

    print("🗂️  지역별 해변 ID 메타데이터 업데이트 중...")
    update_region_metadata(locations)
    print("✅ 메타데이터 업데이트 완료\n")

    successful_updates = 0
    partial_updates = 0
    failed_updates = 0

    for i, loc in enumerate(locations, 1):
        nx, ny = latlon_to_xy(float(loc["lat"]), float(loc["lon"]))
        beach_id = loc["beach_id"]
        
        print(f"[{i}/{len(locations)}] 🌊 {loc['region']} - {loc['beach']} (ID: {beach_id}) → 격자 {nx},{ny}")

        has_kma = False
        has_marine = False
        forecast_count = 0
        picked = []
        marine = []

        try:
            # --- 1. KMA (기상청 단기예보) ---
            items, used_date, used_time = fetch_items_with_fallback(nx, ny)
            
            if items:
                # 받은 데이터 개수 확인
                item_count = len(items)
                completeness = (item_count / EXPECTED_ITEM_COUNT) * 100 if EXPECTED_ITEM_COUNT > 0 else 0
                
                # 시간대별 필터링
                for it in items:
                    dt = datetime.datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M")
                    if dt <= end_dt and dt.minute == 0 and dt.hour in ISSUE_HOURS:
                        picked.append({
                            "datetime": dt.isoformat(),
                            "category": it["category"],
                            "value": it["fcstValue"]
                        })
                
                if picked:
                    forecast_time_slots = {p["datetime"] for p in picked}
                    forecast_count = len(forecast_time_slots)
                    has_kma = True
                    
                    # 데이터 완전성 평가
                    if completeness >= 90:
                        print(f"   ✅ KMA 전체 데이터: {forecast_count}개 시간대 (완전성 {completeness:.0f}%)")
                    elif completeness >= 70:
                        print(f"   ⚠️ KMA 부분 데이터: {forecast_count}개 시간대 (완전성 {completeness:.0f}%)")
                        print(f"      💡 일부 시간대 누락, 다음 실행 때 자동 보완 예정")
                    else:
                        print(f"   ⚠️ KMA 최소 데이터: {forecast_count}개 시간대 (완전성 {completeness:.0f}%)")
                        print(f"      ⚠️ 대부분 시간대 누락, 확인 필요")
                else:
                    print(f"   ⚠️ KMA 데이터 필터링 후 0개 (raw items: {item_count})")
            else:
                print("   ❌ KMA 서버 오류 (데이터 수신 실패)")
                print("      💡 Open-Meteo 데이터만 시도")

            # --- 2. Open-Meteo API ---
            try:
                marine = fetch_marine(float(loc["lat"]), float(loc["lon"]),
                                      timezone="Asia/Seoul", forecast_days=5)
                marine = [m for m in marine
                          if datetime.datetime.fromisoformat(m["om_datetime"]) <= end_dt]
                
                if marine:
                    print(f"   🌊 Open-Meteo: {len(marine)}개 해양 예보")
                    has_marine = True
                else:
                    print(f"   ⚠️ Open-Meteo 데이터 없음")
            except Exception as e:
                print(f"   ⚠ Open-Meteo 수집 실패: {e}")

            # --- 3. 결과 병합 & 저장 ---
            if has_kma or has_marine:
                save_forecasts_merged(loc["region"], loc["beach"], beach_id, picked, marine)
                
                if has_kma and has_marine:
                    # KMA 데이터 완전성에 따라 분류
                    if picked:
                        if forecast_count >= EXPECTED_FORECAST_HOURS * 0.9:
                            successful_updates += 1
                            print(f"   ✅ 전체 데이터 저장 완료")
                        else:
                            partial_updates += 1
                            print(f"   ⚠️ 부분 데이터 저장 완료 (다음 실행 때 보완)")
                    else:
                        partial_updates += 1
                        print(f"   ⚠️ 부분 저장 (Open-Meteo 위주)")
                elif has_kma:
                    partial_updates += 1
                    print(f"   ⚠️ 부분 저장 (KMA만, Open-Meteo 실패)")
                else:
                    partial_updates += 1
                    print(f"   ⚠️ 부분 저장 (Open-Meteo만, KMA 서버 오류)")
            else:
                print("   ❌ 저장할 데이터 없음 (KMA + Open-Meteo 모두 실패)")
                failed_updates += 1

        except Exception as e:
            print(f"   ❌ 예보 수집 실패: {e}")
            failed_updates += 1
            continue

        print()

    # 최종 결과 요약
    print("=" * 50)
    print(f"🎯 예보 수집 완료!")
    print(f"   ✅ 전체 성공: {successful_updates}개 해변 (완전한 데이터)")
    if partial_updates > 0:
        print(f"   ⚠️ 부분 성공: {partial_updates}개 해변 (일부 데이터)")
        print(f"      💡 부분 데이터는 다음 실행 때 자동 보완됩니다")
    print(f"   ❌ 완전 실패: {failed_updates}개 해변 (데이터 없음)")
    print(f"   📊 전체: {len(locations)}개 위치")
    
    total_success = successful_updates + partial_updates
    success_rate = (total_success / len(locations) * 100) if locations else 0
    print(f"   📈 데이터 확보율: {success_rate:.1f}%")
    
    # 권장 사항
    if partial_updates > 0:
        print(f"\n💡 권장사항:")
        print(f"   - 부분 데이터는 다음 실행({FORECAST_DAYS}시간 후)에 자동으로 보완됩니다")
        print(f"   - merge=True 옵션으로 기존 데이터와 자동 병합됩니다")

    # 7일 이전 데이터 자동 삭제
    cleanup_result = None
    cleanup_error = None
    print("\n🧹 7일 이전 오래된 데이터 정리 중...")
    try:
        cleanup_result = cleanup_old_forecasts(days=7, dry_run=False, confirm=False)
        deleted_docs = cleanup_result.get("deleted_documents", 0) if cleanup_result else 0
        print(f"🧹 정리 완료: {deleted_docs}개 문서 삭제")
    except Exception as e:
        cleanup_error = str(e)
        print(f"⚠️ 데이터 정리 실패 (수집 결과에는 영향 없음): {cleanup_error}")

    # 문제 발생 시 Telegram 알림 (환경변수 설정 시)
    alert_messages = []
    if failed_updates > 0:
        alert_messages.append(
            f"수집 실패 해변 {failed_updates}개 발생 (전체 {len(locations)}개 중)"
        )
    if cleanup_error:
        alert_messages.append(f"자동 정리(cleanup) 실패: {cleanup_error}")

    if alert_messages:
        alert_result = send_telegram_alert(
            message="\n".join(alert_messages),
            level="WARNING",
            source="run_collection",
        )
        if alert_result.get("sent"):
            print("📩 Telegram 장애 알림 전송 완료")
        else:
            print(f"ℹ️ Telegram 알림 미전송: {alert_result.get('reason')}")

    return {
        "total": len(locations),
        "success": successful_updates,
        "partial": partial_updates,
        "failed": failed_updates,
        "cleanup": cleanup_result,
    }


def main():
    run_collection()

if __name__ == "__main__":
    main()
