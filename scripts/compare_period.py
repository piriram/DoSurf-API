"""iOS 파주기 추정치 vs 파랑모델 실제 파주기 대조.

iOS는 `wave.period_s`가 없으면 풍속에서 파주기를 유도한다
(DoSurf-iOS `FirestoreRepository.estimateWavePeriod`).

    Tp ≈ 0.83 * U10,  clamp [2, 18]

이 추정이 실제 파주기와 얼마나 다른지 잰다. 풍속은 Firestore에 저장된
기상청 값(iOS가 실제로 쓰는 그 값)을 쓰고, 실제 파주기는 Open-Meteo에서
직접 받는다.

사용:
    .venv/bin/python3 scripts/compare_period.py            # 기본 5곳
    .venv/bin/python3 scripts/compare_period.py 1001 3001  # beach_id 지정

주의: 지역마다 채택 모델이 다르므로(config.json marine.region_models)
`fetch_marine`에 region을 넘겨야 실제 저장되는 값과 같은 모델을 본다.
"""
import math
import statistics
import sys

from scripts.firebase_utils import get_db
from scripts.open_meteo import fetch_marine

import json
import os

# 지역별로 하나씩. 인자로 beach_id를 주면 그걸 쓴다.
DEFAULT_BEACH_IDS = ["1001", "2001", "3001", "4001", "6001"]

CLAMP_MIN, CLAMP_MAX = 2.0, 18.0
CLAMP_FLOOR_WIND = CLAMP_MIN / 0.83  # 이 풍속 이하면 추정치가 항상 바닥값


def load_locations():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "locations.json")) as f:
        return {str(l["beach_id"]): l for l in json.load(f)}


def ios_estimate(wind_speed):
    """DoSurf-iOS FirestoreRepository.estimateWavePeriod 와 같은 식."""
    if wind_speed is None or wind_speed <= 0:
        return None
    return max(CLAMP_MIN, min(CLAMP_MAX, 0.83 * wind_speed))


def doc_id_of(om_datetime):
    """"2026-08-31T15:00:00" -> "202608311500" (Firestore 문서 id 규약)"""
    d = om_datetime
    return d[:4] + d[5:7] + d[8:10] + d[11:13] + d[14:16]


def main(beach_ids):
    locations = load_locations()
    db = get_db()
    all_diffs = []
    pinned = 0
    compared = 0

    for bid in beach_ids:
        loc = locations.get(bid)
        if loc is None:
            print(f"[{bid}] locations.json에 없음")
            continue

        region, name = loc["region"], loc["display_name"]
        col = db.collection("regions").document(region).collection(bid)
        docs = {d.id: d.to_dict() for d in col.limit(500).stream() if d.id[0].isdigit()}

        hours, meta = fetch_marine(loc["lat"], loc["lon"],
                                   forecast_days=3, region=region)
        by_time = {doc_id_of(h["om_datetime"]): h
                   for h in hours if h.get("om_datetime")}

        rows = []
        for doc_id in sorted(docs):
            h = by_time.get(doc_id)
            if h is None:
                continue
            wind = docs[doc_id].get("wind_speed")
            est = ios_estimate(wind)
            real = h.get("wave_period")
            if est is None or real is None:
                continue
            rows.append((doc_id, wind, est, real,
                         h.get("swell_wave_period"), h.get("wind_wave_period")))

        if not rows:
            print(f"[{name}] 겹치는 시각 없음 (model={meta.get('model')})")
            continue

        diffs = [r[3] - r[2] for r in rows]
        all_diffs.extend(diffs)
        compared += len(rows)
        pinned += sum(1 for r in rows if r[1] <= CLAMP_FLOOR_WIND)

        print(f"\n=== {name} ({region}/{bid}) · model={meta.get('model')} · "
              f"격자거리 {meta.get('snap_distance_km')}km · {len(rows)}개 ===")
        print(f"{'시각':<14}{'풍속':>6}{'iOS추정':>9}{'실제':>8}{'차이':>8}{'스웰':>8}{'풍파':>8}")
        for doc_id, wind, est, real, swell, wind_wave in rows[:8]:
            sw = f"{swell:.1f}" if swell is not None else "-"
            ww = f"{wind_wave:.1f}" if wind_wave is not None else "-"
            print(f"{doc_id:<14}{wind:>6.1f}{est:>9.1f}{real:>8.1f}"
                  f"{real - est:>+8.1f}{sw:>8}{ww:>8}")
        print(f"  평균 차이 {statistics.mean(diffs):+.2f}s · "
              f"절대평균 {statistics.mean(abs(d) for d in diffs):.2f}s · "
              f"최대 {max(diffs, key=abs):+.1f}s")

    if not all_diffs:
        print("\n비교할 데이터가 없다.")
        return

    over3 = sum(1 for d in all_diffs if abs(d) >= 3)
    print(f"\n{'=' * 62}")
    print(f"전체 {len(all_diffs)}개 · 평균 차이 {statistics.mean(all_diffs):+.2f}s · "
          f"절대평균 {statistics.mean(abs(d) for d in all_diffs):.2f}s")
    print(f"3초 이상 어긋남: {over3}개 ({over3 / len(all_diffs) * 100:.0f}%)")
    print(f"추정치가 clamp 바닥({CLAMP_MIN}s)에 고정: "
          f"{pinned}개 ({pinned / compared * 100:.0f}%) "
          f"— 풍속 {CLAMP_FLOOR_WIND:.2f} m/s 이하")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_BEACH_IDS)
