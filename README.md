# DoSurf Functions

DoSurf 서핑 예보 백엔드 저장소입니다.

기능은 크게 2가지입니다.
- **예보 수집 파이프라인**: `main.py` (KMA + Open-Meteo 수집/병합/저장)
- **실행 엔드포인트**: `server.py` (Cloud Run에서 수집 트리거), `api_functions.py` (Firebase HTTP 함수)

---

## 폴더 구조

```text
do-surf-functions/
├── main.py                    # 수집 메인 로직(run_collection)
├── server.py                  # Flask 엔드포인트 (/ , /health)
├── api_functions.py           # Firebase HTTP 함수들
├── cleanup_old_forecasts.py   # 오래된 예보 정리 스크립트
├── config.json                # 수집/저장 설정
├── scripts/
│   ├── forecast_api.py        # 기상청 API 연동
│   ├── open_meteo.py          # Open-Meteo API 연동
│   ├── storage.py             # Firestore 저장/조회
│   ├── beach_registry.py      # 해변 메타데이터/locations 로딩
│   ├── firebase_utils.py      # Firebase 초기화(lazy)
│   ├── cache_utils.py         # 인메모리 캐시
│   ├── path_utils.py          # Firestore 경로 sanitize
│   └── locations.json         # 해변 마스터 데이터
├── private/                   # 민감정보 전용 폴더(키/토큰)
│   └── README.md
├── DEPLOYMENT.md              # 배포 상세 가이드
└── requirements.txt
```

---

## 민감정보 관리(중요)

이 저장소는 **Git에 올리면 안 되는 파일을 `private/` 한 폴더로 관리**합니다.

- 권장 위치: `private/keys/serviceAccountKey.json`
- `.gitignore`에서 `private/README.md`만 추적, 나머지는 무시
- 기존 `secrets/` 경로도 레거시 호환으로만 유지

Firebase 로컬 초기화 키 탐색 순서:
1. `private/keys/serviceAccountKey.json` (권장)
2. `private/serviceAccountKey.json`
3. `secrets/serviceAccountKey.json` (legacy)

---

## 로컬 실행

### 1) 의존성 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install firebase-functions
```

### 2) 문법 체크

```bash
python3 -m py_compile main.py server.py api_functions.py cleanup_old_forecasts.py \
  scripts/storage.py scripts/beach_registry.py scripts/add_location.py \
  scripts/firebase_utils.py scripts/forecast_api.py scripts/config.py \
  scripts/open_meteo.py scripts/path_utils.py
```

### 3) 로컬 서버 실행

```bash
python server.py
```

- 수집 트리거: `GET/POST /`
- 헬스체크: `GET /health`

---

## 배포

Cloud Run 배포 절차는 `DEPLOYMENT.md` 참고.

핵심 명령만 빠르게 보면:

```bash
gcloud run deploy do-surf-functions \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --quiet
```

배포 후:

```bash
curl -sS https://<service-url>/health
```

---

## 운영 팁

- 배포 전 `git status` / `py_compile` 확인
- `config.json` 변경 시 수집 정책(시간대, 일수, 파고 오프셋) 같이 점검
- 이슈 발생 시 Cloud Run 리비전 롤백 우선
