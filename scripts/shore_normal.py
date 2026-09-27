#!/usr/bin/env python3
"""해변이 바라보는 방위(`shore_normal_deg`)와 스웰 창(`swell_window_deg`) 초안을 만든다.

── 왜 필요한가 ──

**격자가 붕괴해서 지역 안 해변들이 같은 값을 갖는다.** 양양 6곳(죽도~물치)은
어느 파랑 모델을 써도 Open-Meteo 격자 하나에 다 들어간다 — `best_match`(8km)도,
`ncep_gfswave016`(18km)도 마찬가지다 (2026-09-27 5모델 실측). 해변 간격이 3km 라
전지구 파랑모델 해상도로는 구분이 불가능하다.

    yangyang  6곳 → 서로 다른 파고 1개   (전부 0.64m)
    pohang    5곳 → 3개 (월포·신항만·영일대가 동일)
    gangneung 7곳 → 4개

**Windfinder 를 따라가도 이 문제는 안 풀린다.** Windfinder 도 양양 일대에 지점이
`gisamun` 하나뿐이다. 즉 Windfinder 를 완벽히 재현해도 양양 6곳은 같은 값이다.
해변별 차이는 **받아오는 게 아니라 계산해서 만들어야 한다**
(`docs/marine-data-audit.md` 「앞바다 값은 지역당 하나만 받고」).

── 어떻게 구하는가 ──

Open-Meteo 고도 API(`/v1/elevation`)로 육지·바다를 판정한다. 해변 좌표에서
36방위로 두 반경(기본 2km·5km)의 점을 만들고, **두 반경 모두 고도 0 이하**인
방위를 바다로 본다. 그 바다 방위들 중 **가장 긴 연속 구간**의 중심이
`shore_normal_deg`, 구간 길이가 `swell_window_deg` 다.

죽도(37.9723, 128.7595) 실측 — 서쪽 293·146·67m(육지), 동쪽 0m(바다).
동해안이므로 90° 근처가 나와야 맞다.

가장 긴 구간만 쓰는 이유: 만이나 섬이 있으면 바다 방위가 여러 토막으로 갈린다.
좁은 틈으로 들어오는 스웰보다 주 개구부가 파고를 지배한다.

사용법:

    .venv/bin/python3 -m scripts.shore_normal                 # 표로 확인
    .venv/bin/python3 -m scripts.shore_normal --region jeju
    .venv/bin/python3 -m scripts.shore_normal --save           # data/shore_normal.json

**이건 초안이다.** `docs/marine-data-audit.md` Q3 이 말하는 대로 실제 스팟을 아는
사람의 검수가 필요하다 — 특히 방위각이 인접 해변과 크게 다르거나
`swell_window_deg` 가 아주 좁게(<60°) 나온 해변을 의심할 것. 만 안쪽이거나
좌표가 실제 입수 지점과 떨어진 경우다.

고도 API 는 자격증명이 필요 없고 파랑 API 와 한도를 공유한다
(해변 32곳 × 1콜 = 32콜).
"""
import argparse
import json
import math
import os
import sys
import time

import requests

from scripts.beach_registry import load_locations

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "shore_normal.json")

# 10도 간격. 5도로 줄이면 한 요청의 좌표 수가 한도를 넘는다.
BEARING_STEP = 10
BEARINGS = list(range(0, 360, BEARING_STEP))

# 두 반경 모두 바다여야 바다로 센다. 가까운 쪽만 보면 파도가 닿지 않는
# 작은 물길도 바다로 잡히고, 먼 쪽만 보면 곶 너머 바다까지 열린 것으로 본다.
RADII_KM = (2.0, 5.0)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def offset(lat, lon, bearing_deg, km):
    """방위·거리만큼 옮긴 좌표. 위도 1도 111km, 경도는 cos(위도) 보정."""
    b = math.radians(bearing_deg)
    dlat = km / 111.0 * math.cos(b)
    dlon = km / (111.0 * math.cos(math.radians(lat))) * math.sin(b)
    return lat + dlat, lon + dlon


