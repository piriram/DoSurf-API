# iOS에서 고쳐야 할 것

대상: [`piriram/DoSurf-iOS`](https://github.com/piriram/DoSurf-iOS) (`dbc6ac4` 기준)

백엔드 Phase 1이 배포되면 iOS도 손봐야 한다. **깨지지는 않지만, 고치지 않으면
Phase 1의 개선이 사용자에게 도달하지 않는다.**

배경은 [`marine-data-audit.md`](./marine-data-audit.md), 백엔드 작업은 [`marine-data-plan.md`](./marine-data-plan.md).

---

## 먼저 안심할 것 — 앱은 깨지지 않는다

iOS는 Firestore 문서를 `Codable`이 아니라 **딕셔너리 접근**으로 읽는다.

```swift
// FirestoreRepository.swift:115
let rawWaveHeight = data["wave_height"] as? Double
```

그래서 Phase 1이 새로 넣는 `wave`, `tide`, `marine_source` 필드는 **조용히 무시된다.**
디코딩 실패도, 크래시도 없다. 기존 평면 필드(`om_wave_height` 등)는 이름을 그대로 두었다.

즉 **백엔드를 먼저 배포하고 iOS를 나중에 고쳐도 된다.** 순서 제약이 없다.

---

## 지금 iOS가 실제로 하는 일

`FirestoreRepository.swift:110~155`와 `FirestoreChartDTO.swift:24~49`를 읽은 결과다.

| 화면에 보이는 값 | 어디서 오나 |
|---|---|
| 파고 | `wave_height`(기상청) **우선**, 없으면 `om_wave_height` |
| 파향 | `om_wave_direction` |
| 수온 | `om_sea_surface_temperature` |
| **파주기** | **어디서도 안 온다 — 풍속으로 만들어낸 추정치** |
| 날씨 아이콘 | `sky_condition`·`precipitation_type`으로 iOS가 계산 |

---

## P0 · 파고 우선순위를 뒤집어야 한다

### 문제

```swift
// FirestoreChartDTO.swift:38
waveHeight: waveHeight ?? omWaveHeight ?? 0.0
//           ^^^^^^^^^^ 기상청 wave_height 가 먼저다
```

Phase 1에서 우리가 검증하고 개선한 것은 **`om_wave_height` 쪽**이다.
Windfinder 대조도, 지역별 모델 선택도, `+0.5` 제거도 전부 Open-Meteo 값에 대한 것이다.

**기상청 `wave_height`가 있는 시각에는 iOS가 그 값을 쓰므로 Phase 1의 개선이 보이지 않는다.**

이건 백엔드 조사 단계에서 놓쳤던 부분이다. `+0.5` 제거로 "동해 잔잔한 날 0.7m → 0.2m로
떨어진다"고 했던 예측도 **기상청 파고가 없는 시각에만 해당된다.**

### 확인이 먼저 필요하다

기상청 단기예보가 우리 해변 격자에 `WAV`(파고)를 얼마나 자주 주는지 모른다.
`KMA_API_KEY`가 있는 환경에서 확인해야 한다.

- `WAV`가 대부분 있다 → Phase 1의 사용자 체감 효과가 거의 없다. **P0가 급해진다.**
- `WAV`가 거의 없다 → 이미 `om_wave_height`를 쓰고 있으므로 Phase 1 효과가 바로 나타난다.

Firestore에서 아무 해변 문서 몇 개를 열어 `wave_height` 필드 유무만 봐도 판단할 수 있다.

### 고칠 방향

Open-Meteo를 우선으로 뒤집는다.

```swift
waveHeight: omWaveHeight ?? waveHeight ?? 0.0
```

다만 **그냥 뒤집기 전에 기상청 파고와 Open-Meteo 파고를 같은 시각에 비교해 볼 것.**
둘이 크게 다르면 화면 값이 눈에 띄게 변한다. 백엔드에서 두 값이 나란히 저장되고 있으니
Firestore를 그대로 조회하면 된다.

Phase 2에서 `wave.height_m`로 옮기면 이 분기 자체가 사라진다.

---

## P1 · 파주기는 지금 만들어낸 숫자다

### 문제

앱은 파주기를 **표시하고 있다.**

- `ChartTableViewCell.swift:218` — `String(format: "%.1fs", chart.wavePeriod)`
- `PageChartRowView.swift:314, 355`
- `DashboardViewModel.swift:119`
- `WatchDataSyncCoordinator.swift:144` — Apple Watch로도 보낸다

그런데 그 값의 출처가 이것이다.

```swift
// FirestoreRepository.swift:262
// Pierson–Moskowitz fully developed sea approximation:
// Tp ≈ 0.83 * U10 (seconds), clamp to a reasonable surf range
let raw = 0.83 * u          // u = 풍속
let clamped = max(2.0, min(18.0, raw))
```

**풍속만으로 계산한 추정치다.** 파랑 모델의 값이 아니다.
백엔드가 파주기를 준 적이 없어서 이렇게 되어 있었다.

이게 왜 문제냐면 — 조사에서 확인했듯이 같은 파고 0.3m라도
주기 8.6초와 16.8초는 완전히 다른 날이다. 풍속에서 유도한 값은
**먼바다에서 들어오는 그라운드 스웰을 원리적으로 표현하지 못한다.**
바람이 약한 날 롱 스웰이 들어와도 앱은 짧은 주기를 표시한다.

### 고칠 방향

Phase 1부터 백엔드가 **실제 파주기를 저장한다.**

```
wave.period_s              총 파주기
wave.swell.period_s        스웰 성분
wave.wind_wave.period_s    풍파 성분
```

중첩 맵이라 읽는 방법이 다르다.

```swift
let wave = data["wave"] as? [String: Any]
let wavePeriod = wave?["period_s"] as? Double
```

`estimateWavePeriod`는 **폴백으로만 남기거나 지운다.** 추정값과 실제값이 섞이면
어느 쪽인지 알 수 없으니, 폴백으로 남긴다면 화면에서 구분할 수 있어야 한다.

### 단, 바로 켜지 말 것

백엔드 문서에도 적어둔 주의사항이다. **파고로 고른 모델이 파주기까지 맞는다는 보장이 없다.**
제주 8/28 기준 Windfinder는 10~11초인데 우리가 채택한 `ecmwf_wam025`는 5.4~7.3초였다.

파주기 노출은 백엔드 Phase 2에서 파주기 기준 대조를 마친 뒤에 켜는 것이 안전하다.
그 전까지는 저장된 값을 읽되 화면에는 기존 추정치를 쓰거나, 내부적으로만 비교해 보는 편이 낫다.

---

## P2 · 새로 쓸 수 있게 된 것들

Phase 1부터 저장되지만 iOS가 아직 안 읽는 값이다. 필요할 때 가져다 쓰면 된다.

| Firestore 경로 | 내용 |
|---|---|
| `wave.swell.height_m` / `period_s` / `direction_deg` | 스웰 성분 |
| `wave.wind_wave.*` | 풍파 성분 |
| `tide.height_m` | 조석 (평균해수면 기준, m) |
| `marine_source.model` | 이 값을 만든 파랑 모델 이름 |
| `marine_source.snap_distance_km` | 실제 조회 격자가 해변에서 얼마나 떨어졌는지 |
| `marine_source.fallback_fields` | 다른 모델에서 채운 필드 목록 |

`marine_source`는 디버깅·신뢰도 표시용이다. 사용자에게 그대로 보여줄 값은 아니다.

**주의**: 제주는 `wave.swell.*`이 총 파고와 다른 모델에서 온다
(`fallback_fields`에 들어 있다). 총 파고와 스웰 성분이 서로 맞지 않으므로
**제주에서 스웰을 그대로 표시하면 안 된다.** 백엔드에서 모델 확정 후 정리한다.

---

## P3 · Phase 2 스키마 전환

백엔드가 Phase 2로 넘어가면 평면 필드가 사라진다. 그때 한 번에 옮긴다.

| 지금 | Phase 2 |
|---|---|
| `om_wave_height` | `wave.height_m` |
| `om_wave_direction` | `wave.direction_deg` |
| `om_sea_surface_temperature` | (별도 논의 — 아직 미정) |
| `wave_height` (기상청) | 삭제 예정 |

Phase 1에서 이미 **최종 이름으로 저장하고 있으므로** iOS는 한 번만 바꾸면 된다.
지금 P1을 하면서 `wave` 맵을 읽는 코드를 넣어두면 P3가 거의 끝난다.

백엔드가 평면 필드를 지우기 **전에** iOS 배포가 충분히 퍼져야 한다. 순서를 맞출 것.

---

## P4 · Open-Meteo 출처 표기 (라이선스 의무)

백엔드는 Open-Meteo Marine API를 **무료 티어**로 쓴다. 조건이 둘이다.

- **비상업 용도만** — 확인됨
- **CC BY 4.0** — 출처 표기 의무

앱 어딘가(설정·정보 화면 등)에 표기가 있는지 확인하고, 없으면 넣어야 한다.

```
Weather data by Open-Meteo.com
```

기상청 데이터도 쓰고 있으므로 그쪽 표기 조건도 함께 확인하는 편이 좋다.
코드 문제가 아니라 라이선스 문제라 **누군가 한 번 확인하고 끝내면 되는 항목이다.**

---

## 겸사겸사 정리할 것

- **`estimateWavePeriod`가 두 곳에 중복 정의되어 있다**
  `FirestoreRepository.swift:262`와 `FirestoreChartDTO.swift:51`.
  Repository에서 이미 계산해 DTO에 넘기므로 **DTO 쪽은 실행되지 않는 죽은 코드다.**
- **`mapWeather` / `computeWeatherCode`도 같은 구조로 중복**되어 있다.
- **`wave_height` 센티넬 가드** (`FirestoreRepository.swift:116`)
  `-900` 이하 / `900` 이상을 `nil`로 거른다. 기상청이 그런 값을 준 적이 있다는 뜻인데,
  백엔드에서도 같은 검증을 하는 게 맞다. Phase 1에서 Open-Meteo 쪽에는 범위 검증을 넣었지만
  기상청 쪽에는 아직 없다.

---

## 순서 제안

1. **확인** — Firestore에서 `wave_height`(기상청) 필드가 실제로 얼마나 채워지는지 본다.
   이 답에 따라 P0의 시급성이 갈린다.
2. **P0** — 파고 우선순위 결정 및 반영.
3. **P1(읽기만)** — `wave.period_s`를 읽어 기존 추정치와 비교해 본다. 화면은 아직 그대로.
4. **P1(노출)** — 백엔드 파주기 대조가 끝나면 실제 값으로 전환.
5. **P3** — 백엔드 Phase 2에 맞춰 스키마 이전.

P2는 필요할 때 아무 때나.
**P4(출처 표기)는 순서와 무관하게 빨리 확인할 것** — 라이선스 의무라 미룰 성격이 아니다.
