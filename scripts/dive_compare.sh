#!/bin/bash
# 서귀포 앞 다이빙 포인트 세 곳(문섬·섶섬·범섬)을 Windfinder 와 대조한다.
#
# ── 왜 daily_compare.sh 와 따로인가 ──
#
# 이 셋은 서핑 해변이 아니라 스쿠버 다이빙 포인트라 locations.json(해변 32곳)에
# 없다. 운영 수집 대상이 아니므로 대조 기록도 섞지 않는다 —
#
#   출력 파일  data/dive_compare.jsonl   (해변 쪽은 data/model_compare.jsonl)
#   launchd    등록하지 않았다. 손으로 돌린다
#
# 따라서 이 스크립트는 운영 수집·launchd 에이전트·compare_rollup 의 해변 결론
# 어느 것에도 영향을 주지 않는다. 롤업을 보려면 파일을 지정한다:
#
#   bash scripts/dive_compare.sh
#   .venv/bin/python3 -m scripts.compare_rollup --path data/dive_compare.jsonl
#
# ── 좌표 ──
#
# OSM 에서 `islet` 로 등록된 섬 자체의 중심이다(Nominatim, 2026-09-30).
# 다이빙샵 주소(올블루=보목동 748 · 제주씨스타다이브=호근동 2003)는 육지라
# 해양 예보 좌표로 쓸 수 없다. 배를 타고 나가는 곳은 섬이다.
#
# ── 기준값은 세 곳이 같다 ──
#
# Windfinder 에 섬별 지점이 없어 셋 다 `seogwipo` 페이지를 기준으로 쓴다.
# 그러므로 섬끼리의 편향 차이는 **모델의 공간 차이만** 뜻하고, 실제로 그 섬의
# 파도가 그렇다는 뜻이 아니다. 한 지점으로 세 곳을 재는 한계다.
#
# 다만 격자는 맞다 — 문섬·범섬이 best_match 에서 `seogwipo` 지점과 **같은 칸**
# (33.208336, 126.54167)에 떨어진다(2026-09-30 실측). `seogwipo` 는 격자가 맞는
# 해변이 0곳이라 daily_compare.sh 에서 빠졌는데, 다이빙 포인트에는 쓸 데가 있다.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python3"
OUT="$REPO/data/dive_compare.jsonl"
LOGDIR="$REPO/data/compare_log"      # daily_compare.sh 와 공유한다(30일 정리 포함)

WINDFINDER="seogwipo_jeju-do_south_korea"

# 이름:위도:경도 — OSM islet 중심
SITES=(
  "munseom:33.2263146:126.5658877"    # 문섬  (송산동 앞)
  "seopseom:33.2301425:126.5984946"   # 섶섬  (보목동 앞)
  "beomseom:33.2180733:126.5166353"   # 범섬  (대륜동 앞)
)

# ── ecmwf_wam025 를 넣어 두는 이유 ──
#
# 운영 config.json 의 `peak_period_model` 이 ecmwf_wam025 인데, **문섬·섶섬에서는
# 이 모델이 파고·첨두 24개 전부 None 이다**(2026-09-30 실측). 25km 격자가
# (33.25, 126.75) 육지 칸에 떨어지고 `cell_selection=sea` 로도 못 살린다.
# ecmwf_wam(9km)은 세 곳 전부 24/24 값이 온다.
#
# 그래서 여기서 첨두주기를 쓰려면 ecmwf_wam 이어야 한다. 025 는 범섬에서만
# 값이 오는데, 그 한 곳에서 첨두 순위의 유일한 비교 대상이라 남겨 둔다.
# 각 실행의 "결측" 줄이 그 근거 기록이다.
MODELS="best_match,ncep_gfswave016,gwam,ecmwf_wam,ecmwf_wam025"

mkdir -p "$LOGDIR"
LOG="$LOGDIR/dive-$(date +%F).log"

echo "=== $(date '+%F %T %Z') 다이빙 포인트 대조 시작 ===" >>"$LOG"

if [[ ! -x "$PY" ]]; then
  echo "  ✗ 파이썬이 없다: $PY" >>"$LOG"
  echo "파이썬이 없다: $PY" >&2
  exit 1
fi

failed=0
for site in "${SITES[@]}"; do
  IFS=: read -r name lat lon <<<"$site"
  echo "--- $name ($lat, $lon)" >>"$LOG"
  if "$PY" -m scripts.model_compare \
        --lat "$lat" --lon "$lon" --label "$name" \
        --from-windfinder "$WINDFINDER" \
        --models "$MODELS" --out "$OUT" >>"$LOG" 2>&1; then
    # 종료코드만 믿지 않는다 — Windfinder 파싱이 깨져 기준이 비어도
    # 스크립트는 정상 종료한다(daily_compare.sh 와 같은 이유).
    if tail -60 "$LOG" | grep -q "기록 추가"; then
      echo "  ✓ $name 기록됨" >>"$LOG"
    else
      echo "  ⚠ $name 실행은 됐는데 기록이 안 붙었다 — Windfinder 파싱 확인" >>"$LOG"
      failed=1
    fi
  else
    echo "  ✗ $name 실패 (종료코드 $?)" >>"$LOG"
    failed=1
  fi
done

echo "누적: $(wc -l <"$OUT" | tr -d ' ')건" >>"$LOG"
find "$LOGDIR" -name '*.log' -mtime +30 -delete 2>/dev/null

echo "=== 종료 (failed=$failed) ===" >>"$LOG"
echo "로그: $LOG"
exit $failed
