# 해상 데이터 정확도 개선 — 이 저장소 기준 재검토

조사는 `piriram/do-surf-functions`에서 진행했다. 그 저장소가 현행이 아니라는 것을
뒤늦게 확인해서, **모든 발견을 이 저장소의 실제 코드에 다시 대조했다.**

- 측정값과 근거: [`marine-data-audit.md`](./marine-data-audit.md)
- iOS 수정 사항: [`ios-migration.md`](./ios-migration.md)
- 차트 포함 읽기용: [`marine-data-audit.html`](./marine-data-audit.html)

> **주의**: `marine-data-audit.md`와 `.html`의 `file:line` 참조는 **조사 당시 저장소 기준**이다.
> 이 저장소에서의 위치는 아래 재검토 표를 볼 것.
> 측정값(Open-Meteo 응답, Windfinder 대조, 모델별 오차)은 저장소와 무관하게 유효하다.

---

## 재검토 결과

`845aa3c` 기준으로 발견 하나하나를 다시 확인했다.

| 발견 | 이 저장소에서의 상태 | 위치 |
|---|---|---|
| **파고 `+0.5` 일괄 보정** | ✅ **유효** — 설정으로 빠졌을 뿐 값은 그대로 | `config.json` `storage.wave_height_offset: 0.5` → `scripts/storage.py:17,135` |
| **결측 파고가 0.5m로 저장** | 🆕 **새로 발견** | `scripts/storage.py:135` |
| **예보 범위 9시간 잘림 (UTC/KST)** | ✅ **유효** | `app/services/collection.py:60` |
| **파주기·스웰·조석 미수집** | ✅ **유효** | `scripts/open_meteo.py:28` |
| **격자 스냅 / 지역별 모델 미적용** | ✅ **유효** | `scripts/open_meteo.py:35` |
| **출처·격자 좌표 미기록** | ✅ **유효** | `scripts/storage.py`, `app/services/collection.py:125` |
| **Open-Meteo 재시도 미구현** | ✅ **유효** — `config.json`에 `open_meteo_retry_count: 3`이 선언만 되어 있고 코드가 참조하지 않는다 | `scripts/open_meteo.py` |
| **기상청 값 범위 검증 없음** | ✅ **유효** — `float()` 변환만 한다 | `scripts/storage.py:70` |
| **`firebase.json`이 없는 `functions/` 참조** | ✅ **유효** | `firebase.json` |
| **`api_functions.py` 미연결** | ⚠️ **부분** — `jobs/`로 정리됐지만 `firebase_functions`가 `requirements.txt`에 여전히 없다 | `jobs/api_functions.py` |
| ~~`None + 0.5` → `TypeError`~~ | ❌ **무효** — 여기선 이미 방어되어 있다 | — |
| ~~`main.py`/`server.py` 수집 루프 중복~~ | ❌ **무효** — 둘 다 얇은 래퍼고 로직은 한 곳뿐이다 | — |

### 무효가 된 두 가지

`do-surf-functions`에서 찾았던 결함 중 둘은 이 저장소에서 이미 해결되어 있었다.

**`None + 0.5` 크래시** — `(float(x) if x is not None else 0.0) + WAVE_HEIGHT_OFFSET`로
방어되어 있다. 저쪽의 `r.get(k, 0) + 0.5`는 값이 `None`일 때 터졌다.

**수집 루프 중복** — `main.py`(9줄)와 `server.py`(12줄)가 모두 얇은 래퍼이고
실제 로직은 `app/services/collection.py` 한 곳에 있다. 저쪽은 같은 루프가 두 파일에 복사돼 있었다.

### 「새로 발견」이라고 했던 것 — 실측으로 등급을 낮춘다

방어 코드가 오히려 다른 문제를 만든다.

```python
# scripts/storage.py:135
(float(raw_wave_height) if raw_wave_height is not None else 0.0) + WAVE_HEIGHT_OFFSET
```

Open-Meteo가 파고를 주지 않은 시각(`None`)에 `0.0 + 0.5 = 0.5`가 저장된다.
데이터 없음과 파도 0.5m가 구별되지 않는다.

**다만 실제로는 발생하지 않고 있었다.** 현재 운영 파라미터(`best_match`, 3개 항목)로
해변 32곳 × 5일 = **3840개 시각을 조회했더니 파고 결측이 0건(0.00%)** 이었다.
코드상 열려 있지만 실제로는 안 밟히는 경로다.