def elevations(points, retries=4, timeout=30):
    """여러 좌표의 고도를 한 번에. 반환 (값 리스트, 실패 이유).

    한 해변이 72좌표를 쓰므로 32곳을 연달아 돌리면 분당 한도에 걸린다.
    429/5xx 는 점점 더 기다리며 재시도하고, 끝내 실패하면 **이유를 돌려준다** —
    조용히 None 을 반환하면 "고도 조회 실패"만 남아 원인을 알 수 없다.
    """
    params = {
        "latitude": ",".join(f"{la:.4f}" for la, _ in points),
        "longitude": ",".join(f"{lo:.4f}" for _, lo in points),
    }
    reason = None
    for attempt in range(retries):
        try:
            r = requests.get(ELEVATION_URL, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                reason = f"HTTP {r.status_code}"
                time.sleep(5.0 * (attempt + 1))     # 분당 한도는 넉넉히 기다린다
                continue
            r.raise_for_status()
            values = r.json().get("elevation")
            if values and len(values) == len(points):
                return values, None
            reason = f"응답 길이 불일치 ({len(values) if values else 0}/{len(points)})"
            return [None] * len(points), reason
        except Exception as exc:
            reason = f"{type(exc).__name__}: {str(exc)[:60]}"
            if attempt == retries - 1:
                break
            time.sleep(3.0 * (attempt + 1))
    return [None] * len(points), reason or "재시도 초과"


def longest_sea_arc(is_sea):
    """원형 배열에서 가장 긴 연속 True 구간의 (시작 인덱스, 길이).

    전부 바다면 (0, n) — 섬이다. 전부 육지면 (None, 0).
    """
    n = len(is_sea)
    if all(is_sea):
        return 0, n
    if not any(is_sea):
        return None, 0

    best_start, best_len = None, 0
    i = 0
    # 육지에서 시작하도록 회전시켜 경계를 한 번만 만난다
    while is_sea[i]:
        i += 1
    start_offset = i
    cur_start, cur_len = None, 0
    for k in range(n):
        idx = (start_offset + k) % n
        if is_sea[idx]:
            if cur_len == 0:
                cur_start = idx
            cur_len += 1
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
        else:
            cur_len = 0
    return best_start, best_len


def circular_mid(start_idx, length):
    """구간의 중심 방위(도). 경계를 넘어가도 맞게 돈다."""
    return (start_idx * BEARING_STEP + (length - 1) * BEARING_STEP / 2.0) % 360


def analyze(loc):
    """해변 한 곳의 shore_normal / swell_window. 실패하면 None."""
    points = []
    for km in RADII_KM:
        for b in BEARINGS:
            points.append(offset(loc["lat"], loc["lon"], b, km))

    values, reason = elevations(points)
    if any(v is None for v in values):
        return {"error": reason or "알 수 없음"}

    n = len(BEARINGS)
    per_radius = [values[i * n:(i + 1) * n] for i in range(len(RADII_KM))]
    # 두 반경 모두 0 이하여야 바다
    is_sea = [all(r[j] is not None and r[j] <= 0 for r in per_radius)
              for j in range(n)]

    start, length = longest_sea_arc(is_sea)
    if start is None:
        return {"shore_normal_deg": None, "swell_window_deg": 0,
                "sea_bearings": 0, "note": "열린 바다 방위가 없다 — 좌표 확인 필요"}

    result = {
        "shore_normal_deg": round(circular_mid(start, length)),
        "swell_window_deg": length * BEARING_STEP,
        "sea_bearings": sum(is_sea),
    }
    if length == n:
        result["note"] = "전방위 바다 — 섬이거나 좌표가 해상에 있다"
    elif result["swell_window_deg"] < 60:
        result["note"] = "스웰 창이 좁다 — 만 안쪽이거나 좌표가 실제 입수점과 다를 수 있다"
    elif sum(is_sea) > length:
        result["note"] = f"바다 방위가 여러 토막이다(총 {sum(is_sea)}개 중 {length}개 구간 채택)"
    return result


def main():
    ap = argparse.ArgumentParser(
        description="해변이 바라보는 방위와 스웰 창 초안을 만든다")
    ap.add_argument("--region", help="이 지역만")
    ap.add_argument("--save", action="store_true",
                    help=f"{os.path.relpath(DEFAULT_OUT)} 에 저장")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    beaches = [b for b in load_locations()
               if not args.region or b["region"] == args.region]

    print(f"{'해변':16}{'지역':12}{'방위':>6}{'스웰창':>8}{'바다방위':>9}  비고")
    print("-" * 82)
    out = {}
    failed = []
    for loc in beaches:
        res = analyze(loc)
        name = loc.get("display_name", loc["beach"])
        if res.get("error"):
            print(f"{name:16}{loc['region']:12}{'—':>6}{'—':>8}{'—':>9}  "
                  f"고도 조회 실패 — {res['error']}")
            failed.append(name)
            continue
        out[str(loc["beach_id"])] = dict(
            beach=loc["beach"], display_name=name, region=loc["region"], **res)
        sn = res["shore_normal_deg"]
        print(f"{name:16}{loc['region']:12}"
              f"{(f'{sn}°' if sn is not None else '—'):>6}"
              f"{res['swell_window_deg']:>7}°{res['sea_bearings']:>8}/36"
              f"  {res.get('note','')}")
        time.sleep(1.2)     # 한 해변이 72좌표다 — 분당 한도를 넘지 않게 띄운다

    # ── 검수 대상 고르기 ──
    # 지역 단위로 편차를 보면 안 된다. 제주는 섬이라 남(180°)과 북(0°)이 마주보는 게
    # 정상이고, west_south 는 서해(만리포 285°)와 남해(남열 100°)가 섞여 있다.
    # 실제로 의심스러운 것은 **서로 가까운 해변끼리 방위가 크게 다른 경우**다.
    print("\n[지역별 방위]")
    by_region = {}
    for v in out.values():
        if v["shore_normal_deg"] is not None:
            by_region.setdefault(v["region"], []).append(
                (v["display_name"], v["shore_normal_deg"]))
    for region, items in sorted(by_region.items()):
        print(f"  {region:12} " + " · ".join(f"{n} {d}°" for n, d in items))

    def ang_diff(a, b):
        d = abs(a - b) % 360
        return min(d, 360 - d)

    NEAR_KM = 20.0
    coords = {str(b["beach_id"]): b for b in beaches}
    suspects = []
    ids = [i for i, v in out.items() if v["shore_normal_deg"] is not None]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = out[ids[i]], out[ids[j]]
            la, lb = coords[ids[i]], coords[ids[j]]
            km = haversine_km(la["lat"], la["lon"], lb["lat"], lb["lon"])
            if km > NEAR_KM:
                continue
            diff = ang_diff(a["shore_normal_deg"], b["shore_normal_deg"])
            if diff > 60:
                suspects.append((a["display_name"], b["display_name"], km, diff))

    print("\n[검수 우선순위] 가까운데 방위가 크게 다른 쌍 — 한쪽이 틀렸을 가능성")
    if suspects:
        for n1, n2, km, diff in sorted(suspects, key=lambda x: -x[3]):
            print(f"  {n1} ↔ {n2}   {km:.1f}km 인데 방위 차 {diff}°")
    else:
        print("  없음 — 가까운 해변끼리는 방위가 일관적이다")

    narrow = [(v["display_name"], v["swell_window_deg"]) for v in out.values()
              if v["shore_normal_deg"] is not None and v["swell_window_deg"] < 60]
    if narrow:
        print("\n[검수 필요] 스웰 창이 좁다 — 만 안쪽이거나 좌표가 실제 입수점과 다를 수 있다")
        for n, w in sorted(narrow, key=lambda x: x[1]):
            print(f"  {n} {w}°")

    if failed:
        print(f"\n[조회 실패 {len(failed)}곳] {', '.join(failed)}")
        print("  --region 으로 나눠 다시 돌리면 분당 한도를 피할 수 있다.")

    if args.save:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        # ── 기존 파일과 병합한다 ──
        # 고도 API 가 분당 한도(429)로 매번 한두 곳을 떨어뜨린다. 덮어쓰면
        # --region 으로 빠진 곳만 채울 때 나머지가 지워진다. 이번에 구한 값이
        # 이기고, 이번에 안 돈 해변은 기존 값을 유지한다.
        merged = {}
        if os.path.exists(args.out):
            try:
                with open(args.out, encoding="utf-8") as f:
                    merged = json.load(f).get("beaches", {})
            except (OSError, ValueError):
                merged = {}
        kept = len(set(merged) - set(out))
        merged.update(out)
        out = merged
        if kept:
            print(f"(기존 파일에서 {kept}곳 유지)")
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": f"Open-Meteo /v1/elevation · {BEARING_STEP}도 간격 "
                          f"{len(BEARINGS)}방위 · 반경 {RADII_KM} km 모두 0m 이하를 바다로 판정 "
                          f"· 가장 긴 연속 구간의 중심",
                "note": "초안이다. 실제 스팟을 아는 사람의 검수가 필요하다 "
                        "(docs/marine-data-audit.md Q3). swell_window_deg 가 60도 미만이거나 "
                        "인접 해변과 방위가 크게 다른 곳을 먼저 볼 것.",
                "beaches": out,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n저장: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
