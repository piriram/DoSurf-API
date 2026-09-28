#!/usr/bin/env python3
"""`locations.json` 의 해변 좌표가 틀렸는지 잡아낸다.

── 왜 이 스크립트가 필요한가 ──

2026-09-27~28 에 좌표 **7곳**이 틀린 것을 찾았다. 전부 2025-03~04 에 들어와
**1년 반 동안 그대로**였다. 아무도 모른 이유는 하나다 —

    Open-Meteo 의 `cell_selection=sea` 는 육지 좌표든 엉뚱한 좌표든
    가장 가까운 해상 격자를 찾아 **그럴듯한 숫자를 계속 돌려준다.**
    `null` 도 에러도 안 난다.

그래서 로그에도 앱에도 이상이 보이지 않았다. 영덕 부흥과 고성 천진은 그동안
**다른 해역의 파도를 보여주고 있었다.**

── 왜 `snap_distance_km` 임계값이 아닌가 ──

원래 계획은 "수집 격자까지의 스냅거리가 크면 경고"였다. **2026-09-28 실측으로
작동하지 않는 것이 확인됐다.**

    물치      실제 오차 21.5km  → 스냅거리 6.8km  (정상 범위)
    강릉 남애  실제 오차  3.3km  → 스냅거리 7.3km
    함덕      오류 없음         → 스냅거리 18.6km (32곳 중 최대)

틀린 좌표도 해안 근처면 스냅이 짧고, 맞는 좌표도 격자가 멀면 스냅이 길다.
**스냅거리는 좌표 오류와 상관이 약하다.**

── 실제로 7곳을 잡아낸 신호 ──

    A. 인접 겹침       같은 지역 해변 쌍이 너무 가깝다      (기하 — API 불필요)
    C. 고도 15m 초과    해변점이 내륙이거나 절벽 위다        (고도 API)
    D. 해상 좌표       해변점이 바다 한가운데다            (고도 API)

각 신호가 어느 해변을 잡는지는 `--fixtures` 회귀 테스트가 증명한다.

**「좌표 순서 역전」은 구현하지 않았다.** 백로그의 원안이었지만 `locations.json`
에 지리적 정렬 순서가 없다 — `beach_id` 는 등록 순서이고 위도로 정렬하면 어떤
배열이든 단조가 되므로 판정이 성립하지 않는다. 물치(21.5km 오차)는 신호 A 가
1.32km 로 잡으므로 공백이 아니다.

── 수집 경로에 넣지 않는다 ──

좌표는 자주 바뀌지 않으므로 매 수집마다 검사할 이유가 없다. 게다가 고도 API 는
**파랑 API 와 별개의 일일 한도**가 있고 **요청 수가 아니라 좌표 수로 센다** —
하루 8회 수집에 끼우면 금방 막힌다(2026-09-27 실제로 걸렸다).
좌표를 고친 뒤에 손으로 돌리는 도구다.

사용법:

    .venv/bin/python3 -m scripts.validate_locations              # 전부 (고도 API 32좌표)
    .venv/bin/python3 -m scripts.validate_locations --offline    # 기하 검사만, API 없음
    .venv/bin/python3 -m scripts.validate_locations --region yangyang
    .venv/bin/python3 -m scripts.validate_locations --fixtures   # 회귀 테스트

경고가 하나라도 있으면 종료코드 1 이다.
"""
import argparse
import itertools
import json
import math
import os
import sys
import time

import requests

from scripts.beach_registry import load_locations

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

# ── 임계값은 실측으로 정했다 (2026-09-29) ──
#
# 같은 지역 해변 쌍의 최소 거리를 32곳 전부 재 본 결과다.
#
#   정상 최솟값   사천진↔사천 2.12km · 인구↔기사문 2.20km · 월정↔김녕 3.36km
#   옛 오류값     남애3리 0.58km · 물치 1.32km
#
# **백로그의 1km 안은 물치(1.32km)를 놓치고, 월포↔부흥(0.85km)을 오탐한다.**
# 2km 로 잡으면 옛 오류 둘을 모두 잡고 정상 최솟값(2.12km)과 겹치지 않는다.
OVERLAP_KM = 2.0