단 Phase 1에서 지역별 모델로 바꾸면 상황이 달라진다 —
`ecmwf_wam025` 같은 모델은 결측이 생길 수 있어 그때는 이 경로가 열린다.
보정을 제거하면서 `None`을 `None`으로 저장하면 함께 해결된다.

---

## 이 저장소에서 할 일

### Phase 1 — 구현 완료 (배포 전)

브랜치 `claude/marine-data-accuracy`. 스키마를 깨지 않는 범위의 수정이다.

iOS는 Firestore 문서를 딕셔너리 접근으로 읽으므로 필드를 추가해도 앱이 깨지지 않는다.
기존 평면 필드 이름을 유지하면 **백엔드를 먼저 배포해도 된다.**

| 대상 | 작업 |
|---|---|
| `config.json` | `storage.wave_height_offset` 제거, `marine.region_models` 추가 |
| `scripts/config.py` | `get_wave_height_offset()` 제거, 모델 설정 접근자 추가 |
| `scripts/storage.py:135` | 보정 제거, `None` 유지, `wave`/`tide`/`marine_source` 저장 |
| `scripts/open_meteo.py` | 지역별 모델 + 폴백 이중 호출, 파주기·스웰·조석, 값 검증, 격자 기록, 재시도 |
| `app/services/collection.py:64` | 예보 범위를 KST 기준으로 |
| `app/services/collection.py:129` | `fetch_marine`에 `region` 전달, 반환된 메타를 저장에 넘김 |
| `scripts/forecast_api.py:68` | **기상청 발표시각 선택을 KST 기준으로** (아래 참조) |
| `scripts/timeutil.py` | 신규 — naive KST 헬퍼 |
| `scripts/model_compare.py` | 신규 — Windfinder 대조 도구 |

**모델 선택** — 3일치 대조로 결정했다 (Windfinder 대비 파고 MAE).

| 모델 | 속초 8/26 | 8/28 | 8/29 | 평균 |
|---|---|---|---|---|
| **`ncep_gfswave016`** | **0.090** | 0.065 | **0.065** | **0.073** |
| `ncep_gfswave025` | 0.108 | **0.018** | 0.135 | 0.087 |
| `gwam` | 0.155 | 0.082 | 0.253 | 0.163 |
| `best_match` (기존) | 0.190 | 0.070 | 0.255 | 0.172 |
| 기존 저장값 (`+0.5`) | 0.360 | 0.560 | 0.450 | **0.457** |

```
동해(yangyang·gangneung·sokcho·pohang)  ncep_gfswave016   3일 평균 0.457 → 0.073
jeju                                     보류 (best_match) 아래 참조
busan · west_south                       보류 (대조 데이터 없음)
```

**제주는 보류했다.** 3일간 1위가 매일 바뀐다 — 8/26 `ncep025`, 8/28 `ecmwf_wam025`,
8/29 `best_match`. 지금 고르면 동전 던지기다.
`+0.5`만 제거해도 8/29 기준 0.385 → 0.115로 개선되므로 서두를 이유가 없다.

파주기 오차도 제주가 유독 크다 — 속초는 최선 모델이 0.26초인데 제주는 어느 모델도 1.35초 이상 틀린다.
격자가 18~26km 밖이라 그런 것으로 보이고, 좌표로는 못 좁힌다는 것이 이미 확인됐다.

표본이 며칠치뿐이라 **모델은 코드가 아니라 `config.json`에만 둔다.**

#### 시간대 버그는 두 개였다

`datetime.now()`가 UTC라는 같은 원인인데 증상이 둘이다.

**① 예보 범위 9시간 잘림** (`app/services/collection.py:64`) — 3일치 요청이 2일 15시간만 저장됐다.

**② 기상청 발표를 한 단계 전 것으로 요청** (`scripts/forecast_api.py:68`) — 재검토 중 새로 찾았다.
발표시각(02·05·…·23)은 KST 기준인데 UTC 시각으로 골라서 **매번 9시간 묵은 발표**를 받고 있었다.
검증한 8개 시각에서 8번 다 어긋났고, 날짜 경계에서는 전날 발표를 가져왔다.
기상청이 지난 발표도 응답해 주기 때문에 에러 없이 조용히 낡은 값을 쓰고 있었다.

스케줄이 정시+15분인 이유가 최신 발표를 받으려는 것인데 정작 그걸 못 받고 있었다.
**iOS가 파고를 기상청 우선으로 읽으므로 화면 값에 직접 영향을 준다.**

