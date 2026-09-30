#!/usr/bin/env python3
"""대조 지점의 결론을 어느 해변에 적용할 수 있는지 계산한다.

── 왜 이 스크립트가 필요한가 ──

대조(`model_compare.py`)는 Windfinder 지점 좌표로 하고, 실제 수집
(`app/services/collection.py`)은 `locations.json` 의 해변 좌표로 한다.
좌표가 다르면 Open-Meteo 격자도 다를 수 있고, **격자가 다르면 대조 결론을
그 해변에 적용할 수 없다.**

2026-09-27 실측이 그 근거다.

    격자가 다른 15곳의 파고차   중앙값 0.020m · 최대 0.083m
    격자가 같은 14곳의 파고차   0.000m (같은 격자니 당연하다)
    모델 1·2위 편향제거 MAE 차   0.001m  ← 4주 집계

격자 차이가 모델 차이를 **20~80배 압도한다.** 그래서 대조에서 "이 모델이 1위"라고
나와도 격자가 다른 해변에서는 그 순위가 유지된다는 보장이 전혀 없다.

모델 호출 좌표를 해변 좌표로 옮기는 것은 해법이 아니다. 기준값(Windfinder
파고·파주기)은 그 지점 좌표에 대한 예보이므로, 모델만 해변으로 옮기면 같은
크기의 공간 오차가 기준값 비교에 들어온다. 위치 차이와 모델 오차를 구분할 수
없게 될 뿐이다.

**그러므로 할 수 있는 것은 적용 범위를 정직하게 좁히는 것이다.**

사용법:

    .venv/bin/python3 -m scripts.grid_coverage              # 표로 출력
    .venv/bin/python3 -m scripts.grid_coverage --save       # data/grid_coverage.json 갱신
    .venv/bin/python3 -m scripts.grid_coverage --spot sokcho

`--save` 로 만든 파일을 `model_compare.py` 가 읽어, 그 지점의 결론을 적용할 수
있는 해변을 출력에 찍는다. 파일이 없으면 model_compare 는 안내만 하고 넘어간다.

**config.json 의 marine.region_models 를 바꾸면 다시 돌려야 한다.**
격자는 모델마다 다르다 — `best_match` 는 촘촘하고(스냅 0.62~8.7km)
`ncep_gfswave016` 은 1/6도 간격이다(3.45~18.6km).

Firestore 자격증명은 필요 없다. Open-Meteo 만 호출한다(해변 32곳 + 지점 10곳).
"""
import argparse
import json
import math
import os
import sys
import time

import requests

from scripts.beach_registry import load_locations
from scripts.model_compare import REFERENCE_SPOTS

BASE_URL = "https://marine-api.open-meteo.com/v1/marine"
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "grid_coverage.json")