# 해변 입수점이 이보다 높으면 내륙이거나 절벽 위다.
# 실측: 영덕 부흥 40m · 동해 대진 27m · 남애3리 26m · 포항 월포 24m · 고성 천진 23m
# 정상 해변은 0~5m 다. 예외는 중문 62m(주상절리 절벽) 하나로 아래 KNOWN_EXCEPTIONS 에 있다.
ELEV_MAX_M = 15.0

# 해상 좌표 판정: 이 반경의 방위가 전부 바다면 육지에서 그만큼 떨어져 있다.
# 강릉 남애 옛 좌표(37.9347, 128.8217)가 해안에서 3.3km 떨어진 바다였다.
OFFSHORE_RADIUS_KM = 2.0
OFFSHORE_BEARINGS = list(range(0, 360, 45))     # 8방위 — 해변당 8좌표로 싸다

# 좌표는 맞는데 신호가 걸리는 곳. **근거 없이 추가하지 말 것.**
KNOWN_EXCEPTIONS = {
    "3002": "중문 — 주상절리 절벽이라 DEM 이 절벽 위를 찍는다(62m). "
            "`jungmun` 대조 지점과 격자가 일치하므로 옮기면 오히려 어긋난다",
}

# ── 회귀 테스트 픽스처 ──
#
# 2026-09-27~29 에 고친 좌표들의 **틀렸던 값**이다. `--fixtures` 가 이것을 넣어
# **전부 잡히는지** 확인한다. 하나라도 통과하면 그 신호가 죽은 것이다.
#
# 옛 좌표는 git 이력에서 떴다 (9b21031^ · 29addbf^ · 4ed5933^ · a8ddabb^ ·
# 6d15e34^ · 264c42a^ 의 scripts/locations.json).
OLD_COORDS = [
    # (display_name, region, 옛 lat, 옛 lon, 기대 신호, 무엇이 틀렸나)
    ("영덕 부흥", "pohang", 36.4171, 129.3704, "elev",
     "해안에서 6km 내륙 · 고도 40m · 바다 방위 0/36"),
    ("포항 월포", "pohang", 36.2014, 129.3606, "elev",
     "해안에서 0.94km 내륙 · 고도 24m"),
    ("고성 천진", "sokcho", 38.376, 128.4762, "elev",
     "13km 북쪽(죽왕면 만 안쪽) · 고도 23m · 스웰창 30°"),
    ("물치", "yangyang", 37.9973, 128.7556, "overlap",
     "21.5km 남쪽 — 인구에서 1.32km 로 겹친다"),
    ("남애3리", "yangyang", 37.9694, 128.754, "overlap",
     "3.9km 북쪽 — 죽도에서 0.58km 로 겹친다"),
    ("동해 대진", "gangneung", 37.5383, 129.1042, "elev",
     "해안에서 1.06km 내륙 · 고도 27m · 스웰창 80°"),
    ("강릉 남애", "gangneung", 37.9347, 128.8217, "offshore",
     "해상 3.3km — 해안선은 경도 128.788 이다"),
    # 8번째는 **이 도구가 스스로 찾아낸 것**이다. 2026-09-27 에 영덕 부흥의 내륙
    # 좌표를 고칠 때 동쪽(해안) 대신 남쪽으로 옮겨, 포항 월포에서 0.85km 지점에
    # 얹어 놨다. 부흥리는 영덕군 남정면(36.27)이고 월포리는 포항시 청하면(36.20)
    # 이라 애초에 9km 떨어져 있어야 한다. 겹침 신호가 잡았다.
    ("영덕 부흥", "pohang", 36.195, 129.373, "overlap",
     "2026-09-27 수정이 24.7km 남쪽으로 잘못 옮겼다 — 월포에서 0.85km"),
]


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

    실패를 조용히 None 으로 돌리지 않는다 — "고도 조회 실패"만 남으면
    한도에 걸린 것인지 좌표가 이상한 것인지 구분할 수 없다.
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
                time.sleep(5.0 * (attempt + 1))
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


# ══════════════════════════════════════════════════════════════════
#  신호 A — 인접 겹침 (기하, API 불필요)
# ══════════════════════════════════════════════════════════════════

