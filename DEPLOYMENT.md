# DoSurf-API 배포 가이드

이 문서는 **Cloud Run 기준**으로 `do-surf-functions` 서비스를 배포하는 방법을 정리합니다.

---

## 0) 배포 대상 정보

- **서비스명**: `do-surf-functions`
- **프로젝트**: `dosurf-api`
- **리전**: `asia-northeast3`
- **배포 방식**: 소스 기반 배포 (`--source .`, Dockerfile 사용)

---

## 1) 사전 준비

### 1-1. gcloud 로그인 및 프로젝트 설정

```bash
gcloud auth login
gcloud config set project dosurf-api
gcloud config set run/region asia-northeast3
```

### 1-2. 필요한 API 활성화 (최초 1회)

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

### 1-3. 레포 최신 상태 확인

```bash
cd /Users/ram/25-2/do-surf-functions
git status
git pull
```

### 1-4. 민감정보(키) 위치 확인

- 로컬 키 파일은 `private/keys/` 아래에 둡니다.
- 예: `private/keys/serviceAccountKey.json`

---

## 2) 배포 전 체크리스트

아래가 통과되면 배포 진행:

```bash
python3 -m py_compile main.py server.py api_functions.py cleanup_old_forecasts.py \
  app/api/routes.py app/services/collection.py app/clients/alerts.py app/config/settings.py \
  scripts/storage.py scripts/beach_registry.py scripts/add_location.py \
  scripts/firebase_utils.py scripts/forecast_api.py scripts/config.py \
  scripts/open_meteo.py scripts/path_utils.py scripts/alerts.py
```

- 문법 오류 없음
- 브랜치/커밋 상태 확인

### 2-1) Telegram 장애 알림 환경변수(선택)

문제 발생 시 iPhone Telegram 알림을 받으려면 아래 환경변수를 설정하세요.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- (권장) `ENV=production`
- (필수 권장) `MONITORING_WEBHOOK_USER`, `MONITORING_WEBHOOK_PASS`  
  Cloud Monitoring Webhook(`/monitoring-alert`) 인증에 사용 (production에서 미설정 시 401)

```bash
gcloud run services update do-surf-functions \
  --region asia-northeast3 \
  --update-env-vars "TELEGRAM_BOT_TOKEN=<bot_token>,TELEGRAM_CHAT_ID=<chat_id>"
```

---

## 3) 배포 실행

프로젝트 루트에서 실행:

```bash
gcloud run deploy do-surf-functions \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --quiet
```

성공 시 마지막에 아래 형태로 URL이 출력됩니다:

- `Service URL: https://<service>-<hash>.asia-northeast3.run.app`

---

## 4) 배포 후 검증

### 4-1. 헬스체크

```bash
curl -sS https://do-surf-functions-900402500777.asia-northeast3.run.app/health
```

정상 응답 예시:

```json
{"status":"healthy"}
```

### 4-2. 리비전 확인

```bash
gcloud run revisions list --service do-surf-functions --region asia-northeast3
```

### 4-3. 트래픽 확인

```bash
gcloud run services describe do-surf-functions \
  --region asia-northeast3 \
  --format='value(status.traffic)'
```

---

## 5) 롤백 방법

문제가 있을 때 이전 리비전으로 트래픽 전환:

```bash
gcloud run services update-traffic do-surf-functions \
  --region asia-northeast3 \
  --to-revisions <이전리비전명>=100
```

예: `do-surf-functions-00000-abc=100`

---

## 6) 운영 팁

- 배포 직전에는 `git status`를 항상 확인
- 배포 성공 후 `/health`는 반드시 체크
- 장애 시 먼저 리비전 롤백하고 원인 분석
- 스케줄러를 쓰는 경우, 대상 URL이 최신 서비스 URL인지 확인

---

## 7) 빠른 배포 요약 (복붙용)

```bash
cd /Users/ram/25-2/do-surf-functions

gcloud config set project dosurf-api
gcloud config set run/region asia-northeast3

gcloud run deploy do-surf-functions \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --quiet

curl -sS https://do-surf-functions-900402500777.asia-northeast3.run.app/health
```
