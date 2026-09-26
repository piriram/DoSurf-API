#!/bin/bash
# 매일 한 번 Windfinder 대조를 돌려 data/model_compare.jsonl 에 쌓는다.
#
# 모델 궁합은 하루치로 못 정한다(1·2위 차이가 측정 노이즈보다 작다).
# 표본이 자동으로 모여야 결론을 낼 수 있어서 만든 스크립트다.
#
# launchd 가 부른다: ~/Library/LaunchAgents/com.dosurf.compare.plist
# 손으로 돌려도 된다: bash scripts/daily_compare.sh
#
# Windy 값은 여기서 안 받는다. 무료 API가 난수를 주고 스크래핑은 막혀 있어
# 사람이 넣어야 한다(CLAUDE.md 「Windy까지 3자 대조」).
# 나중에 --reference-windy 로 같은 날짜를 다시 돌리면 롤업이 최신 것만 쓴다.

set -uo pipefail

# 저장소 위치는 이 스크립트 위치에서 구한다 — 맥을 바꿔도 안 깨진다.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python3"
OUT="$REPO/data/model_compare.jsonl"
LOGDIR="$REPO/data/compare_log"
# 지점이 표본을 늘리는 유일한 축이다 — 같은 날 여러 번 돌려도 롤업이
# (지점, 날짜)로 중복을 제거해서 표본은 하루 1개다.
# wolpo(포항) · mallipo(태안) · seogwipo/hamdok(제주 남·북동) · yeosu(남해안)를
# 2026-09-27 에 추가했다. pohang·west_south 는 대조 근거 없이 모델이 정해져
# 있었고, 제주는 남(33.22)~북동(33.56)이 파도가 달라 한 지점으로 못 대표한다.
# busan(3곳)은 Windfinder 페이지를 못 찾아 아직 공백이다.
# seogwipo 는 뺐다 - 격자가 (33.21,126.54)로 locations.json 의 어느 해변과도
# 맞지 않아 결론을 적용할 해변이 0곳이다. jungmun·mosulpo 가 중문·사계 격자에
# 정확히 떨어져 그 역할을 대신한다. 필요하면 손으로 --spot seogwipo 를 돌린다.
SPOTS=(sokcho jeju wolpo mallipo jungmun mosulpo hamdok yeosu gisamun donghae ulsan)

# 파고 후보 전체 + 첨두주기를 주는 ecmwf 계열.
#
# ecmwf_wam 을 ecmwf_wam025 와 함께 넣는다. 첨두주기(wave_peak_period)를 값으로
# 주는 Open-Meteo 모델이 이 둘뿐이라(2026-09-27 실측), 하나만 넣으면 파주기에
# 비교 대상이 없어 순위가 성립하지 않는다. 격자도 다르게 스냅된다 -
# 속초에서 ecmwf_wam 6.9km vs ecmwf_wam025 16.1km.
#
# cmems 는 뺐다 - 자격증명이 만료되면 조용히 실패하고, 파고에서 이기지도 않았다.
# 필요하면 손으로 --models 에 cmems,cmems_peak 를 붙여 돌린다.
MODELS="best_match,ncep_gfswave025,ncep_gfswave016,ecmwf_wam025,ecmwf_wam,gwam,meteofrance_wave"

mkdir -p "$LOGDIR"
today=$(date +%F)
LOG="$LOGDIR/$today.log"

echo "=== $(date '+%F %T %Z') 대조 시작 ===" >>"$LOG"

if [[ ! -x "$PY" ]]; then
  echo "  ✗ 파이썬이 없다: $PY" >>"$LOG"
  exit 1
fi

failed=0
for spot in "${SPOTS[@]}"; do
  echo "--- $spot" >>"$LOG"
  if "$PY" -m scripts.model_compare \
        --spot "$spot" --from-windfinder \
        --models "$MODELS" --out "$OUT" >>"$LOG" 2>&1; then
    # 기록이 실제로 붙었는지 본다. 종료코드만 믿으면
    # Windfinder 파싱이 깨져 기준이 비어도 성공으로 보인다.
    if tail -40 "$LOG" | grep -q "기록 추가"; then
      echo "  ✓ $spot 기록됨" >>"$LOG"
    else
      echo "  ⚠ $spot 실행은 됐는데 기록이 안 붙었다 — Windfinder 파싱 확인" >>"$LOG"
      failed=1
    fi
  else
    echo "  ✗ $spot 실패 (종료코드 $?)" >>"$LOG"
    failed=1
  fi
done

echo "누적: $(wc -l <"$OUT" | tr -d ' ')건" >>"$LOG"

# 로그는 30일치만 남긴다
find "$LOGDIR" -name '*.log' -mtime +30 -delete 2>/dev/null

echo "=== 종료 (failed=$failed) ===" >>"$LOG"
exit $failed