def check_overlap(beaches):
    """같은 지역 해변 쌍이 OVERLAP_KM 보다 가까우면 경고.

    파랑 격자(best_match 8km · ncep_gfswave016 18km)로는 둘이 확실히 같은 칸이라
    **수집값이 완전히 동일해진다.** 서로 다른 해변으로 등록한 의미가 없다.
    """
    out = []
    by_region = {}
    for b in beaches:
        by_region.setdefault(b["region"], []).append(b)

    for region, group in sorted(by_region.items()):
        for a, b in itertools.combinations(group, 2):
            km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            if km < OVERLAP_KM:
                out.append({
                    "signal": "overlap", "region": region, "km": round(km, 2),
                    "beaches": [a.get("display_name", a["beach"]),
                                b.get("display_name", b["beach"])],
                    "ids": [str(a["beach_id"]), str(b["beach_id"])],
                })
    return sorted(out, key=lambda x: x["km"])


def nearest_neighbor(beach, beaches):
    """같은 지역에서 가장 가까운 해변과의 거리. 혼자면 None."""
    same = [b for b in beaches
            if b["region"] == beach["region"] and b["beach_id"] != beach["beach_id"]]
    if not same:
        return None, None
    best = min(same, key=lambda b: haversine_km(
        beach["lat"], beach["lon"], b["lat"], b["lon"]))
    return (round(haversine_km(beach["lat"], beach["lon"], best["lat"], best["lon"]), 2),
            best.get("display_name", best["beach"]))


# ══════════════════════════════════════════════════════════════════
#  신호 C·D — 고도 / 해상 좌표 (고도 API)
# ══════════════════════════════════════════════════════════════════

def check_elevation(beaches):
    """해변점 고도와 해상 여부. 반환 {beach_id: {...}}.

    좌표 수를 아낀다 — 해변점 1좌표를 먼저 다 받고, **고도 0m 이하인 곳만**
    8방위를 더 쏜다. 32곳이면 32 + (해상 후보 × 8) 좌표다.
    `shore_normal.py` 의 전체 스캔이 2,300좌표인 것과 비교해 70분의 1이다.
    """
    result = {}
    points = [(b["lat"], b["lon"]) for b in beaches]
    values, reason = elevations(points)

    for b, elev in zip(beaches, values):
        bid = str(b["beach_id"])
        if elev is None:
            result[bid] = {"error": reason or "알 수 없음"}
            continue
        result[bid] = {"elev_m": elev}

    # 고도가 0m 이하인 곳만 해상 판정 — 육지에 있으면 물어볼 필요가 없다
    candidates = [b for b in beaches
                  if result[str(b["beach_id"])].get("elev_m") is not None
                  and result[str(b["beach_id"])]["elev_m"] <= 0]
    for b in candidates:
        ring = [offset(b["lat"], b["lon"], deg, OFFSHORE_RADIUS_KM)
                for deg in OFFSHORE_BEARINGS]
        ring_elev, ring_reason = elevations(ring)
        bid = str(b["beach_id"])
        if any(v is None for v in ring_elev):
            result[bid]["offshore_error"] = ring_reason or "알 수 없음"
            continue
        land = sum(1 for v in ring_elev if v > 0)
        result[bid]["land_bearings"] = land
        result[bid]["ring_max_m"] = max(ring_elev)
        time.sleep(1.0)     # 분당 한도를 넘지 않게 띄운다

    return result


def verdicts(beaches, elev_by_id, overlaps):
    """해변별 판정을 모은다. (경고 목록, 해변별 상세)"""
    overlap_ids = {}
    for o in overlaps:
        for i, bid in enumerate(o["ids"]):
            other = o["beaches"][1 - i]
            overlap_ids.setdefault(bid, []).append((o["km"], other))

    rows, warnings = [], []
    for b in beaches:
        bid = str(b["beach_id"])
        name = b.get("display_name", b["beach"])
        info = elev_by_id.get(bid, {})
        signals = []

        if info.get("error"):
            rows.append({"id": bid, "name": name, "region": b["region"],
                         "elev": None, "note": f"고도 조회 실패 — {info['error']}",
                         "signals": []})
            continue

        elev = info.get("elev_m")
        if elev is not None and elev > ELEV_MAX_M:
            signals.append(("elev", f"고도 {elev:.0f}m (> {ELEV_MAX_M:.0f}m) — "
                                    "내륙이거나 절벽 위다"))

        # 해상 좌표: 2km 8방위에 육지가 하나도 없다
        land = info.get("land_bearings")
        if land == 0:
            signals.append(("offshore", f"{OFFSHORE_RADIUS_KM:.0f}km 8방위가 전부 바다 "
                                        f"(최고 {info.get('ring_max_m')}m) — 해상 좌표다"))

        for km, other in overlap_ids.get(bid, []):
            signals.append(("overlap", f"{other} 에서 {km}km (< {OVERLAP_KM:.0f}km) — "
                                       "같은 격자로 떨어져 수집값이 동일해진다"))

        nn_km, nn_name = nearest_neighbor(b, beaches)
        row = {"id": bid, "name": name, "region": b["region"], "elev": elev,
               "land_bearings": land, "nn_km": nn_km, "nn_name": nn_name,
               "signals": signals}

        if signals and bid in KNOWN_EXCEPTIONS:
            row["exception"] = KNOWN_EXCEPTIONS[bid]
        elif signals:
            warnings.append(row)
        rows.append(row)

    return warnings, rows


