#!/usr/bin/env python3
"""
파랑 모델 대조 스크립트

지역마다 Windfinder에 가장 가까운 모델이 다르다는 것이 확인됐지만
(docs/marine-data-audit.md 「2차 검증」), 근거가 2일치 표본뿐이다.
이 스크립트로 대조를 계속 쌓아서 config.json의 모델 선택을 재확정한다.

사용법:

  # 후보 모델들의 오늘 예보를 나란히 출력
  python scripts/model_compare.py --spot sokcho

  # Windfinder 값을 넣어 평균절대오차(MAE)로 순위 매기기
  python scripts/model_compare.py --spot jeju \
      --reference 1.0,0.9,0.8,0.8,0.8,0.8,0.8,0.8

  # 파주기까지 함께 (파고와 따로 순위가 나오고, 1위가 갈리면 경고한다)
  python scripts/model_compare.py --spot jeju \
      --reference 1.0,0.9,0.8,0.8,0.8,0.8,0.8,0.8 \
      --reference-period 10,10,11,11,10,10,9,9

  # 결과를 누적 저장 (JSON Lines)
  python scripts/model_compare.py --spot sokcho --reference ... \
      --out data/model_compare.jsonl

  # 임의 좌표
  python scripts/model_compare.py --lat 35.1789 --lon 129.202 --label busan_songjeong

Windfinder 값은 `--from-windfinder` 로 자동 수집된다 (scripts/windfinder.py).
직접 넣으려면 windfinder.com/forecast/<spot>에서 해당 날짜의 wave height를
00,03,06,09,12,15,18,21시 순서로 읽어 --reference에 넣을 것.
파주기(period)도 같은 시각 순서로 읽어 --reference-period에 넣는다.

── Windy는 왜 수동인가 ──

Windy Point Forecast API의 무료 Trial은 실제 예보가 아니라 난수를 돌려준다
("randomly shuffled and slightly modified data", 공식 문구). 실데이터는
Professional(€990/년)뿐이다. 그래서 Windy 값은 사람이 windy.com에서 읽어
--reference-windy 로 넣는다. 자동화하려고 스크래핑하지 말 것 —
windy.com은 WebGL SPA라 HTML 파싱이 불가능하고 ToS에도 걸린다.

그리고 Windy의 파랑 모델은 전부 Open-Meteo에도 있다 (WINDY_EQUIVALENT 참조).
그러므로 이 대조가 재는 것은 "Windy 예보가 더 맞나"가 아니라
**"같은 모델을 Windy가 어떻게 보간·스냅했나"** 다. 표에서 `*` 표시된 모델이
Windy가 화면에 쓰는 그 모델이고, Windy 값과 그 모델의 차이가 Windy 후처리 몫이다.

  # 3자 대조: Windfinder(자동) + Windy(수동) + Open-Meteo 모델 6종
  python -m scripts.model_compare --spot sokcho --from-windfinder \
      --reference-windy 1.2,1.1,1.0,0.9,0.9,0.8,0.8,0.7 \
      --out data/model_compare.jsonl

여러 날 쌓은 뒤 결론은 `scripts/compare_rollup.py` 로 낸다.

파고와 파주기는 순위를 따로 매긴다. 파고로 고른 모델이 파주기까지 맞는다는
보장이 없기 때문이다 (docs/marine-data-audit.md). 1위가 갈리면 그렇다고 알린다.

── MAE만 보면 안 되는 이유 ──

MAE는 두 가지 다른 문제를 한 숫자에 섞는다.

  편향(bias)  — 이 지점에서 늘 얼마나 높게/낮게 나오는가. 상수를 더해 고칠 수 있다
  모양(shape) — 오르내리는 흐름이 Windfinder와 같은가. 모델을 바꿔야 고친다

2026-08-30 속초 측정에서 전 모델의 상관계수가 0.98을 넘었다. 즉 흐름은 이미
맞고, 차이는 대부분 편향이었다. gwam이 대표적이다 — MAE 0.235로 꼴찌였는데
편향이 정확히 -0.235이고, 편향을 빼면 오차가 0.105로 줄었다. 틀린 게 아니라
일정하게 낮게 나올 뿐이다.

그래서 MAE 순위만 보고 모델을 바꾸면 편향을 모델 문제로 착각하게 된다.
아래 네 값을 함께 본다.

  MAE          기존 지표
  편향          평균 부호오차. 클수록 보정계수(MOS)로 해결할 여지가 크다
  편향제거 MAE   편향을 뺀 뒤 남는 오차. 이게 진짜 모양 오차다
  상관계수       흐름 일치도. 1에 가까울수록 경향성이 같다

**모델은 편향제거 MAE와 상관계수로 고르고, 남은 편향은 보정계수로 처리한다.**
보정계수를 넣을 때는 반드시 여러 날 평균을 쓸 것 — 하루치로 상수를 박으면
예전에 제거한 `+0.5` 보정의 재발이다.
"""
import argparse
import datetime
import json
import math
import os
import sys
import time