def region_models():
    """config.json 의 지역별 모델. 대조 격자도 이 모델로 재야 의미가 있다."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        marine = json.load(f)["marine"]
    return marine["region_models"], marine["default_model"]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def grid_of(lat, lon, model, cache, retries=3):
    """(lat, lon) 이 그 모델에서 어느 격자로 스냅되는지.

    수집 경로와 같은 조건이어야 하므로 cell_selection=sea 를 똑같이 준다.
    """
    key = (round(lat, 4), round(lon, 4), model)
    if key in cache:
        return cache[key]

    params = {"latitude": lat, "longitude": lon, "hourly": "wave_height",
              "timezone": "Asia/Seoul", "cell_selection": "sea",
              "forecast_days": 1}
    if model != "best_match":
        params["models"] = model

    for attempt in range(retries):
        try:
            r = requests.get(BASE_URL, params=params, timeout=25)
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                cache[key] = None
                return None
            cache[key] = (data.get("latitude"), data.get("longitude"))
            time.sleep(0.15)          # 분당 600 한도 여유를 둔다
            return cache[key]
        except Exception:
            if attempt == retries - 1:
                cache[key] = None
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def build(only_spot=None):
    """지점별로 {격자 일치 해변, 격자 불일치 해변} 을 만든다."""
    rm, default = region_models()

    by_region = {}
    for name, spot in REFERENCE_SPOTS.items():
        for region in spot["regions"]:
            by_region.setdefault(region, []).append(name)

    cache = {}
    result = {name: {"windfinder": spot["windfinder"],
                     "lat": spot["lat"], "lon": spot["lon"],
                     "regions": spot["regions"],
                     "applies_to": [], "differs": []}
              for name, spot in REFERENCE_SPOTS.items()}
    orphans = []

    for loc in load_locations():
        # hidden 지점은 커버리지 분모에서 뺀다. 「N/29」 는 **서핑 해변** 중
        # 대조 결론을 적용할 수 있는 곳의 수이고, 다이빙 지점이 섞이면
        # 이전 날짜와 숫자를 비교할 수 없게 된다.
        if loc.get("hidden"):
            continue
        region = loc["region"]
        spots = by_region.get(region, [])
        model = rm.get(region, default)
        entry = {"beach_id": loc["beach_id"], "beach": loc["beach"],
                 "display_name": loc.get("display_name", loc["beach"]),
                 "region": region, "model": model}

        if not spots:
            orphans.append(entry)
            continue

        # 담당 지점은 가장 가까운 것으로 정한다 (한 지역에 여러 지점이 있다)
        best = min(spots, key=lambda s: haversine_km(
            loc["lat"], loc["lon"], REFERENCE_SPOTS[s]["lat"], REFERENCE_SPOTS[s]["lon"]))
        if only_spot and best != only_spot:
            continue

        entry["spot"] = best
        entry["distance_km"] = round(haversine_km(
            loc["lat"], loc["lon"],
            REFERENCE_SPOTS[best]["lat"], REFERENCE_SPOTS[best]["lon"]), 1)

        beach_grid = grid_of(loc["lat"], loc["lon"], model, cache)
        spot_grid = grid_of(REFERENCE_SPOTS[best]["lat"],
                            REFERENCE_SPOTS[best]["lon"], model, cache)
        entry["beach_grid"] = beach_grid
        entry["spot_grid"] = spot_grid

        key = "applies_to" if (beach_grid is not None and beach_grid == spot_grid) else "differs"
        result[best][key].append(entry)

    return result, orphans


def report(result, orphans):
    total = matched = 0
    print(f"\n{'지점':10}{'모델':>17}{'적용가능':>9}{'격자다름':>9}  적용 가능한 해변")
    print("-" * 92)
    for name, info in sorted(result.items()):
        ok, no = info["applies_to"], info["differs"]
        if not (ok or no):
            continue
        total += len(ok) + len(no)
        matched += len(ok)
        model = (ok or no)[0]["model"]
        names = ", ".join(b["display_name"] for b in ok) or "— 없음 —"
        print(f"{name:10}{model:>17}{len(ok):>9}{len(no):>9}  {names}")

    print(f"\n합계: {matched}/{total}곳에 결론을 적용할 수 있다.")

    print("\n[격자가 달라 적용 못 하는 해변]")
    any_diff = False
    for name, info in sorted(result.items()):
        for b in info["differs"]:
            any_diff = True
            print(f"  {b['display_name']:16} {b['region']:12} {name} 에서 "
                  f"{b['distance_km']}km · 격자 {b['beach_grid']} vs {b['spot_grid']}")
    if not any_diff:
        print("  없음")

    if orphans:
        print("\n[대조 지점 자체가 없는 해변]")
        for b in orphans:
            print(f"  {b['display_name']:16} {b['region']}")

    print("\n격자가 다르면 대조 결론을 쓸 수 없다 — 격자 간 파고차가 중앙값 0.020m,")
    print("모델 1·2위 차이는 0.001m 다 (2026-09-27 실측). 공간 차이가 20배 이상 크다.")


def main():
    ap = argparse.ArgumentParser(
        description="대조 지점의 결론을 적용할 수 있는 해변을 계산한다")
    ap.add_argument("--spot", choices=sorted(REFERENCE_SPOTS),
                    help="이 지점만 계산")
    ap.add_argument("--save", action="store_true",
                    help=f"결과를 {os.path.relpath(DEFAULT_OUT)} 에 저장 "
                         "(model_compare 가 읽는다)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="저장 경로")
    args = ap.parse_args()

    result, orphans = build(args.spot)
    report(result, orphans)

    if args.save:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "격자가 같은 해변만 그 지점의 대조 결론을 적용할 수 있다. "
                    "config.json 의 region_models 를 바꾸면 다시 생성할 것.",
            "spots": {name: {
                "windfinder": info["windfinder"],
                "regions": info["regions"],
                "applies_to": [b["display_name"] for b in info["applies_to"]],
                "differs": [b["display_name"] for b in info["differs"]],
            } for name, info in result.items()},
            "no_spot": [b["display_name"] for b in orphans],
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n저장: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