# ══════════════════════════════════════════════════════════════════
#  회귀 테스트
# ══════════════════════════════════════════════════════════════════

def run_fixtures():
    """틀렸던 좌표 전부를 넣어 다시 잡히는지 확인한다.

    **이것이 이 도구가 작동한다는 증명이다.** 신호를 고치다가 하나를 죽이면
    여기서 드러난다.
    """
    current = load_locations()
    print(f"\n회귀 테스트 — 틀렸던 좌표 {len(OLD_COORDS)}곳을 넣는다 (2026-09-27~29)")
    print("=" * 96)

    # 옛 좌표로 치환한 목록을 만든다. 겹침 판정은 **나머지가 현재 좌표**여야
    # 의미가 있다 — 옛 좌표끼리 비교하면 그때의 상태를 재현하지 못한다.
    by_name = {b.get("display_name", b["beach"]): b for b in current}
    missing = [n for n, *_ in OLD_COORDS if n not in by_name]
    if missing:
        print(f"⚠ locations.json 에 없는 해변: {', '.join(missing)}")
        return 1

    # 고도는 한 번에 받는다 (7좌표)
    pts = [(la, lo) for _, _, la, lo, _, _ in OLD_COORDS]
    elevs, reason = elevations(pts)
    if any(v is None for v in elevs):
        print(f"⚠ 고도 조회 실패 — {reason}")
        print("  일일 한도라면 09:00 KST 에 풀린다. --offline 으로 겹침만 볼 수 있다.")
        return 2

    print(f"{'해변':10}{'기대신호':>9}{'고도':>7}{'최근접':>9}  판정   무엇이 틀렸나")
    print("-" * 96)

    failed = []
    for (name, region, la, lo, expect, why), elev in zip(OLD_COORDS, elevs):
        probe = dict(by_name[name], lat=la, lon=lo)
        others = [b for b in current
                  if b.get("display_name", b["beach"]) != name]
        nn_km, nn_name = nearest_neighbor(probe, others + [probe])

        caught = set()
        if elev > ELEV_MAX_M:
            caught.add("elev")
        if nn_km is not None and nn_km < OVERLAP_KM:
            caught.add("overlap")
        if elev <= 0:
            ring = [offset(la, lo, d, OFFSHORE_RADIUS_KM) for d in OFFSHORE_BEARINGS]
            ring_elev, _ = elevations(ring)
            if all(v is not None for v in ring_elev) and not any(v > 0 for v in ring_elev):
                caught.add("offshore")
            time.sleep(1.0)

        ok = expect in caught
        mark = "✅ 잡힘" if caught else "❌ 놓침"
        if not ok:
            mark = "⚠️ 다름" if caught else "❌ 놓침"
            failed.append((name, expect, sorted(caught)))
        print(f"{name:10}{expect:>9}{elev:>6.0f}m"
              f"{(f'{nn_km}km' if nn_km is not None else '—'):>9}  {mark}  {why}")
        if caught and sorted(caught) != [expect]:
            print(f"{'':10}{'':>9}{'':>7}{'':>9}         걸린 신호: {', '.join(sorted(caught))}")

    print("-" * 96)
    if failed:
        print(f"\n❌ {len(failed)}곳이 기대한 신호로 잡히지 않았다:")
        for name, expect, caught in failed:
            got = ", ".join(caught) if caught else "없음"
            print(f"   {name}: 기대 {expect} · 실제 {got}")
        return 1

    print(f"\n✅ {len(OLD_COORDS)}곳 전부 잡힌다. 세 신호가 살아 있다.")
    return 0


