"""Copernicus Marine(CMEMS) 전지구 파랑 예보에서 파고·파주기·파향을 읽는다.

Open-Meteo 대안 후보 검증용이다 (docs/MARINE_DATA_INVESTIGATION.md 5장).
`scripts/open_meteo.py` 의 `fetch_marine()` 과 **같은 모양의 행**을 돌려주므로
`model_compare.py` 가 Open-Meteo 모델과 나란히 놓고 잴 수 있다.

여기서 받은 값은 Firestore에 저장하지 않는다. 검증 결과를 보고 채택 여부를
정한 뒤에야 수집 경로에 넣는다.

── 왜 REST가 아닌가 ──

CMEMS는 위경도 단건 조회 REST가 없다. 대신 토큰박스(`copernicusmarine`)가
ARCO(zarr) 저장소를 lazy 하게 열어주므로, 필요한 격자 상자와 시간 범위만
잘라서 받으면 NetCDF 전체를 내려받지 않아도 된다.
docs/MARINE_DATA_INVESTIGATION.md 에 "NetCDF 파일을 직접 파싱해야 함"이라고
적혀 있는데, 그건 툴박스 v1 시절 얘기다 (2026-08-31 v2.4.1로 확인).

── 자격증명 ──

무료 계정이 필요하다. https://marine.copernicus.eu 에서 직접 가입한 뒤:

    .venv/bin/copernicusmarine login

한 번 실행하면 `~/.copernicusmarine` 에 저장돼 이후엔 필요 없다.
환경변수 `COPERNICUSMARINE_SERVICE_USERNAME` / `_PASSWORD` 도 쓸 수 있다.

── 이 제품에 없는 것 ──

수온과 조석은 이 파랑 제품에 없다. 각각 물리(PHY) 제품과 조석 제품이 따로다.
그러므로 CMEMS로 갈아탄다 해도 수온은 Open-Meteo에 계속 의존해야 한다
(CLAUDE.md 「확인된 사실」).
"""
import datetime
import math
import os

DATASET_ID = "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i"

# 우리 스키마 ← CMEMS 변수명.
#
# 파주기가 둘인 게 핵심이다. CMEMS는 평균주기와 첨두주기를 따로 준다.
#   VTM10  평균주기 — Open-Meteo `wave_period` 와 같은 계열이라 사과 대 사과 비교용
#   VTPK   첨두주기 — Windfinder·서핑 앱이 화면에 쓰는 값
# 둘 다 받아서 어느 쪽이 Windfinder와 맞는지 보는 것이 이 검증의 목적 중 하나다.
VARIABLES = [
    "VHM0",       # 유의파고
    "VMDR",       # 파향
    "VTM10",      # 평균주기
    "VTPK",       # 첨두주기
    "VHM0_SW1", "VMDR_SW1", "VTM01_SW1",   # 1차 스웰
    "VHM0_WW", "VMDR_WW", "VTM01_WW",      # 윈드웨이브
]

FIELD_MAP = {
    "wave_height": "VHM0",
    "wave_direction": "VMDR",
    "wave_period": "VTM10",
    "wave_period_peak": "VTPK",
    "swell_wave_height": "VHM0_SW1",
    "swell_wave_direction": "VMDR_SW1",
    "swell_wave_period": "VTM01_SW1",
    "wind_wave_height": "VHM0_WW",
    "wind_wave_direction": "VMDR_WW",
    "wind_wave_period": "VTM01_WW",
}

# open_meteo.py 와 같은 물리 범위 검사. 기준이 다르면 비교가 의미 없다.
VALUE_RANGES = {
    "wave_height": (0.0, 30.0),
    "swell_wave_height": (0.0, 30.0),
    "wind_wave_height": (0.0, 30.0),
    "wave_period": (0.0, 30.0),
    "wave_period_peak": (0.0, 30.0),
    "swell_wave_period": (0.0, 30.0),
    "wind_wave_period": (0.0, 30.0),
    "wave_direction": (0.0, 360.0),
    "swell_wave_direction": (0.0, 360.0),
    "wind_wave_direction": (0.0, 360.0),
}

