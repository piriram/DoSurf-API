# Firestore 오래된 데이터 자동 삭제 계획

## Context

현재 `cleanup_old_forecasts.py`는 수동 실행 스크립트로, 실행 시 `input()`으로 사용자 확인을 요구합니다.
사용자는 일주일(7일) 이전 데이터를 **자동으로** 삭제하길 원합니다.

서버 흐름:
- Cloud Scheduler → Cloud Run(`/` 엔드포인트) → `server.py` → `run_collection()` (3시간마다)
- cleanup 로직을 `run_collection()` 끝에 통합하면 기존 스케줄을 그대로 활용 가능

---

## 현재 코드 상태

- `cleanup_old_forecasts()` 시그니처에 `confirm=True` 파라미터가 **이미 존재**
- 하지만 실제 `input()` 로직에서 `confirm` 값을 **체크하지 않음** (항상 확인 요청)
- `get_old_forecasts()`에 `.limit(500)` 제한이 있어 한 해변당 최대 500개만 삭제

---

## 수정 사항

### 1. `cleanup_old_forecasts.py` 수정

#### 1-1. `confirm` 파라미터 실제 적용 (Line 123)

**Before:**
```python
if not dry_run:
    print("⚠️  경고: 이 작업은 데이터를 영구적으로 삭제합니다!")
    response = input("   계속하시겠습니까? (yes/no): ")
```

**After:**
```python
if not dry_run and confirm:
    print("⚠️  경고: 이 작업은 데이터를 영구적으로 삭제합니다!")
    response = input("   계속하시겠습니까? (yes/no): ")
```

이 한 줄 변경으로 `confirm=False` 시 `input()` 없이 바로 삭제가 진행됩니다.

#### 1-2. 반복 삭제로 500개 제한 해결

현재 `get_old_forecasts()`는 `.limit(500)`으로 한 번만 쿼리합니다.
7일치 데이터가 500개를 초과할 수 있으므로, 반복 삭제 로직 추가:

```python
def get_old_forecasts(region, beach_id, cutoff_date, dry_run=False):
    clean_region = sanitize_firestore_id(region)
    beach_id_str = str(beach_id)

    collection_ref = (db.collection("regions")
                       .document(clean_region)
                       .collection(beach_id_str))

    total_deleted = 0

    while True:
        old_docs_query = (collection_ref
                           .where("timestamp", "<", cutoff_date)
                           .limit(500))

        docs = list(old_docs_query.stream())
        docs_to_delete = [doc for doc in docs if doc.id != "_metadata"]

        if not docs_to_delete:
            break

        if dry_run:
            total_deleted += len(docs_to_delete)
            print(f"   [DRY RUN] {len(docs_to_delete)}개 문서 삭제 예정")
            for doc in docs_to_delete[:3]:
                data = doc.to_dict()
                timestamp = data.get("timestamp")
                print(f"     - {doc.id}: {timestamp}")
            if len(docs_to_delete) > 3:
                print(f"     ... 외 {len(docs_to_delete) - 3}개")
            break  # dry_run은 한 번만 조회
        else:
            batch = db.batch()
            for doc in docs_to_delete:
                batch.delete(doc.reference)
            batch.commit()
            total_deleted += len(docs_to_delete)
            print(f"   🗑️  {len(docs_to_delete)}개 문서 삭제 완료")

        # 500개 미만이면 더 이상 없음
        if len(docs_to_delete) < 500:
            break

    if total_deleted > 0 and not dry_run:
        print(f"   🗑️  총 {total_deleted}개 문서 삭제 완료")

    return total_deleted
```

#### 1-3. cleanup 결과를 dict로 반환

자동화 시 결과를 API 응답에 포함시키기 위해 반환값 추가:

```python
def cleanup_old_forecasts(days=10, dry_run=False, target_region=None, target_beach_id=None, confirm=True):
    # ... 기존 로직 ...

    # 최종 결과 반환 (기존 print 유지 + return 추가)
    return {
        "deleted_documents": total_deleted,
        "processed_beaches": processed_beaches,
        "skipped_beaches": skipped_beaches,
        "total_beaches": len(locations)
    }
```

### 2. `main.py` 수정

`run_collection()` 끝에 자동 cleanup 호출 추가:

```python
from cleanup_old_forecasts import cleanup_old_forecasts

def run_collection():
    # ... 기존 수집 로직 ...

    # 7일 이전 데이터 자동 삭제
    cleanup_result = None
    print("\n🧹 7일 이전 오래된 데이터 정리 중...")
    try:
        cleanup_result = cleanup_old_forecasts(days=7, dry_run=False, confirm=False)
        print(f"🧹 정리 완료: {cleanup_result['deleted_documents']}개 문서 삭제")
    except Exception as e:
        print(f"⚠️ 데이터 정리 실패 (수집 결과에는 영향 없음): {e}")

    return {
        "total": len(locations),
        "success": successful_updates,
        "partial": partial_updates,
        "failed": failed_updates,
        "cleanup": cleanup_result
    }
```

### 3. `server.py` - 변경 없음

`server.py`는 `run_collection()`의 반환값을 그대로 JSON 응답으로 내보내므로,
`cleanup` 필드가 자동으로 포함됩니다.

---

## 수정 파일 요약

| 파일 | 변경 내용 |
|------|----------|
| `cleanup_old_forecasts.py` | `confirm` 파라미터 실제 적용, 반복 삭제 로직, dict 반환 |
| `main.py` | import 추가, `run_collection()` 끝에 cleanup 호출 |

---

## 환경 변수 설정 (선택사항)

추후 cleanup 일수를 환경 변수로 조절하고 싶다면:

```python
CLEANUP_DAYS = int(os.environ.get('CLEANUP_DAYS', '7'))
```

현재는 하드코딩 7일로 충분하므로 **나중에 필요할 때 추가**.

---

## 동작 결과

- 3시간마다 데이터 수집 완료 후 자동으로 7일 이전 데이터 삭제
- cleanup 실패 시 예외를 잡아서 수집 결과에는 영향 없음
- 기존 수동 스크립트도 그대로 동작 유지 (backward compatible)
- API 응답에 cleanup 결과가 포함되어 모니터링 가능
- 500개 초과 데이터도 반복 삭제로 완전 처리

---

## 검증 방법

1. 로컬에서 `python cleanup_old_forecasts.py --dry-run --days 7`로 삭제 대상 확인
2. 로컬에서 `python main.py` 실행 → cleanup 로그 출력 확인
3. Cloud Run 배포 후 다음 스케줄 실행 시 로그에서 cleanup 결과 확인
4. API 응답의 `cleanup` 필드로 삭제된 문서 수 확인

---

## 리스크 & 대응

| 리스크 | 대응 |
|--------|------|
| cleanup이 오래 걸려서 다음 스케줄과 겹침 | Cloud Run은 요청 단위로 실행되므로 겹쳐도 문제 없음 |
| Firestore 배치 한도 (500개/배치) 초과 | 반복 삭제 로직으로 해결 |
| cleanup 중 에러 발생 | try/except로 수집 결과에 영향 없도록 격리 |
| 실수로 최근 데이터 삭제 | `days=7` 하드코딩 + `cutoff_date` 기반 쿼리로 안전 |
