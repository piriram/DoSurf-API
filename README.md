# DoSurf API Backend

DoSurf 서핑 예보 백엔드입니다.

이 저장소는 크게 **3가지 역할**을 수행합니다.

1. **예보 수집/병합 파이프라인**
   - 기상청(KMA) + Open-Meteo 데이터를 수집
   - 해변별 예보를 병합/정규화
   - Firestore 저장 + 메타데이터 업데이트 + 캐시 무효화
2. **실행 엔드포인트(Cloud Run)**
   - 스케줄러/수동 호출로 수집 실행
   - 헬스체크
   - Cloud Monitoring Webhook 수신 후 Telegram 포워딩
3. **조회 API(Firebase HTTP Functions)**
   - 지역/해변 목록 조회
   - 해변 메타데이터 조회

---

## 아키텍처 개요

```text
Cloud Scheduler
   └─(POST /)──────────────────────┐
                                   ▼
                         Cloud Run (server.py)
                           ├─ app/api/routes.py
                           │   ├─ run_collection() (app/services/collection.py)
                           │   │   ├─ KMA API
                           │   │   ├─ Open-Meteo API
                           │   │   └─ Firestore 저장
                           │   ├─ /health
                           │   └─ /monitoring-alert
                           └─ Telegram 알림(app/clients/alerts.py)

Client App
   └─ Firebase HTTP Functions (api_functions.py)
       ├─ get_all_locations
       ├─ get_regions
       ├─ get_beaches_by_region
       └─ get_beach_info
```

---

## 주요 파일 구조

```text
.
├── server.py                  # Cloud Run 진입점(호환용, app/api/routes.py 사용)
├── main.py                    # 배치 진입점(호환용, app/services/collection.py 사용)
├── app/
│   ├── api/routes.py          # Flask 라우트(/, /health, /monitoring-alert)
│   ├── services/collection.py # 수집 메인 로직(run_collection)
│   ├── clients/alerts.py      # Telegram 장애 알림
│   └── config/settings.py     # 실행 설정/상수
├── api_functions.py           # Firebase HTTP Functions
├── cleanup_old_forecasts.py   # 오래된 예보 정리 스크립트
├── config.json                # 수집/저장 설정
├── scripts/
│   ├── forecast_api.py        # 기상청 API 연동 + fallback
│   ├── open_meteo.py          # Open-Meteo API 연동
│   ├── storage.py             # Firestore 저장/조회
│   ├── beach_registry.py      # locations 로딩/해변 메타
│   ├── firebase_utils.py      # Firebase 초기화(lazy)
│   ├── cache_utils.py         # 인메모리 캐시
│   ├── path_utils.py          # Firestore 경로 sanitize
│   └── alerts.py              # 호환용 import shim
├── private/                   # 민감정보 폴더(Git 제외)
│   └── README.md
├── DEPLOYMENT.md              # Cloud Run 배포 가이드
└── requirements.txt
```

---

## 실행 엔드포인트 (Cloud Run)

### `POST /`
예보 수집 트리거 엔드포인트.

- 요청 헤더 `X-Job-Token` 필요 (`COLLECT_JOB_TOKEN`과 일치)
- production에서 토큰 미설정/불일치 시 401 반환
- 성공 시 200 + 결과 JSON 반환
- 전체 위치가 모두 실패하면 500 반환 (모니터링 감지 목적)

### `GET /health`
헬스체크 엔드포인트.

```json
{"status":"healthy"}
```

### `POST /monitoring-alert`
Cloud Monitoring Webhook 수신 엔드포인트.

- incident payload를 Telegram으로 포워딩
- `MONITORING_WEBHOOK_USER/PASS` 설정 시 Basic Auth 검증

---

## 조회 API (Firebase Functions)

> 구현 파일: `api_functions.py`

- `get_all_locations`
  - 전체 지역 + 해변 목록 반환
- `get_regions`
  - 지역 목록 반환
- `get_beaches_by_region?region=<region>`
  - 특정 지역 해변 목록 반환
- `get_beach_info?region=<region>&beach_id=<id>`
  - 특정 해변 메타데이터 반환

응답 공통:
- JSON 응답
- CORS 허용(`*`)
- 캐시 사용 시 `X-Cache` 헤더(HIT/MISS)

---

## 로컬 개발

### 1) 의존성 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install firebase-functions
```

### 2) 문법 체크

```bash
python3 -m py_compile \
  main.py server.py api_functions.py cleanup_old_forecasts.py \
  scripts/storage.py scripts/beach_registry.py scripts/firebase_utils.py \
  scripts/forecast_api.py scripts/open_meteo.py scripts/path_utils.py scripts/alerts.py
```

### 3) 로컬 서버 실행

```bash
python server.py
```

테스트:

```bash
curl -sS http://127.0.0.1:8080/health
curl -sS -X POST http://127.0.0.1:8080/
```

---

## 배포 (Cloud Run)

상세 절차는 `DEPLOYMENT.md` 참고.

빠른 배포:

```bash
gcloud config set project dosurf-api
gcloud config set run/region asia-northeast3

gcloud run deploy do-surf-functions \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --quiet
```

배포 후 확인:

```bash
curl -sS https://do-surf-functions-900402500777.asia-northeast3.run.app/health
```

---

## 운영/모니터링

### Telegram 장애 알림

필수 환경변수:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

선택(모니터링 웹훅 인증):
- `MONITORING_WEBHOOK_USER`
- `MONITORING_WEBHOOK_PASS`

### 알림 정책

Cloud Monitoring 정책으로 다음을 감시:
- KMA API Key 누락
- 수집 전체 실패
- Cloud Run 5xx
- Deadman (성공 로그 장시간 미유입)

현재 Deadman 정책은 스케줄 공백을 고려해 **14시간** 기준으로 설정됨.

---

## 민감정보/보안

민감정보는 `private/` 폴더에 보관하고 Git에 커밋하지 않습니다.

Firebase 키 탐색 순서:
1. `private/keys/serviceAccountKey.json` (권장)
2. `private/serviceAccountKey.json`
3. `secrets/serviceAccountKey.json` (legacy)

---

## 트러블슈팅

### 1) deadman 알림이 자주 뜰 때
- Cloud Scheduler 주기/실패 여부 확인
- deadman duration이 스케줄 공백보다 짧지 않은지 확인

### 2) `/monitoring-alert` 401 발생
- Basic Auth 설정값(`MONITORING_WEBHOOK_USER/PASS`)과
  webhook notifier 인증 정보가 일치하는지 확인

### 3) 수집은 되는데 일부 데이터만 저장될 때
- KMA 응답 완전성(아이템 수) 확인
- Open-Meteo 호출 상태 확인
- 로그에서 partial 저장 메시지 확인

---

## 라이선스

내부 프로젝트 기준으로 운영 중입니다. 필요 시 별도 라이선스 정책을 추가하세요.