KST_OFFSET = datetime.timedelta(hours=9)

# 0.083° 격자에서 몇 칸을 확보할 상자 크기. 육지 격자를 피해 바다 칸을 고르려면
# 한 점만 봐서는 안 된다 — Open-Meteo 의 `cell_selection=sea` 를 손으로 하는 셈이다.
BOX_DEGREES = 0.5


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _num(value, name):
    """숫자로 바꾸고 범위를 벗어나면 None. NaN(육지·결측)도 None."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    lo, hi = VALUE_RANGES.get(name, (float("-inf"), float("inf")))
    if v < lo or v > hi:
        return None
    return v


CREDENTIALS_FILE = os.path.expanduser(
    "~/.copernicusmarine/.copernicusmarine-credentials")

_SIGNUP = (
    "  무료 계정이 필요하다. https://data.marine.copernicus.eu/register 에서\n"
    "  직접 가입한 뒤 아래를 한 번 실행할 것:\n"
    "      .venv/bin/copernicusmarine login\n"
    "  또는 환경변수 COPERNICUSMARINE_SERVICE_USERNAME / _PASSWORD 를 설정한다.")


def _credentials_hint(exc):
    return RuntimeError(f"CMEMS 접근 실패: {exc}\n{_SIGNUP}")


def has_credentials():
    """자격증명이 있는지 미리 본다.

    없는 상태로 open_dataset 을 부르면 툴박스가 **대화형으로 아이디를 묻는다.**
    스크립트나 배치에서는 그게 EOF 로 끊기고 `None` 이 돌아와서, 원인과 무관한
    `'NoneType' object is not subscriptable` 로 터진다. 그 혼란을 막으려고
    먼저 확인한다.
    """
    if os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") and \
            os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD"):
        return True
    return os.path.exists(CREDENTIALS_FILE)


def _pick_sea_cell(ds, lat, lon):
    """요청 좌표에서 가장 가까운 **바다** 격자를 고른다.

    가장 가까운 칸이 육지면 파고가 NaN 으로 온다. 그 상태로 비교하면
    "결측이 많은 모델"로 잘못 판정된다. VHM0 가 하나라도 유효한 칸 중에서
    제일 가까운 것을 고르는 이유다.

    반환: (선택된 ds, grid_lat, grid_lon, 거리km)
    """
    import numpy as np

    valid = ds["VHM0"].notnull().any(dim="time")
    lats = ds["latitude"].values
    lons = ds["longitude"].values
    mask = np.asarray(valid.values)
    if not mask.any():
        raise RuntimeError(
            f"({lat}, {lon}) 주변 {BOX_DEGREES}° 안에 바다 격자가 없다. "
            "좌표를 확인하거나 BOX_DEGREES 를 키울 것")

    best = None
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            if not mask[i, j]:
                continue
            d = haversine_km(lat, lon, float(la), float(lo))
            if best is None or d < best[0]:
                best = (d, float(la), float(lo))

    dist, glat, glon = best
    return ds.sel(latitude=glat, longitude=glon, method="nearest"), glat, glon, dist


def fetch_marine(lat, lon, *, forecast_days=3, start_date=None):
    """CMEMS 파랑 예보를 Open-Meteo 와 같은 모양으로 돌려준다.

    반환: (hours, meta)

    hours 각 원소:
      - om_datetime: "YYYY-MM-DDTHH:MM:SS" (naive KST) — open_meteo.py 와 같은 규약
      - wave_height / wave_direction / wave_period / wave_period_peak
      - swell_wave_* / wind_wave_*

    수온·조석은 이 제품에 없어 키 자체가 없다.

    ── 시각 정렬 ──
    원본은 UTC 3시간 간격이다. KST 오프셋 +9h 가 3의 배수라 KST로 옮겨도
    0,3,6,...,21시에 그대로 떨어진다. 보간이 필요 없다는 뜻이고,
    이건 우연이 아니라 ALLOWED_HOURS 와 맞아떨어지는 조건이다.
    """
    try:
        import copernicusmarine as cm
    except ImportError as exc:
        raise RuntimeError(
            "copernicusmarine 이 없다. .venv/bin/pip install copernicusmarine\n"
            "  (배포용 requirements.txt 에는 넣지 말 것 — 검증 전용 도구다)") from exc

    if start_date is None:
        start_kst = datetime.datetime.now() .replace(
            hour=0, minute=0, second=0, microsecond=0)
    else:
        start_kst = datetime.datetime.fromisoformat(str(start_date))
    end_kst = start_kst + datetime.timedelta(days=forecast_days)

    # 조회는 UTC로 한다. 경계에서 잘리지 않도록 앞뒤로 한 스텝씩 여유를 준다.
    start_utc = start_kst - KST_OFFSET - datetime.timedelta(hours=3)
    end_utc = end_kst - KST_OFFSET + datetime.timedelta(hours=3)

    if not has_credentials():
        raise RuntimeError("CMEMS 자격증명이 없다.\n" + _SIGNUP)

    try:
        ds = cm.open_dataset(
            dataset_id=DATASET_ID,
            variables=VARIABLES,
            minimum_latitude=lat - BOX_DEGREES,
            maximum_latitude=lat + BOX_DEGREES,
            minimum_longitude=lon - BOX_DEGREES,
            maximum_longitude=lon + BOX_DEGREES,
            start_datetime=start_utc,
            end_datetime=end_utc,
        )
    except Exception as exc:
        raise _credentials_hint(exc) from exc

    # 툴박스는 실패해도 예외 대신 None 을 돌려줄 때가 있다 (인증·카탈로그 오류)
    if ds is None:
        raise RuntimeError(
            f"open_dataset 이 None 을 돌려줬다 — 인증 실패이거나 "
            f"{DATASET_ID} 조회가 거부됐다.\n" + _SIGNUP)

    point, glat, glon, dist = _pick_sea_cell(ds, lat, lon)
    point = point.load()   # 여기서 처음 실제로 내려받는다

    times = [t for t in point["time"].values]
    columns = {}
    for field, var in FIELD_MAP.items():
        columns[field] = point[var].values if var in point else [None] * len(times)

    out = []
    for i, t in enumerate(times):
        # numpy datetime64(UTC) → naive KST
        utc = datetime.datetime.fromisoformat(str(t)[:19])
        kst = utc + KST_OFFSET
        row = {"om_datetime": kst.strftime("%Y-%m-%dT%H:%M:%S")}
        for field in FIELD_MAP:
            values = columns[field]
            row[field] = _num(values[i], field) if i < len(values) else None
        out.append(row)

    meta = {
        "model": "cmems_glo_wav",
        "dataset_id": DATASET_ID,
        "grid_lat": glat,
        "grid_lon": glon,
        "snap_distance_km": round(dist, 2),
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    return out, meta


if __name__ == "__main__":
    import sys

    lat, lon = 38.2500, 128.5660     # 속초 (model_compare.py REFERENCE_SPOTS)
    if len(sys.argv) >= 3:
        lat, lon = float(sys.argv[1]), float(sys.argv[2])

    rows, meta = fetch_marine(lat, lon, forecast_days=1)
    print(f"{meta['dataset_id']}  격자 ({meta['grid_lat']}, {meta['grid_lon']}) "
          f"· {meta['snap_distance_km']}km")
    print(f"\n{'시각(KST)':<20}{'파고':>7}{'평균주기':>9}{'첨두주기':>9}{'파향':>7}")
    for r in rows:
        def f(key, fmt="{:.2f}"):
            v = r.get(key)
            return fmt.format(v) if v is not None else "-"
        print(f"{r['om_datetime']:<20}{f('wave_height'):>7}"
              f"{f('wave_period'):>9}{f('wave_period_peak'):>9}"
              f"{f('wave_direction', '{:.0f}'):>7}")
