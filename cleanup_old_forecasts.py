#!/usr/bin/env python3
"""
오래된 예보 데이터 정리 스크립트

사용법:
    python cleanup_old_forecasts.py                    # 10일 지난 데이터 삭제
    python cleanup_old_forecasts.py --days 7           # 7일 지난 데이터 삭제
    python cleanup_old_forecasts.py --dry-run          # 삭제하지 않고 미리보기만
    python cleanup_old_forecasts.py --region busan     # 부산 지역만 삭제
    python cleanup_old_forecasts.py --beach-id 4001    # 특정 해변만 삭제

주의:
    - 이 스크립트는 Firestore에서 영구적으로 데이터를 삭제합니다
    - 먼저 --dry-run으로 삭제될 데이터를 확인하는 것을 권장합니다
    - 삭제된 데이터는 복구할 수 없습니다
"""

import argparse
import datetime
from zoneinfo import ZoneInfo
from scripts.beach_registry import load_locations
from scripts.path_utils import sanitize_firestore_id

# Firebase Admin SDK 초기화
try:
    from firebase_admin import initialize_app, firestore
    import firebase_admin

    # 이미 초기화되었는지 확인
    try:
        firebase_admin.get_app()
    except ValueError:
        initialize_app()

    db = firestore.client()
except ImportError:
    print("❌ Firebase Admin SDK가 설치되지 않았습니다.")
    print("   설치: pip install firebase-admin")
    exit(1)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")

def get_old_forecasts(region, beach_id, cutoff_date, dry_run=False):
    """
    특정 해변의 오래된 예보 데이터 조회

    Args:
        region: 지역 이름
        beach_id: 해변 ID
        cutoff_date: 이 날짜 이전 데이터 삭제
        dry_run: True면 조회만 하고 삭제하지 않음

    Returns:
        삭제된(또는 삭제될) 문서 수
    """
    clean_region = sanitize_firestore_id(region)
    beach_id_str = str(beach_id)

    # 해변 컬렉션 참조
    collection_ref = (db.collection("regions")
                       .document(clean_region)
                       .collection(beach_id_str))

    # 오래된 데이터 쿼리 (메타데이터 문서 제외)
    old_docs_query = (collection_ref
                       .where("timestamp", "<", cutoff_date)
                       .limit(500))  # 안전을 위해 한 번에 최대 500개

    docs = list(old_docs_query.stream())

    # 메타데이터 문서 제외
    docs_to_delete = [doc for doc in docs if doc.id != "_metadata"]

    if not docs_to_delete:
        return 0

    deleted_count = len(docs_to_delete)

    if dry_run:
        print(f"   [DRY RUN] {deleted_count}개 문서 삭제 예정")
        # 처음 3개만 샘플로 출력
        for doc in docs_to_delete[:3]:
            data = doc.to_dict()
            timestamp = data.get("timestamp")
            print(f"     - {doc.id}: {timestamp}")
        if deleted_count > 3:
            print(f"     ... 외 {deleted_count - 3}개")
    else:
        # 배치로 삭제 (최대 500개)
        batch = db.batch()
        for doc in docs_to_delete:
            batch.delete(doc.reference)
        batch.commit()
        print(f"   🗑️  {deleted_count}개 문서 삭제 완료")

    return deleted_count