import requests

BASE_URL = "https://marine-api.open-meteo.com/v1/marine"

# Windfinder 지점 좌표. 대조는 반드시 Windfinder가 쓰는 좌표로 해야 의미가 있다.
REFERENCE_SPOTS = {
    "sokcho": {"lat": 38.2500, "lon": 128.5660, "windfinder": "sokcho",
               "regions": ["sokcho", "yangyang", "gangneung"]},
    "jeju":   {"lat": 33.5142, "lon": 126.5297, "windfinder": "jeju",
               "regions": ["jeju"]},
}

CANDIDATE_MODELS = [
    "best_match",
    "ncep_gfswave025",
    "ncep_gfswave016",
    "gwam",
    "ecmwf_wam025",
    "meteofrance_wave",
]

HOURS = [0, 3, 6, 9, 12, 15, 18, 21]

# Windy가 쓰는 파랑 모델은 전부 Open-Meteo에도 있다. 같은 기관의 같은 모델이다.
#
#   Windy gfsWave    = NOAA/NCEP GFS-Wave (WW3)  → ncep_gfswave025 · ncep_gfswave016
#   Windy iconWave   = DWD GWAM                  → gwam
#   Windy iconEuWave = DWD EWAM                  → ewam (유럽 해역 전용, 한국은 결측)
#
# 그래서 Windy 대조는 "다른 예보와의 대조"가 아니다. 같은 모델을 Windy가 어떻게
# 격자 스냅·보간했고 어느 런(run)을 물고 있는가의 대조다. 순위를 읽을 때 이걸
# 잊으면 Windfinder를 WW3라고 착각했던 것과 같은 실수를 반복하게 된다
# (docs/marine-data-audit.md 「기준을 Windfinder로」).
#
# 한국에서 Windy가 실제로 보여주는 파랑 모델은 gfsWave·iconWave 둘뿐이므로,
# Windy 화면값과 아래 두 모델의 차이가 곧 Windy의 후처리 몫이다.
# Open-Meteo가 아닌 후보. 같은 표에 놓고 재려고 가짜 모델명으로 끼워 넣는다.
# 두 이름이 같은 CMEMS 자료를 가리키되 파주기만 다르게 읽는다.
#   cmems       VTM10 평균주기 — Open-Meteo `wave_period` 와 같은 계열
#   cmems_peak  VTPK  첨두주기 — Windfinder·서핑 앱이 화면에 쓰는 값
# 파주기 순위에서 둘이 갈리면, 우리가 지금까지 "파주기가 안 맞는다"고 본 것이
# 모델 문제가 아니라 **정의가 다른 값을 비교하고 있었던 것**이라는 뜻이다.
CMEMS_MODELS = {
    "cmems": "wave_period",
    "cmems_peak": "wave_period_peak",
}

# 한 번 돌 때 CMEMS를 두 번 내려받지 않도록 (lat, lon, date) 로 캐시한다
_CMEMS_CACHE = {}

WINDY_EQUIVALENT = {
    "ncep_gfswave025": "gfsWave",
    "ncep_gfswave016": "gfsWave(0.16°)",
    "gwam": "iconWave",
    "ewam": "iconEuWave",
}


