# 두섭이 백엔드 (DoSurf Backend)

<p align="center">
  <img src="images/dosurf-backend-icon.png" width="120" alt="DoSurf Backend Icon">
</p>

<p align="center">
  <strong>해양 예보 데이터를 수집·정규화·저장하고, 장애를 감지/알림하는 서핑 백엔드</strong>
</p>

<p align="center">
  Reliable forecast pipeline for surfers.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Framework-Flask-black?logo=flask" alt="Flask">
  <img src="https://img.shields.io/badge/Deploy-Cloud%20Run-4285F4?logo=googlecloud" alt="Cloud Run">
  <img src="https://img.shields.io/badge/Database-Firestore-FFCA28?logo=firebase" alt="Firestore">
  <img src="https://img.shields.io/badge/Status-Production-brightgreen" alt="Production">
</p>

---

## 🌊 프로젝트 소개

두섭이 백엔드는 초보 서퍼가 복잡한 기상/해양 데이터를 직접 해석하지 않아도 되도록,
외부 예보 데이터를 주기적으로 수집해 앱에서 바로 쓸 수 있는 형태로 가공/저장합니다.

또한 Cloud Monitoring + Telegram 알림을 통해 장애를 빠르게 감지하고 대응할 수 있게 설계했습니다.

- **핵심 기간**: 2025.11 - 진행중
- **역할**: Backend 개발 / 운영 자동화
- **배포 환경**: GCP Cloud Run
- **레포지토리**: [piriram/DoSurf-API](https://github.com/piriram/DoSurf-API)

---

## ✨ 주요 기능

- 🛰️ **예보 수집 파이프라인** — KMA + Open-Meteo 데이터를 주기적으로 수집
- 🌐 **데이터 병합/정규화** — 앱 조회에 맞는 형태로 통합 가공
- 🗄️ **Firestore 저장 및 메타 업데이트** — 지역/해변 메타데이터와 함께 저장
- 🚨 **장애 알림** — Cloud Monitoring incident를 Telegram으로 포워딩
- 🧹 **자동 정리** — 오래된 예보 문서를 주기적으로 cleanup
- 🔐 **운영 보안 강화** — `X-Job-Token`, webhook 인증, secret scan pre-commit 훅

---

## 🛠 기술 스택

| 분류 | 기술 |
|------|------|
| Language | Python 3.12 |
| Framework | Flask |
| Infra | Cloud Run, Cloud Scheduler, Cloud Monitoring |
| Data | Firestore |
| External API | KMA, Open-Meteo, Telegram Bot API |
| Security | Basic Auth, `X-Job-Token`, gitleaks pre-commit |

---

## 🏗 아키텍처

현재 구조는 API / Service / Client / Config 레이어를 분리해,
운영 안정성을 유지하면서도 변경 범위를 작게 가져갈 수 있게 설계되어 있습니다.

```text
Cloud Scheduler
   └─ POST / (X-Job-Token)
        ↓
Cloud Run (Flask)
   ├─ app/api/routes.py            # HTTP 진입점
   ├─ app/services/collection.py   # 수집 오케스트레이션
   ├─ app/clients/alerts.py        # Telegram 알림
   └─ scripts/storage.py           # Firestore 저장/메타 갱신
```

### 데이터 플로우

```mermaid
graph LR
  A[Cloud Scheduler] --> B[POST /]
  B --> C[run_collection]
  C --> D[KMA API]
  C --> E[Open-Meteo API]
  C --> F[Firestore Save/Merge]
  C --> G[Cleanup Old Forecasts]
  H[Cloud Monitoring Incident] --> I[/monitoring-alert]
  I --> J[Telegram Alert]
```

---

## 📂 프로젝트 구조

```text
.
├── app/
│   ├── api/
│   │   └── routes.py
│   ├── services/
│   │   └── collection.py
│   ├── clients/
│   │   └── alerts.py
│   └── config/
│       └── settings.py
├── scripts/
│   ├── forecast_api.py
│   ├── open_meteo.py
│   ├── storage.py
│   ├── firebase_utils.py
│   └── alerts.py                # backward-compatible shim
├── jobs/
│   ├── api_functions.py
│   └── cleanup_old_forecasts.py
├── docs/
│   ├── DEPLOYMENT.md
│   ├── CLEANUP_GUIDE.md
│   └── REFACTORING_REPORT.md
├── api_functions.py             # jobs/api_functions.py 호환 래퍼
├── cleanup_old_forecasts.py     # jobs/cleanup_old_forecasts.py 호환 래퍼
├── server.py                    # app/api/routes.py 진입 래퍼
├── main.py                      # app/services/collection.py 진입 래퍼
└── requirements.txt
```

---

## 🔐 운영 보안 포인트

- `POST /`는 `COLLECT_JOB_TOKEN` 기반 `X-Job-Token` 인증 사용
- `/monitoring-alert`는 Basic Auth(`MONITORING_WEBHOOK_USER/PASS`) 검증
- production에서 인증값 미설정 시 요청 차단(401)
- pre-commit 단계에서 `gitleaks`로 민감정보 커밋 차단

---

## 🚀 로컬 실행

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python server.py
```

헬스체크:

```bash
curl -sS http://127.0.0.1:8080/health
```

---

## ☁️ 배포

배포 절차/환경변수는 `docs/DEPLOYMENT.md`를 참고하세요.

핵심 환경변수:

- `ENV=production`
- `COLLECT_JOB_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MONITORING_WEBHOOK_USER`
- `MONITORING_WEBHOOK_PASS`

---

## 🧾 버전 히스토리

| 버전 | 설명 | 비고 |
|------|------|------|
| v2.0 | app 레이어 분리 + 인증/알림/테스트성 강화 | 현재 |
| v1.x | 초기 수집/저장 파이프라인 | 초기 운영 |

---

## 👨‍💻 개발자

| <img alt="piriram" src="https://github.com/piriram.png" width="120"> |
|:---:|
| [piriram](https://github.com/piriram) |
| Backend / iOS |

---

## License

MIT License