def cleanup_old_forecasts(days=10, dry_run=False, target_region=None, target_beach_id=None):
    """
    오래된 예보 데이터 정리

    Args:
        days: 몇 일 이전 데이터를 삭제할지
        dry_run: True면 실제 삭제하지 않고 미리보기만
        target_region: 특정 지역만 처리 (None이면 전체)
        target_beach_id: 특정 해변만 처리 (None이면 전체)
    """
    print("=" * 60)
    print(f"🧹 오래된 예보 데이터 정리 시작")
    print(f"   기준 날짜: {days}일 이전 데이터 삭제")
    print(f"   모드: {'🔍 미리보기 (삭제 안 함)' if dry_run else '🗑️  실제 삭제'}")
    print("=" * 60)

    # 기준 날짜 계산
    kst_now = datetime.datetime.now(tz=KST)
    cutoff_date = kst_now - datetime.timedelta(days=days)
    print(f"\n📅 현재 시간: {kst_now.strftime('%Y-%m-%d %H:%M:%S KST')}")
    print(f"📅 삭제 기준: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S KST')} 이전 데이터\n")

    # 경고 메시지
    if not dry_run:
        print("⚠️  경고: 이 작업은 데이터를 영구적으로 삭제합니다!")
        response = input("   계속하시겠습니까? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("❌ 작업이 취소되었습니다.")
            return
        print()

    # locations 로드
    locations = load_locations()

    # 필터링
    if target_region:
        locations = [loc for loc in locations if loc["region"] == target_region]
        print(f"🎯 지역 필터: {target_region}")

    if target_beach_id:
        locations = [loc for loc in locations if loc["beach_id"] == int(target_beach_id)]
        print(f"🎯 해변 필터: {target_beach_id}")

    if not locations:
        print("❌ 조건에 맞는 해변이 없습니다.")
        return

    print(f"📍 처리할 해변: {len(locations)}개\n")

    # 통계
    total_deleted = 0
    processed_beaches = 0
    skipped_beaches = 0

    # 각 해변 처리
    for i, loc in enumerate(locations, 1):
        region = loc["region"]
        beach_id = loc["beach_id"]
        beach_name = loc["display_name"]

        print(f"[{i}/{len(locations)}] 🌊 {region} - {beach_name} (ID: {beach_id})")

        try:
            deleted_count = get_old_forecasts(region, beach_id, cutoff_date, dry_run)

            if deleted_count > 0:
                total_deleted += deleted_count
                processed_beaches += 1
            else:
                print(f"   ✓ 삭제할 데이터 없음")
                skipped_beaches += 1

        except Exception as e:
            print(f"   ❌ 오류 발생: {e}")
            skipped_beaches += 1

        print()

    # 최종 결과
    print("=" * 60)
    print("✅ 정리 완료!")
    print(f"   {'예상 삭제' if dry_run else '삭제 완료'}: {total_deleted}개 문서")
    print(f"   처리된 해변: {processed_beaches}개")
    print(f"   건너뛴 해변: {skipped_beaches}개")
    print(f"   전체 해변: {len(locations)}개")
    print("=" * 60)

    if dry_run:
        print("\n💡 실제 삭제를 원하시면 --dry-run 없이 다시 실행하세요.")
    else:
        print(f"\n🎉 {days}일 이전 데이터가 성공적으로 삭제되었습니다!")


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="오래된 예보 데이터를 정리합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
  %(prog)s                           # 10일 지난 데이터 삭제
  %(prog)s --days 7                  # 7일 지난 데이터 삭제
  %(prog)s --dry-run                 # 미리보기 (삭제 안 함)
  %(prog)s --region busan            # 부산 지역만
  %(prog)s --beach-id 4001           # 송정 해변만
  %(prog)s --days 14 --dry-run       # 14일 지난 데이터 미리보기
        """
    )

    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="삭제할 데이터의 기준 일수 (기본: 10일)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 삭제하지 않고 미리보기만 표시"
    )

    parser.add_argument(
        "--region",
        type=str,
        help="특정 지역만 처리 (예: busan, jeju)"
    )

    parser.add_argument(
        "--beach-id",
        type=int,
        help="특정 해변만 처리 (예: 4001)"
    )

    args = parser.parse_args()

    # 유효성 검사
    if args.days < 1:
        print("❌ --days는 1 이상이어야 합니다.")
        exit(1)

    if args.days < 7:
        print("⚠️  경고: 7일 미만의 데이터를 삭제하려고 합니다.")
        print("   예보 데이터가 너무 빨리 삭제될 수 있습니다.")

    # 실행
    try:
        cleanup_old_forecasts(
            days=args.days,
            dry_run=args.dry_run,
            target_region=args.region,
            target_beach_id=args.beach_id
        )
    except KeyboardInterrupt:
        print("\n\n❌ 사용자가 작업을 중단했습니다.")
        exit(1)
    except Exception as e:
        print(f"\n❌ 예상치 못한 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