# ══════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="locations.json 해변 좌표가 틀렸는지 잡아낸다")
    ap.add_argument("--region", help="이 지역만 (고도 API 일일 한도를 나눠 쓴다)")
    ap.add_argument("--offline", action="store_true",
                    help="고도 API 없이 기하 검사(인접 겹침)만")
    ap.add_argument("--fixtures", action="store_true",
                    help=f"틀렸던 좌표 {len(OLD_COORDS)}곳으로 회귀 테스트")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 으로")
    args = ap.parse_args()

    if args.fixtures:
        return run_fixtures()

    everything = load_locations()
    beaches = [b for b in everything
               if not args.region or b["region"] == args.region]
    if not beaches:
        print(f"해당 지역이 없다: {args.region}")
        return 2

    # 겹침은 **지역 전체**로 봐야 한다 — --region 으로 잘라도 같은 지역이므로 문제없다
    overlaps = check_overlap(beaches)

    if args.offline:
        elev_by_id = {}
        print("(--offline: 고도 API 를 부르지 않는다. 고도·해상 신호는 건너뛴다)")
    else:
        n = len(beaches)
        print(f"고도 API 호출 — 해변 {n}곳 {n}좌표 + 해상 후보당 8좌표")
        elev_by_id = check_elevation(beaches)

    warnings, rows = verdicts(beaches, elev_by_id, overlaps)

    if args.json:
        print(json.dumps({"warnings": warnings, "beaches": rows},
                         ensure_ascii=False, indent=2))
        return 1 if warnings else 0

    print(f"\n{'해변':16}{'지역':12}{'고도':>7}{'최근접이웃':>12}  판정")
    print("-" * 96)
    for r in rows:
        elev = f"{r['elev']:.0f}m" if r.get("elev") is not None else "—"
        nn = (f"{r['nn_km']}km {r['nn_name']}"
              if r.get("nn_km") is not None else "—")
        if r.get("note"):
            verdict = r["note"]
        elif r.get("exception"):
            verdict = "예외 (문서화됨)"
        elif r["signals"]:
            verdict = " / ".join(s for _, s in r["signals"])
        else:
            verdict = "이상 없음"
        print(f"{r['name']:16}{r['region']:12}{elev:>7}{nn:>12}  {verdict}")

    if overlaps:
        print(f"\n[인접 겹침 {len(overlaps)}쌍] — {OVERLAP_KM:.0f}km 미만")
        for o in overlaps:
            print(f"  {o['beaches'][0]} ↔ {o['beaches'][1]}   "
                  f"{o['km']}km  ({o['region']})")
        print("  같은 격자로 떨어져 수집값이 완전히 동일해진다. 한쪽 좌표가 틀렸거나")
        print("  실제로 같은 해변이 두 번 등록된 것이다.")

    print("\n[임계값 근거]")
    print(f"  인접 겹침 {OVERLAP_KM:.0f}km — 정상 최솟값은 사천진↔사천 2.12km · 인구↔기사문 2.20km 다.")
    print(f"  고도 {ELEV_MAX_M:.0f}m   — 잡아낸 값 영덕 부흥 40m · 대진 27m · 월포 24m · 천진 23m.")
    print(f"  해상 좌표    — {OFFSHORE_RADIUS_KM:.0f}km 8방위에 육지가 하나도 없으면 바다 한가운데다.")

    for bid, why in sorted(KNOWN_EXCEPTIONS.items()):
        if any(r["id"] == bid for r in rows):
            print(f"\n[예외] {why}")

    if warnings:
        print(f"\n⚠ 경고 {len(warnings)}곳: "
              f"{', '.join(r['name'] for r in warnings)}")
        print("  좌표를 고쳤으면 다음을 함께 돌릴 것 —")
        print("    .venv/bin/python3 -m scripts.shore_normal --region <지역> --save")
        print("    .venv/bin/python3 -m scripts.grid_coverage --save")
        return 1

    print("\n✅ 경고 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
