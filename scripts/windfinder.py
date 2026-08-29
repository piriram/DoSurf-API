"""Windfinder 예보 페이지에서 파고·파주기를 읽어온다.

우리 모델(Open-Meteo)을 고르는 **검증 기준**으로만 쓴다. 서퍼들이 실제로 보는
값이 Windfinder이기 때문이다 (docs/marine-data-audit.md 「검증 기준」).
여기서 받은 값은 Firestore에 저장하지 않고 앱에도 싣지 않는다.

── 지켜야 할 선 ──

Windfinder는 이 데이터를 파는 API가 따로 있다(api.windfinder.com). 그래서
가져오는 방식에 제약을 둔다.

- `/forecast/` 만 읽는다. robots.txt가 `/api/`, `/widget/forecast/`,
  `/share/forecast/`, `/wind-cgi/*` 를 막고 있으므로 그쪽은 건드리지 않는다.
- 하루 1~2회로 충분하다. 폴링하지 않는다. 같은 날 같은 지점은 캐시를 쓴다.
- User-Agent에 용도와 연락처를 밝힌다.
- 상업적 재배포 금지 (이용약관). 이 파일의 결과가 사용자에게 나가면 안 된다.

── 깨질 수 있는 곳 ──

파고/파주기 셀의 class에 빌드 해시가 붙는다 (`_cell-wave-height_1i1fy_215`).
해시는 배포마다 바뀌므로 접두사로만 매칭한다. 시각(`cell-ts`)과 날짜(`fc-day`)
class는 해시가 없어 상대적으로 안정적이다.
그래도 사이트 개편이 나면 파싱이 깨진다. 값이 안 나오면 여기부터 의심할 것.
"""
import datetime
import json
import os
import re
import time

import requests

BASE = "https://www.windfinder.com/forecast"
UA = ("DoSurf-validation/1.0 (personal, non-commercial forecast validation; "
      "contact pyoram25@gmail.com)")

# model_compare.py 와 같은 시각 격자
HOURS = [0, 3, 6, 9, 12, 15, 18, 21]

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "windfinder_cache")

# class 해시를 무시하고 접두사로만 잡는다
RE_DAY = re.compile(r'<div class="fc-day"[^>]*>(.*?)(?=<div class="fc-day"|$)', re.S)
RE_HEADLINE = re.compile(r'fc-day-headline[^>]*>\s*(?:<span[^>]*>)?\s*([^<]+?)\s*<')
RE_ROW = re.compile(r'class="cell-ts">\s*(\d{1,2})h\s*<(.*?)(?=class="cell-ts">|$)', re.S)
# 숫자와 단위 사이가 narrow no-break space(U+202F)다. 일반 공백이 아니므로
# 명시적으로 넣어둔다.
_SP = r'[\s  ]*'
RE_WAVE = re.compile(
    r'class="[^"]*cell-wave-height[^"]*"[^>]*>' + _SP +
    r'<div class="[^"]*data-major[^"]*"[^>]*>' + _SP + r'([\d.]+)' + _SP + r'm' + _SP + r'</div>' + _SP +
    r'<div class="[^"]*data-minor[^"]*"[^>]*>' + _SP + r'([\d.]+)' + _SP + r's' + _SP + r'</div>', re.S)


def _cache_path(spot, date):
    return os.path.join(CACHE_DIR, f"{spot}_{date}.json")


def fetch_html(spot, timeout=20):
    """예보 페이지 HTML. 같은 날 같은 지점은 캐시를 재사용한다."""
    today = datetime.date.today().isoformat()
    path = _cache_path(spot, today)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)["html"], True

    resp = requests.get(f"{BASE}/{spot}", headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    # requests가 헤더만 보고 인코딩을 잘못 잡으면 숫자와 단위 사이의
    # narrow no-break space(U+202F)가 깨져서 파싱이 조용히 실패한다.
    resp.encoding = "utf-8"
    html = resp.text

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"spot": spot, "fetched_at": datetime.datetime.now().isoformat(),
                   "html": html}, f)
    time.sleep(1)  # 연속 호출 시 간격
    return html, False


def parse(html):
    """{ "Sunday, Aug 30": {0: (height_m, period_s), 3: (...), ...}, ... }"""
    out = {}
    for day_html in RE_DAY.findall(html):
        headline = RE_HEADLINE.search(day_html)
        if not headline:
            continue
        label = headline.group(1).strip()
        hours = {}
        for hour, row in RE_ROW.findall(day_html):
            wave = RE_WAVE.search(row)
            if wave:
                hours[int(hour)] = (float(wave.group(1)), float(wave.group(2)))
        if hours:
            out[label] = hours
    return out


def reference_series(spot, day_index=0):
    """model_compare.py 의 --reference / --reference-period 에 넣을 8개씩.

    반환: (label, heights, periods). 값이 빠진 시각은 None.
    day_index 0 이 페이지 첫 날(보통 오늘)이다.
    """
    html, cached = fetch_html(spot)
    days = parse(html)
    if not days:
        raise RuntimeError(
            f"{spot}: 파싱 결과가 비었다. 사이트 구조가 바뀌었을 수 있다 "
            f"(scripts/windfinder.py 의 정규식 확인)")
    labels = list(days)
    if day_index >= len(labels):
        raise IndexError(f"{spot}: {len(labels)}일치만 있다 (요청 index={day_index})")
    label = labels[day_index]
    hours = days[label]
    heights = [hours[h][0] if h in hours else None for h in HOURS]
    periods = [hours[h][1] if h in hours else None for h in HOURS]
    return label, heights, periods, cached


if __name__ == "__main__":
    import sys
    for spot in (sys.argv[1:] or ["sokcho"]):
        label, heights, periods, cached = reference_series(spot)
        src = "캐시" if cached else "신규 수집"
        print(f"\n=== {spot} · {label} ({src}) ===")
        print(f"시각   {'  '.join(f'{h:02d}h' for h in HOURS)}")
        print(f"파고   {'  '.join(f'{v:.1f}' if v else ' - ' for v in heights)}")
        print(f"주기   {'  '.join(f'{v:.0f}  ' if v else ' -  ' for v in periods)}")
        print()
        print("model_compare.py 에 넣으려면:")
        print(f"  --reference {','.join(str(v) for v in heights if v is not None)}")
        print(f"  --reference-period {','.join(str(v) for v in periods if v is not None)}")
