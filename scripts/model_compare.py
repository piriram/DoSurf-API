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

Windfinder 값은 자동으로 못 가져온다. windfinder.com/forecast/<spot>에서
해당 날짜의 wave height를 00,03,06,09,12,15,18,21시 순서로 읽어 --reference에 넣을 것.
파주기(period)도 같은 시각 순서로 읽어 --reference-period에 넣는다.

파고와 파주기는 순위를 따로 매긴다. 파고로 고른 모델이 파주기까지 맞는다는
보장이 없기 때문이다 (docs/marine-data-audit.md). 1위가 갈리면 그렇다고 알린다.
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


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


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
    ap.add_argument("--models", help="비교할 모델 목록 (쉼표 구분). 기본: 후보 전체")
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

    print(f"\n지점: {label} ({lat}, {lon})   날짜: {args.date}")
    if reference:
        print(f"Windfinder 파고  : {reference}")
    if reference_period:
        print(f"Windfinder 파주기: {reference_period}")
    print()
    header = (f"{'모델':<20}{'격자거리':>9}{'MAE파고':>9}{'MAE주기':>9}"
              f"  파고 / 주기 시계열")
    print(header)
    print("-" * max(len(header), 96))

    results = []
    for model in models:
        data, err = fetch(lat, lon, model, args.date)
        if data is None:
            print(f"{model:<20}{'':>9}{'':>9}  실패: {err}")
            continue

        hourly = data.get("hourly", {})
        heights_all = series(hourly, "wave_height")
        periods_all = series(hourly, "wave_period")
        if len(heights_all) <= max(HOURS):
            print(f"{model:<20}{'':>9}{'':>9}  자료 부족")
            continue

        heights = [heights_all[h] for h in HOURS]
        periods = [periods_all[h] if h < len(periods_all) else None for h in HOURS]
        if any(v is None for v in heights):
            print(f"{model:<20}{'':>9}{'':>9}  결측 (육지 격자 가능성)")
            continue

        dist = haversine_km(lat, lon, data["latitude"], data["longitude"])
        mae = None
        if reference:
            mae = sum(abs(a - b) for a, b in zip(heights, reference)) / len(HOURS)

        # 파주기는 모델이 결측을 주는 시각이 있어 짝이 맞는 것만 센다
        mae_period = None
        if reference_period:
            pairs = [(p, r) for p, r in zip(periods, reference_period) if p is not None]
            if pairs:
                mae_period = sum(abs(p - r) for p, r in pairs) / len(pairs)

        results.append({
            "model": model, "mae": mae, "mae_period": mae_period,
            "snap_km": round(dist, 1),
            "heights": heights, "periods": periods,
            "grid": [data["latitude"], data["longitude"]],
        })
        mae_txt = f"{mae:>9.3f}" if mae is not None else f"{'-':>9}"
        mae_p_txt = f"{mae_period:>9.2f}" if mae_period is not None else f"{'-':>9}"
        period_txt = [round(v, 1) if v is not None else None for v in periods]
        print(f"{model:<20}{dist:>8.1f}k{mae_txt}{mae_p_txt}  "
              f"{[round(v, 2) for v in heights]} / {period_txt}")

    def ranking(key, unit):
        ranked = sorted([r for r in results if r.get(key) is not None],
                        key=lambda r: r[key])
        for i, r in enumerate(ranked, 1):
            print(f"  {i}. {r[key]:.3f}{unit}  {r['model']}")
        return ranked

    if results and (reference or reference_period):
        print(f"\n=== {label} {args.date} 순위 ===")

        best_h = best_p = None
        if reference:
            print("\n[파고 기준]")
            ranked_h = ranking("mae", "m")
            best_h = ranked_h[0]["model"] if ranked_h else None
        if reference_period:
            print("\n[파주기 기준]")
            ranked_p = ranking("mae_period", "s")
            best_p = ranked_p[0]["model"] if ranked_p else None

        # 열린 질문: 파고로 고른 모델이 파주기까지 맞는가 (docs/marine-data-audit.md)
        if best_h and best_p:
            if best_h == best_p:
                print(f"\n두 기준의 1위가 같다: {best_h}")
            else:
                print(f"\n⚠️ 1위가 갈린다 — 파고 {best_h} / 파주기 {best_p}")
                print("   한 모델로 둘 다 만족시킬 수 없다는 뜻이므로,")
                print("   파주기를 화면에 노출하기 전에 표본을 더 쌓을 것.")

        if args.spot:
            regions = ", ".join(REFERENCE_SPOTS[args.spot]["regions"])
            print(f"\n이 지점이 대표하는 지역: {regions}")
            print("config.json 의 marine.region_models 를 바꾸려면 여러 날 결과를 먼저 쌓으세요.")

    if args.out and results:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        record = {
            "label": label, "lat": lat, "lon": lon, "date": args.date,
            "reference": reference, "reference_period": reference_period,
            "results": results,
            "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\n기록 추가: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