def fetch(lat, lon, model, date, retries=3, timeout=25):
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_period,wave_direction",
        "timezone": "Asia/Seoul",
        "start_date": date,
        "end_date": date,
        "cell_selection": "sea",
    }
    if model != "best_match":
        params["models"] = model

    for attempt in range(retries):
        try:
            r = requests.get(BASE_URL, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                return None, data.get("reason", "unknown")
            return data, None
        except Exception as exc:                      # 네트워크가 불안정한 환경을 가정
            if attempt == retries - 1:
                return None, str(exc)
            time.sleep(1.5 * (attempt + 1))
    return None, "재시도 초과"


def series(hourly, name):
    if name in hourly:
        return hourly[name] or []
    for key in hourly:
        if key.startswith(name + "_"):
            return hourly[key] or []
    return []


def error_stats(predicted, reference):
    """예보와 기준값의 오차를 편향과 모양으로 나눠 잰다.

    반환: {mae, bias, mae_debiased, corr} — 짝이 맞는 값이 없으면 None.

    bias는 평균 부호오차다. 이 지점에서 모델이 늘 얼마나 높게/낮게 나오는지를
    뜻하고, 상수를 더해 고칠 수 있다. mae_debiased는 그 편향을 뺀 뒤 남는
    오차이므로 모델 자체의 모양 오차에 가깝다.
    """
    pairs = [(p, r) for p, r in zip(predicted, reference)
             if p is not None and r is not None]
    if not pairs:
        return None

    errors = [p - r for p, r in pairs]
    bias = sum(errors) / len(errors)

    stats = {
        "mae": sum(abs(e) for e in errors) / len(errors),
        "bias": bias,
        "mae_debiased": sum(abs(e - bias) for e in errors) / len(errors),
        "corr": None,
    }

    # 기준값이 하루 종일 같은 값이면(제주에서 실제로 있었다) 상관계수가 정의되지
    # 않는다. 그런 날은 경향성을 잴 수 없으므로 None으로 둔다.
    preds = [p for p, _ in pairs]
    refs = [r for _, r in pairs]
    mp, mr = sum(preds) / len(preds), sum(refs) / len(refs)
    dp = sum((x - mp) ** 2 for x in preds) ** 0.5
    dr = sum((y - mr) ** 2 for y in refs) ** 0.5
    if dp > 0 and dr > 0:
        stats["corr"] = sum((x - mp) * (y - mr)
                            for x, y in zip(preds, refs)) / (dp * dr)
    return stats


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def fetch_cmems(lat, lon, date, period_field):
    """CMEMS에서 그날 HOURS 8개 시각의 파고·파주기를 뽑는다.

    Open-Meteo는 시간별 24개를 주므로 `heights[h]` 로 바로 집히지만,
    CMEMS는 3시간 간격 행이라 시각 문자열로 맞춰야 한다.
    """
    key = (round(lat, 4), round(lon, 4), date)
    if key not in _CMEMS_CACHE:
        from scripts.copernicus import fetch_marine
        rows, meta = fetch_marine(lat, lon, forecast_days=1, start_date=date)
        _CMEMS_CACHE[key] = ({r["om_datetime"]: r for r in rows}, meta)
    by_time, meta = _CMEMS_CACHE[key]

    heights, periods = [], []
    for h in HOURS:
        row = by_time.get(f"{date}T{h:02d}:00:00", {})
        heights.append(row.get("wave_height"))
        periods.append(row.get(period_field))
    return heights, periods, meta


def fetch_series(lat, lon, model, date):
    """모델 하나의 그날 8개 시각. 반환 (heights, periods, grid_lat, grid_lon, err)

    Open-Meteo든 CMEMS든 이 함수 밖에서는 구분하지 않는다.
    """
    if model in CMEMS_MODELS:
        try:
            heights, periods, meta = fetch_cmems(lat, lon, date, CMEMS_MODELS[model])
        except Exception as exc:
            return None, None, None, None, str(exc)
        return heights, periods, meta["grid_lat"], meta["grid_lon"], None

    data, err = fetch(lat, lon, model, date)
    if data is None:
        return None, None, None, None, err

    hourly = data.get("hourly", {})
    heights_all = series(hourly, "wave_height")
    periods_all = series(hourly, "wave_period")
    if len(heights_all) <= max(HOURS):
        return None, None, None, None, "자료 부족"

    heights = [heights_all[h] for h in HOURS]
    periods = [periods_all[h] if h < len(periods_all) else None for h in HOURS]
    return heights, periods, data["latitude"], data["longitude"], None


def main():
    ap = argparse.ArgumentParser(description="파랑 모델을 Windfinder와 대조한다")
    ap.add_argument("--spot", choices=sorted(REFERENCE_SPOTS), help="미리 정의된 대조 지점")
    ap.add_argument("--lat", type=float, help="임의 좌표 위도")
    ap.add_argument("--lon", type=float, help="임의 좌표 경도")
    ap.add_argument("--label", help="임의 좌표에 붙일 이름")
    ap.add_argument("--date", default=datetime.date.today().isoformat(),
                    help="조회 날짜 (기본: 오늘). 과거 날짜는 재분석 값이 섞이므로 당일 권장")
    ap.add_argument("--reference", help="Windfinder 파고 8개 값 (00,03,...,21시), 쉼표 구분")
    ap.add_argument("--reference-period",
                    help="Windfinder 파주기 8개 값 (00,03,...,21시), 쉼표 구분. "
                         "파고와 따로 순위를 매긴다")
    ap.add_argument("--from-windfinder", metavar="SPOT", nargs="?", const=True,
                    help="Windfinder 예보 페이지에서 파고·파주기를 직접 읽어온다. "
                         "값을 생략하면 --spot 이름을 그대로 쓴다. "
                         "--reference / --reference-period 를 주면 그쪽이 우선한다")
    ap.add_argument("--reference-windy",
                    help="Windy 파고 8개 값 (00,03,...,21시), 쉼표 구분. "
                         "windy.com 파도 레이어에서 직접 읽어 넣는다 — "
                         "Windy API 무료 티어는 난수를 돌려주므로 쓸 수 없다")
    ap.add_argument("--reference-windy-period",
                    help="Windy 파주기 8개 값 (00,03,...,21시), 쉼표 구분")
    ap.add_argument("--models",
                    help="비교할 모델 목록 (쉼표 구분). 기본: Open-Meteo 후보 전체. "
                         "cmems / cmems_peak 를 넣으면 Copernicus Marine도 같이 잰다 "
                         "(자격증명 필요 — scripts/copernicus.py 참조)")
    ap.add_argument("--out", help="결과를 이 파일에 JSON Lines로 append")
    args = ap.parse_args()

    if args.spot:
        spot = REFERENCE_SPOTS[args.spot]
        lat, lon, label = spot["lat"], spot["lon"], args.spot
    elif args.lat is not None and args.lon is not None:
        lat, lon, label = args.lat, args.lon, args.label or f"{args.lat},{args.lon}"
    else:
        ap.error("--spot 또는 --lat/--lon 중 하나가 필요합니다")

    def parse_reference(raw, flag):
        if not raw:
            return None
        try:
            values = [float(v) for v in raw.split(",")]
        except ValueError:
            ap.error(f"{flag} 는 숫자 {len(HOURS)}개를 쉼표로 구분해 주세요")
        if len(values) != len(HOURS):
            ap.error(f"{flag} 는 값이 {len(HOURS)}개여야 합니다 (00,03,...,21시)")
        return values

    reference = parse_reference(args.reference, "--reference")
    reference_period = parse_reference(args.reference_period, "--reference-period")
    reference_windy = parse_reference(args.reference_windy, "--reference-windy")
    reference_windy_period = parse_reference(args.reference_windy_period,
                                             "--reference-windy-period")

    if args.from_windfinder:
        wf_spot = args.from_windfinder if isinstance(args.from_windfinder, str) else args.spot
        if not wf_spot:
            ap.error("--from-windfinder 에 지점 이름을 주거나 --spot 을 함께 쓰세요")
        # 직접 준 값이 있으면 그쪽을 존중한다
        if reference and reference_period:
            print(f"(--reference 와 --reference-period 가 모두 있어 Windfinder 수집을 건너뜁니다)")
        else:
            from scripts.windfinder import reference_series
            try:
                label_wf, heights_wf, periods_wf, cached = reference_series(wf_spot)
            except Exception as exc:
                ap.error(f"Windfinder 수집 실패: {exc}")
            src = "캐시" if cached else "수집"
            print(f"Windfinder({wf_spot}) {label_wf} — {src}")
            if reference is None and all(v is not None for v in heights_wf):
                reference = heights_wf
            if reference_period is None and all(v is not None for v in periods_wf):
                reference_period = periods_wf

    models = args.models.split(",") if args.models else CANDIDATE_MODELS

    # 활성화된 기준들. suffix 는 results 딕셔너리와 jsonl 키에 붙는다.
    # ""(빈 문자열)이 Windfinder로, 기존 스키마를 그대로 유지하기 위해서다.
    refs = [("", "Windfinder", reference, reference_period)]
    if reference_windy or reference_windy_period:
        refs.append(("_windy", "Windy", reference_windy, reference_windy_period))
    active = [r for r in refs if r[2] or r[3]]

    print(f"\n지점: {label} ({lat}, {lon})   날짜: {args.date}")
    for _, name, heights, periods in active:
        if heights:
            print(f"{name} 파고  : {heights}")
        if periods:
            print(f"{name} 파주기: {periods}")

    # ── 기준끼리 먼저 대조한다 ──
    # 두 기준이 서로 크게 다르면 모델 순위는 어느 기준을 골랐느냐로 정해진다.
    # 그 상태에서 1·2위 차이를 논하는 건 표본 노이즈를 읽는 것이다.
    cross = None
    if reference and reference_windy:
        cross = error_stats(reference_windy, reference)
        if cross:
            corr_txt = f"{cross['corr']:.4f}" if cross["corr"] is not None else "-"
            print(f"\n[기준끼리] Windy vs Windfinder — "
                  f"MAE {cross['mae']:.3f}m · 편향 {cross['bias']:+.3f}m · 상관 {corr_txt}")
            if cross["corr"] is not None and cross["corr"] >= 0.95:
                print("  두 기준이 같은 흐름이다. 차이는 대부분 상수 편향이므로")
                print("  '어느 쪽이 맞나'가 아니라 '어느 쪽에 맞출까'의 문제다.")

    results = []
    for model in models:
        heights, periods, glat, glon, err = fetch_series(lat, lon, model, args.date)
        if err:
            print(f"\n{model}: 실패 — {err}")
            continue
        if any(v is None for v in heights):
            # ewam 처럼 해역 밖 모델이 여기로 떨어진다
            print(f"\n{model}: 결측 (해당 모델의 커버리지 밖이거나 육지 격자)")
            continue

        dist = haversine_km(lat, lon, glat, glon)
        row = {
            "model": model,
            "windy_equivalent": WINDY_EQUIVALENT.get(model),
            "snap_km": round(dist, 1),
            "heights": heights, "periods": periods,
            "grid": [glat, glon],
        }

        for suffix, _name, ref_h, ref_p in refs:
            sh = error_stats(heights, ref_h) if ref_h else None
            # 파주기는 모델이 결측을 주는 시각이 있어 짝이 맞는 것만 센다
            sp = error_stats(periods, ref_p) if ref_p else None
            row[f"mae{suffix}"] = sh["mae"] if sh else None
            row[f"bias{suffix}"] = sh["bias"] if sh else None
            row[f"mae_debiased{suffix}"] = sh["mae_debiased"] if sh else None
            row[f"corr{suffix}"] = sh["corr"] if sh else None
            row[f"mae_period{suffix}"] = sp["mae"] if sp else None
            row[f"bias_period{suffix}"] = sp["bias"] if sp else None
            row[f"mae_period_debiased{suffix}"] = sp["mae_debiased"] if sp else None
            row[f"corr_period{suffix}"] = sp["corr"] if sp else None

        results.append(row)

    def cell(value, fmt="{:.3f}", width=9):
        return (fmt.format(value) if value is not None else "-").rjust(width)

    def render(suffix, name):
        """한 기준에 대한 표. 컬럼 구성은 기준이 달라도 같다."""
        header = (f"{'모델':<20}{'격자거리':>9}{'MAE':>9}{'편향':>9}"
                  f"{'편향제거':>9}{'상관':>9}{'MAE주기':>9}")
        print(f"\n=== vs {name} ===")
        print(header)
        print("-" * max(len(header), 84))
        for r in results:
            mark = " *" if r["windy_equivalent"] else ""
            print(f"{r['model'] + mark:<20}{r['snap_km']:>8.1f}k"
                  f"{cell(r[f'mae{suffix}'])}"
                  f"{cell(r[f'bias{suffix}'], '{:+.3f}')}"
                  f"{cell(r[f'mae_debiased{suffix}'])}"
                  f"{cell(r[f'corr{suffix}'], '{:.4f}')}"
                  f"{cell(r[f'mae_period{suffix}'], '{:.2f}')}")
        legend = [f"{r['model']}={r['windy_equivalent']}"
                  for r in results if r["windy_equivalent"]]
        if legend:
            print(f"  * Windy 등가 모델: {' · '.join(legend)}")

    def ranking(key, unit, bias_key=None):
        ranked = sorted([r for r in results if r.get(key) is not None],
                        key=lambda r: r[key])
        for i, r in enumerate(ranked, 1):
            extra = ""
            if bias_key and r.get(bias_key) is not None:
                extra = f"   (편향 {r[bias_key]:+.3f}{unit})"
            print(f"  {i}. {r[key]:.3f}{unit}  {r['model']}{extra}")
        return ranked

    # 기준값 없이 돌리는 경우(모델 값만 훑어볼 때)도 표는 나와야 한다
    if not active and results:
        render("", "기준 없음 — 모델 값만")

    winners = {}
    for suffix, name, ref_h, ref_p in active:
        render(suffix, name)
        if not (ref_h or ref_p):
            continue
        print(f"\n--- {name} 기준 순위 ---")

        best_h = best_p = None
        if ref_h:
            # 모델 선택은 편향을 뺀 오차로 한다. 편향은 보정계수로 따로 처리한다.
            print("\n[파고 · 편향 제거 후 — 모델 선택 기준]")
            ranked_h = ranking(f"mae_debiased{suffix}", "m", f"bias{suffix}")
            best_h = ranked_h[0]["model"] if ranked_h else None

            # 1·2위 차이가 기준끼리의 차이보다 작으면 순위를 신뢰할 수 없다
            if cross and len(ranked_h) >= 2:
                gap = ranked_h[1][f"mae_debiased{suffix}"] - ranked_h[0][f"mae_debiased{suffix}"]
                if gap < cross["mae_debiased"]:
                    print(f"\n  ⚠️ 1·2위 차이({gap:.3f}m)가 두 기준의 모양 차이"
                          f"({cross['mae_debiased']:.3f}m)보다 작다.")
                    print("     이 순위는 기준 선택에 좌우된다. 표본을 더 쌓기 전엔 근거로 쓰지 말 것.")

            corr_rows = [r for r in results if r.get(f"corr{suffix}") is not None]
            if corr_rows:
                worst = min(corr_rows, key=lambda r: r[f"corr{suffix}"])
                print(f"\n  상관계수 최저: {worst[f'corr{suffix}']:.4f} ({worst['model']})")
                if worst[f"corr{suffix}"] >= 0.95:
                    print(f"  → 전 모델이 {name}와 같은 흐름이다. 남은 차이는 대부분 편향이므로")
                    print("     모델 교체보다 보정계수(MOS)가 답이다. 여러 날 평균으로 구할 것.")
            else:
                print(f"\n  ⚠️ 상관계수를 계산할 수 없다 — {name} 값이 하루 종일 같다.")
                print("     경향성 판단 불가. 파고가 변하는 날 다시 잴 것.")

        if ref_p:
            print("\n[파주기 · 편향 제거 후]")
            ranked_p = ranking(f"mae_period_debiased{suffix}", "s")
            best_p = ranked_p[0]["model"] if ranked_p else None

        # 열린 질문: 파고로 고른 모델이 파주기까지 맞는가 (docs/marine-data-audit.md)
        if best_h and best_p:
            if best_h == best_p:
                print(f"\n두 기준의 1위가 같다: {best_h}")
            else:
                print(f"\n⚠️ 1위가 갈린다 — 파고 {best_h} / 파주기 {best_p}")
                print("   한 모델로 둘 다 만족시킬 수 없다는 뜻이므로,")
                print("   파주기를 화면에 노출하기 전에 표본을 더 쌓을 것.")
        winners[name] = best_h

    # ── Windfinder와 Windy가 서로 다른 모델을 고르면 ──
    if len(winners) > 1:
        picks = {n: m for n, m in winners.items() if m}
        if len(set(picks.values())) > 1:
            print("\n⚠️ 기준마다 1위가 다르다 — " +
                  " / ".join(f"{n} {m}" for n, m in picks.items()))
            print("   어느 예보에 맞출지는 데이터가 아니라 제품 결정이다.")
            print("   서퍼가 실제로 뭘 보는지로 정할 것 (docs/marine-data-audit.md).")
        elif picks:
            print(f"\n두 기준이 같은 모델을 고른다: {next(iter(picks.values()))}")

    if args.spot and results:
        regions = ", ".join(REFERENCE_SPOTS[args.spot]["regions"])
        print(f"\n이 지점이 대표하는 지역: {regions}")
        print("config.json 의 marine.region_models 를 바꾸려면 여러 날 결과를 먼저 쌓으세요.")
        print("누적분 집계: .venv/bin/python3 -m scripts.compare_rollup")

    if args.out and results:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        record = {
            "label": label, "lat": lat, "lon": lon, "date": args.date,
            "reference": reference, "reference_period": reference_period,
            "reference_windy": reference_windy,
            "reference_windy_period": reference_windy_period,
            "cross_windy_vs_windfinder": cross,
            "results": results,
            "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\n기록 추가: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
