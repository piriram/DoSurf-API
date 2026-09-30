#!/usr/bin/env python3
"""기상청 부이 관측을 어느 해변의 기준값으로 쓸 수 있는지 — 격자 일치 판정.

`grid_coverage.py` 와 같은 계산을 **Windfinder 지점 대신 기상청 부이**에 대해
한다. 왜 부이를 보는가 —

  AGENTS.md 「⚠️ 이 대조는 독립 검증이 아니다」
  Windfinder 는 WW3(NOAA)를 쓰고 Open-Meteo 의 `ncep_gfswave*` 도 같은 소스다.
  높은 일치도가 곧 정확도는 아니다.

지금 대조는 **모델 대 모델**이라 순환이다. 4주를 쌓고도 「후보들이 실질적으로
같은 정확도」로 끝난 것이, 사실은 「다 똑같이 Windfinder 를 닮았다」였을 수
있다. 부이는 **관측값**이라 이 순환을 끊는다.

판정 규칙은 `grid_coverage.py` 와 같다 — 부이 좌표를 그 지역의 수집 모델에
넣었을 때 **해변과 같은 격자 칸**에 떨어지면 그 부이 관측을 해변의 기준값으로
쓸 수 있다. 격자가 다르면 못 쓴다(격자 간 파고차 중앙값 0.020m vs 모델
1·2위 차 0.001m — 공간 차이가 20배 이상 압도한다).

사용법:

    .venv/bin/python3 -m scripts.buoy_coverage
    .venv/bin/python3 -m scripts.buoy_coverage --region gangneung

**아직 API 를 붙이지 않았다.** 이 스크립트는 거리·격자만 잰다. 실제 관측값은
공공데이터포털 `getWhBuoy` 에서 받아야 하고 `KMA_API_KEY` 가 필요하다.
붙이기 전에 이 표로 「받아서 쓸 데가 있는가」를 먼저 본다.
"""
import argparse
import math
import time

import requests

from scripts.beach_registry import load_locations
from scripts.config import get_marine_model, get_marine_peak_period_model

BASE_URL = "https://marine-api.open-meteo.com/v1/marine"


def _dms(deg, minute, sec=0.0):
    """기상청이 도분초로 공표하므로 그대로 적고 여기서 십진수로 바꾼다."""
    return deg + minute / 60 + sec / 3600


# 기상청 부이. 좌표는 기상청 공표값(도분초)이다.
#
# kind:
#   "파고"  파고부이 — **연안**. 파고·파주기·수온
#   "해양"  해양기상부이 — 외해. + 파향·바람·기압·습도·시정
#
# ending: 2025년에 해양기상부이로 전환되며 운영 종료 예정으로 공지된 지점.
#         종료 목록(기상자료개방포털 공지): 연평도·위도동부·자은·진도·이수도·
#         소매물도·지심도·죽변·구엄·신창·내파수도·강릉.
#         **아직 살아 있는지 확인하지 않았다** — API 를 붙일 때 같이 볼 것.
BUOYS = {
    # ── 동해중부 ──
    "토성":       (_dms(38, 16, 38), _dms(128, 34, 33), "파고", False),
    "고성":       (_dms(38, 19,  2), _dms(128, 38, 21), "파고", False),
    "연곡":       (_dms(37, 52,  3), _dms(128, 53,  8), "파고", False),
    "강릉":       (_dms(37, 47, 54), _dms(129,  3, 39), "파고", True),
    "삼척":       (_dms(37, 24,  6), _dms(129, 26, 48), "파고", False),
    # ── 동해남부 ──
    "죽변":       (_dms(37,  6, 10), _dms(129, 27, 34), "파고", True),
    "후포":       (_dms(36, 43,  9), _dms(129, 29, 17), "파고", False),
    "월포":       (_dms(36, 13,  1), _dms(129, 24,  6), "파고", False),
    "구룡포":     (_dms(35, 58,  4), _dms(129, 35, 55), "파고", False),
    "당사":       (_dms(35, 34, 40), _dms(129, 30, 10), "파고", False),
    "간절곶":     (_dms(35, 22,  1), _dms(129, 22, 30), "파고", False),
    "포항(외해)": (_dms(36, 21,  0), _dms(129, 47,  0), "해양", False),
    "울산(외해)": (_dms(35, 20, 43), _dms(129, 50, 29), "해양", False),
    # ── 제주 ──
    "구엄":       (_dms(33, 31, 15), _dms(126, 22, 29), "파고", True),
    "신창":       (_dms(33, 22,  0.7), _dms(126,  6, 32), "파고", True),
    "위미":       (_dms(33, 13, 25.3), _dms(126, 42, 40.3), "파고", False),
    "서귀포":     (_dms(33,  7, 41), _dms(127,  1, 22), "파고", False),
}


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    rad = math.radians
    a = (math.sin(rad(lat2 - lat1) / 2) ** 2
         + math.cos(rad(lat1)) * math.cos(rad(lat2))
         * math.sin(rad(lon2 - lon1) / 2) ** 2)
    return 2 * radius * math.asin(math.sqrt(a))


