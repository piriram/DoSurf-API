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

### 새로 발견한 것 — 결측이 0.5m 파도가 된다

방어 코드가 오히려 다른 문제를 만든다.

```python
# scripts/storage.py:135
(float(raw_wave_height) if raw_wave_height is not None else 0.0) + WAVE_HEIGHT_OFFSET
```

Open-Meteo가 파고를 주지 않은 시각(`None`)에 **`0.0 + 0.5 = 0.5`가 저장된다.**
데이터가 없는 것과 파도가 0.5m인 것이 구별되지 않는다.
크래시보다 조용해서 더 오래 남는 종류의 문제다.

보정을 제거하면 이 문제도 함께 사라진다 — `None`은 `None`으로 저장하면 된다.

---

## 이 저장소에서 할 일

### Phase 1 — 스키마를 깨지 않는 수정

iOS는 Firestore 문서를 딕셔너리 접근으로 읽으므로 필드를 추가해도 앱이 깨지지 않는다.
기존 평면 필드 이름을 유지하면 **백엔드를 먼저 배포해도 된다.**

| 대상 | 작업 |
|---|---|
| `config.json` | `storage.wave_height_offset` 제거, `marine.region_models` 추가 |
| `scripts/config.py` | `get_wave_height_offset()` 제거, 모델 설정 접근자 추가 |
| `scripts/storage.py:135` | 보정 제거, `None` 유지, `wave`/`tide`/`marine_source` 저장 |
| `scripts/open_meteo.py` | 지역별 모델 + 폴백 이중 호출, 파주기·스웰·조석, 값 검증, 격자 기록, 재시도 |
| `app/services/collection.py:60` | 예보 범위를 KST 기준으로 |
| `app/services/collection.py:125` | `fetch_marine`에 `region` 전달, 반환된 메타를 저장에 넘김 |
| `scripts/timeutil.py` | 신규 — naive KST 헬퍼 |
| `scripts/model_compare.py` | 신규 — Windfinder 대조 도구 |

**모델 선택** (근거는 `marine-data-audit.md` 「2차 검증」):

```
동해(yangyang·gangneung·sokcho·pohang)  ncep_gfswave025    속초 MAE 0.560 → 0.018
jeju                                     ecmwf_wam025       제주 MAE 0.150 → 0.075
busan · west_south                       기본값 유지 (대조 데이터 없음)
```

표본이 2일치뿐이라 **코드가 아니라 `config.json`에만 둔다.**

### 배포 전 확인

- [ ] `KMA_API_KEY` 있는 환경에서 수집 1회 — 조사 세션에서 한 번도 못 돌렸다
- [ ] Firestore 실제 쓰기 확인 (조사 때는 스텁으로만 검증)
- [ ] **기상청 `WAV`가 얼마나 채워지는지** — iOS가 파고를 기상청 우선으로 읽어서,
      이 답에 따라 Phase 1의 사용자 체감 효과가 갈린다 (`ios-migration.md` P0)
- [ ] 보정 제거로 인한 화면 값 변화 공지 여부

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