수정 후 KST 17:41에 `('20260829', '1700')`을 고르는 것을 확인했다 (수정 전이면 `0800`).

### 검증 (Firebase 스텁 + 실제 API)

- `om_wave_height` 0.72 그대로 저장 — 보정 제거 확인
- 결측 입력에 `None` 저장 — 0.5로 둔갑하지 않음
- 예보 범위 69시간 (수정 전 60시간)
- 죽도 → `ncep_gfswave016` 격자 7.17km, 수온·조석은 폴백에서 채움
- 함덕 → `best_match` (보류 결정대로)
- 발표시각 KST 기준 선택 확인

**검증 못 한 것**: `KMA_API_KEY`가 없어 기상청 실제 응답 경로, Firestore 실제 쓰기.

### 배포 전 확인

- [ ] `KMA_API_KEY` 있는 환경에서 수집 1회 — 조사 세션에서 한 번도 못 돌렸다
- [ ] Firestore 실제 쓰기 확인 (조사 때는 스텁으로만 검증)
- [ ] **기상청 `WAV`가 얼마나 채워지는지** — iOS가 파고를 기상청 우선으로 읽어서,
      이 답에 따라 Phase 1의 사용자 체감 효과가 갈린다 (`ios-migration.md` P0)
- [ ] 화면 값 변화 공지 여부 — 보정 제거와 발표시각 수정을 **한 번에 배포**하기로 했으므로
      기상청 파고와 Open-Meteo 파고가 동시에 바뀐다
- [ ] **Open-Meteo 출처 표기** — 무료 티어는 CC BY 4.0이라 표기 의무가 있다.
      앱에 "Weather data by Open-Meteo.com"이 있는지 확인할 것 (비상업 용도 확인됨)

### Phase 2 — 스키마와 해변별 구분

- `wave`/`tide` 계층 스키마로 전환, 옛 평면 필드 삭제 (`merge=True`라 명시적으로 지워야 한다)
- `locations.json`에 `shore_normal_deg`·`swell_window_deg` 추가 → 해변별 노출도 변환
  (**32개 방위각은 좌표만으로 못 뽑는다. 스팟을 아는 사람의 검수가 필요하다.**)
- 저장 단위를 일별 1문서로 (읽기 24회 → 1회, 동시에 1시간 해상도)
- 파주기 앱 노출 — 파주기 기준 대조를 마친 뒤에

### 기술 부채

- [ ] `firebase.json`이 없는 `functions/` (nodejs20)를 참조한다
- [ ] `jobs/api_functions.py`가 `firebase_functions`를 import하는데 `requirements.txt`에 없다
- [ ] 기상청 파싱에 값 범위 검증이 없다 (`scripts/storage.py:70`).
      iOS가 `wave_height`의 `-900`/`900` 센티넬을 거르고 있는 걸 보면 실제로 그런 값이 온 적이 있다
- [ ] 테스트가 없다

---

## 이 저장소에서 활용할 수 있는 것

조사 저장소에는 없던 것들이다.

**텔레그램 장애 알림** (`app/clients/alerts.py`) — 수집 실패를 이미 알린다.
모델 대조 결과가 크게 어긋날 때도 여기에 태울 수 있다.

**`config.json` 설정 체계** — 이미 `storage.wave_height_offset`을 설정으로 빼는 구조가 있다.
지역별 모델도 같은 방식으로 넣으면 자연스럽다.

**`app/` 레이어 분리** — 수집 로직이 `app/services/collection.py` 한 곳이라
조사 저장소처럼 같은 수정을 두 번 할 일이 없다.

---

## 결정된 것 / 아직 안 정한 것

**결정됨** (근거는 `marine-data-audit.md`)

- 기준은 부이 실측이 아니라 **Windfinder**다
- 해변별 `marine_lat/marine_lon` 수동 지정은 **효과 없음이 실측으로 확인**돼 폐기했다
- 모델은 **지역별로 다르게** 쓴다. `ncep`으로 통일하지 않는다

**아직 안 정함**

- 제주 모델: `ecmwf_wam025`(정확도 높음, 스웰 분해 없음) vs `gwam`(약간 낮음, 데이터 일관)
- 해변별 값을 계산해서 보여줄 것인가 (양양 6곳이 같은 값인 문제)
- `shore_normal_deg` 32개를 누가 채울 것인가