_grid_cache = {}


def snap_grid(lat, lon, model):
    """이 좌표를 이 모델에 넣으면 어느 격자 칸에 떨어지나."""
    key = (round(lat, 4), round(lon, 4), model)
    if key not in _grid_cache:
        resp = requests.get(BASE_URL, params={
            "latitude": lat, "longitude": lon, "hourly": "wave_height",
            "models": model, "cell_selection": "sea",
            "timezone": "Asia/Seoul", "forecast_days": 1,
        }, timeout=30).json()
        _grid_cache[key] = (resp.get("latitude"), resp.get("longitude"))
        time.sleep(0.32)          # 무료 한도 배려 (분당 600)
    return _grid_cache[key]


def main():
    ap = argparse.ArgumentParser(
        description="기상청 부이를 어느 해변의 기준값으로 쓸 수 있나")
    ap.add_argument("--region", help="이 지역만")
    args = ap.parse_args()

    beaches = [b for b in load_locations()
               if not args.region or b["region"] == args.region]

    print(f"{'해변':16}{'지역':11}{'부이':>8}{'거리':>9}  판정")
    print("-" * 70)

    matched = []
    for beach in beaches:
        # 숨김 지점(다이빙 섬)은 파고를 첨두 모델로 받으므로 그 격자로 잰다
        model = (get_marine_peak_period_model(beach["region"])
                 if beach.get("hidden") else get_marine_model(beach["region"]))
        bgrid = snap_grid(beach["lat"], beach["lon"], model)

        best = None
        for name, (blat, blon, kind, ending) in BUOYS.items():
            if snap_grid(blat, blon, model) != bgrid:
                continue
            dist = haversine_km(beach["lat"], beach["lon"], blat, blon)
            if best is None or dist < best[1]:
                best = (name, dist, kind, ending)

        label = beach["display_name"] + ("[숨김]" if beach.get("hidden") else "")
        if best:
            name, dist, kind, ending = best
            matched.append((beach["display_name"], name, dist, ending))
            note = "  ⚠ 종료예정 부이" if ending else ""
            print(f"{label:16}{beach['region']:11}{name:>8}{dist:>8.1f}km  ✅{note}")
        else:
            near = min(BUOYS.items(), key=lambda kv: haversine_km(
                beach["lat"], beach["lon"], kv[1][0], kv[1][1]))
            nd = haversine_km(beach["lat"], beach["lon"], near[1][0], near[1][1])
            print(f"{label:16}{beach['region']:11}{'—':>8}{'':>10}  ❌ 최근접 "
                  f"{near[0]} {nd:.0f}km")

    print("-" * 70)
    print(f"격자 일치 {len(matched)}/{len(beaches)}곳")
    risky = [m for m in matched if m[3]]
    if risky:
        print("⚠ 종료예정 부이에 의존: "
              + ", ".join(f"{m[0]}←{m[1]}" for m in risky))
    print()
    print("거리는 참고값이다. 판정은 **격자 일치**로 한다 — 가까워도 칸이 다르면")
    print("모델값이 다르고, 멀어도 같은 칸이면 모델값이 정확히 같다.")


if __name__ == "__main__":
    main()
