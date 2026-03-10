# 🧹 오래된 예보 데이터 정리 가이드

오래된 예보 데이터를 수동으로 삭제하는 방법입니다.

## 📋 목차

- [개요](#개요)
- [사용법](#사용법)
- [예제](#예제)
- [주의사항](#주의사항)
- [문제 해결](#문제-해결)

---

## 개요

`cleanup_old_forecasts.py` 스크립트는 Firestore에 저장된 오래된 예보 데이터를 삭제합니다.

**주요 기능:**
- ✅ 지정한 일수 이전의 예보 데이터 삭제
- ✅ 미리보기 모드 지원 (--dry-run)
- ✅ 특정 지역/해변만 선택적으로 삭제
- ✅ 배치 삭제로 안전하게 처리
- ✅ 진행 상황 실시간 표시

---

## 사용법

### 기본 실행

```bash
python cleanup_old_forecasts.py
```

**기본 동작**: 10일 이전 데이터를 삭제합니다.

### 옵션

| 옵션 | 설명 | 기본값 | 예제 |
|------|------|--------|------|
| `--days N` | N일 이전 데이터 삭제 | 10 | `--days 7` |
| `--dry-run` | 실제 삭제 없이 미리보기만 | False | `--dry-run` |
| `--region NAME` | 특정 지역만 처리 | 전체 | `--region busan` |
| `--beach-id ID` | 특정 해변만 처리 | 전체 | `--beach-id 4001` |

---

## 예제

### 1. 미리보기 (삭제하지 않고 확인만)

```bash
python cleanup_old_forecasts.py --dry-run
```

**출력 예시:**
```
============================================================
🧹 오래된 예보 데이터 정리 시작
   기준 날짜: 10일 이전 데이터 삭제
   모드: 🔍 미리보기 (삭제 안 함)
============================================================

📅 현재 시간: 2025-11-24 14:30:00 KST
📅 삭제 기준: 2025-11-14 14:30:00 KST 이전 데이터

📍 처리할 해변: 10개

[1/10] 🌊 gangreung - 정동진 (ID: 1001)
   [DRY RUN] 15개 문서 삭제 예정
     - 202511130000: 2025-11-13 00:00:00+09:00
     - 202511130300: 2025-11-13 03:00:00+09:00
     - 202511130600: 2025-11-13 06:00:00+09:00
     ... 외 12개
...
```

### 2. 실제 삭제 (10일 이전 데이터)

```bash
python cleanup_old_forecasts.py
```

실행 시 확인 메시지가 나타납니다:
```
⚠️  경고: 이 작업은 데이터를 영구적으로 삭제합니다!
   계속하시겠습니까? (yes/no): yes
```

### 3. 7일 이전 데이터 삭제

```bash
python cleanup_old_forecasts.py --days 7
```

### 4. 부산 지역만 정리

```bash
python cleanup_old_forecasts.py --region busan
```

### 5. 특정 해변만 정리

```bash
python cleanup_old_forecasts.py --beach-id 4001
```

### 6. 조합 사용

```bash
# 부산 지역의 14일 이전 데이터를 미리보기
python cleanup_old_forecasts.py --region busan --days 14 --dry-run
```

---

## 주의사항

### ⚠️ 중요한 경고

1. **영구 삭제**: 삭제된 데이터는 복구할 수 없습니다
2. **먼저 미리보기**: 항상 `--dry-run`으로 먼저 확인하세요
3. **적절한 일수**: 너무 짧은 기간(7일 미만)은 권장하지 않습니다
4. **Firebase 인증**: 올바른 Firebase 인증 정보가 필요합니다

### 📝 권장 사항

1. **첫 실행**: 항상 `--dry-run`으로 시작
   ```bash
   python cleanup_old_forecasts.py --dry-run
   ```

2. **확인 후 실행**: 미리보기 결과를 확인한 후 실제 삭제
   ```bash
   python cleanup_old_forecasts.py
   ```

3. **정기적 정리**: 월 1회 정도 실행 권장
   - 예: 매월 1일에 10일 이전 데이터 삭제

4. **지역별 순차 처리**: 대량 데이터 정리 시
   ```bash
   python cleanup_old_forecasts.py --region gangreung
   python cleanup_old_forecasts.py --region pohang
   python cleanup_old_forecasts.py --region jeju
   python cleanup_old_forecasts.py --region busan
   ```

---

## 문제 해결

### 1. Firebase 인증 오류

**에러:**
```
❌ Firebase Admin SDK가 설치되지 않았습니다.
```

**해결:**
```bash
pip install firebase-admin
```

### 2. locations.json 파일을 찾을 수 없음

**에러:**
```
❌ locations.json 파일을 찾을 수 없습니다
```

**해결:**
- 스크립트를 프로젝트 루트 디렉토리에서 실행하세요
- `scripts/locations.json` 파일이 존재하는지 확인하세요

### 3. 권한 오류

**에러:**
```
Permission denied: cleanup_old_forecasts.py
```

**해결:**
```bash
chmod +x cleanup_old_forecasts.py
```

### 4. 대량 삭제 시 시간 초과

**증상:**
- 스크립트가 매우 느리게 실행됨
- 시간 초과 오류 발생

**해결:**
- 지역별로 나누어 실행
- 또는 배치 크기를 줄여서 실행 (코드 수정 필요)

---

## 📊 실행 결과 예시

### 성공적인 실행

```
============================================================
✅ 정리 완료!
   삭제 완료: 127개 문서
   처리된 해변: 8개
   건너뛴 해변: 2개
   전체 해변: 10개
============================================================

🎉 10일 이전 데이터가 성공적으로 삭제되었습니다!
```

### 미리보기 실행

```
============================================================
✅ 정리 완료!
   예상 삭제: 127개 문서
   처리된 해변: 8개
   건너뛴 해변: 2개
   전체 해변: 10개
============================================================

💡 실제 삭제를 원하시면 --dry-run 없이 다시 실행하세요.
```

---

## 🔧 고급 사용법

### 스크립트 자동화 (cron)

주의: 자동화는 신중하게 설정하세요!

```bash
# crontab 편집
crontab -e

# 매월 1일 새벽 3시에 실행 (예시)
0 3 1 * * cd /path/to/do-surf-functions && python cleanup_old_forecasts.py --days 10
```

### Python에서 직접 호출

```python
from cleanup_old_forecasts import cleanup_old_forecasts

# 미리보기
cleanup_old_forecasts(days=10, dry_run=True)

# 실제 삭제
cleanup_old_forecasts(days=10, dry_run=False)

# 특정 지역만
cleanup_old_forecasts(days=10, target_region="busan")
```

---

## 📞 도움말

스크립트 사용 중 문제가 발생하면:

1. **도움말 보기**
   ```bash
   python cleanup_old_forecasts.py --help
   ```

2. **미리보기로 테스트**
   ```bash
   python cleanup_old_forecasts.py --dry-run
   ```

3. **GitHub 이슈 생성**
   - 문제를 재현할 수 있는 명령어
   - 오류 메시지 전체 복사
   - 환경 정보 (Python 버전, OS 등)

---

## ✅ 체크리스트

정리 작업 전에 확인하세요:

- [ ] `--dry-run`으로 미리보기 실행
- [ ] 삭제될 데이터 확인
- [ ] 적절한 일수 설정 (권장: 10일 이상)
- [ ] Firebase 인증 정보 확인
- [ ] 백업 필요 시 백업 완료

---

**Happy Cleaning!** 🧹✨
