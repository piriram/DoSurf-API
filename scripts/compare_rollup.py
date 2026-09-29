#!/usr/bin/env python3
"""`data/model_compare.jsonl` 누적분을 지점별로 집계한다.

`model_compare.py` 는 하루치 순위만 낸다. 하루치로 모델을 바꾸면
예전에 제거한 `+0.5` 보정의 재발이다 (docs/marine-data-plan.md).
이 스크립트가 여러 날을 모아서 결론을 내는 자리다.

사용:
    .venv/bin/python3 -m scripts.compare_rollup
    .venv/bin/python3 -m scripts.compare_rollup --summary-only   # 지점별 편향 표만
    .venv/bin/python3 -m scripts.compare_rollup --spot sokcho
    .venv/bin/python3 -m scripts.compare_rollup --reference windy

── 출력이 두 부분이다 ──

**1. 지점별 편향 요약 표** (맨 위). 열두 지점을 한 줄씩 나란히 놓는다.
보정계수는 "이 지점에 상수를 박아도 되는가"를 묻는 것이고 그 답은 지점끼리
비교해야 나온다. 아래 상세는 지점을 하나씩 찍으므로 그 비교가 안 된다.

**파고와 첨두주기는 다른 모델로 잰다.** 파고는 그 지역의 수집 모델
(`region_models`), 첨두주기는 `peak_period_model` 이다 — 첨두주기를 주는
모델이 ecmwf 계열뿐이라 지역 모델은 `wave_peak_period` 를 전부 `None` 으로
돌려준다. 지역 모델로 첨두 편향을 찾으면 n=0 만 나오고, 그건 "표본이 없다"가
아니라 **"그 모델에 애초에 첨두주기가 없다"** 는 뜻이다.

`grid_coverage.json` 의 적용 가능 해변을 같은 줄에 찍는다. **0곳인 지점
(`ulsan`·`yeosu`·`seogwipo`)의 편향은 구해도 쓸 데가 없다** — 격자가 다르면
편향이 전이되지 않는다.

**2. 지점별 상세** (기존 출력). 모델 순위·날짜별 1위·판정.

── 무엇을 보고 무엇을 무시하나 ──

  편향제거 MAE 평균   모델 선택 기준. 이게 낮은 모델이 흐름을 제일 잘 맞춘다
  편향 평균           MOS 보정계수 후보. 부호 그대로 빼면 된다
  편향 표준편차       보정계수를 상수로 박아도 되는지의 판단. 크면 상수화 불가
  1위 획득 횟수       날마다 1위가 바뀌면 아직 표본이 부족하다는 신호 (제주가 그랬다)

MAE 평균은 일부러 순위에서 뺐다. 편향과 모양 오차를 한 숫자에 섞기 때문이다.
참고용으로만 출력한다.
"""
import argparse
import json
import os
import statistics
import sys

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "model_compare.jsonl")

# --reference 로 고를 수 있는 기준. 값은 jsonl 키에 붙는 suffix.
REFERENCES = {
    "windfinder": ("", "Windfinder"),
    "windy": ("_windy", "Windy"),
}

# 이 표본 수 밑에서는 결론을 내지 않는다. 하루치로 상수를 박는 사고를 막는 선.
MIN_SAMPLES = 5


def dedupe(records):
    """(지점, 날짜)가 겹치면 나중 기록만 남긴다.

    같은 날 두 번 돌리면 그날이 평균에 두 번 들어가 가중치가 두 배가 된다.
    재실행은 앞의 기록을 고치려는 것이므로 마지막 것이 맞다.
    스키마가 바뀐 뒤 다시 돌린 날도 이 규칙으로 새 기록이 이긴다.
    """
    latest = {}
    for rec in records:
        latest[(rec.get("label"), rec.get("date"))] = rec
    return list(latest.values())


def load(path):
    if not os.path.exists(path):
        sys.exit(f"기록이 없다: {path}\n"
                 f"  model_compare.py 를 --out {path} 로 먼저 돌릴 것")
    records = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"⚠ {i}번째 줄 건너뜀: {exc}")
    return records


def mean(values):
    return statistics.fmean(values) if values else None


def stdev(values):
    # 표본 1개면 표준편차가 정의되지 않는다. 그건 '흩어짐 없음'이 아니라 '모름'이다.
    return statistics.stdev(values) if len(values) >= 2 else None


def collect(records, label, suffix):
    """{모델: {지표: [날짜별 값]}} 과 날짜별 1위를 모은다."""
    per_model = {}
    daily_best = []
    dates = set()
    legacy_days = 0        # 편향·상관 분리(2026-08) 이전에 기록된 날
    mean_period_days = 0   # 파주기를 평균주기 축으로 잰 날 (첨두 도입 2026-09-27 이전)

    for rec in records:
        if rec.get("label") != label:
            continue
        # 기준 metric 은 mae 다. mae_debiased 는 나중에 추가된 필드라
        # 예전 기록엔 없다 — 그 날을 통째로 버리면 표본이 사라진다.
        rows = [r for r in rec.get("results", [])
                if r.get(f"mae{suffix}") is not None]
        if not rows:
            continue
        dates.add(rec.get("date"))
        has_debiased = any(r.get(f"mae_debiased{suffix}") is not None for r in rows)
        if not has_debiased:
            legacy_days += 1
        # 파주기 축은 기록 시점에 따라 다르다. period_kind 가 없으면 첨두 도입
        # (2026-09-27) 이전이라 전부 평균주기다 — 첨두와 섞으면 결론이 뒤집힌다.
        if not any(r.get("period_kind") for r in rows):
            if any(r.get(f"mae_period_debiased{suffix}") is not None for r in rows):
                mean_period_days += 1
        for r in rows:
            acc = per_model.setdefault(r["model"], {
                "mae": [], "bias": [], "mae_debiased": [], "corr": [],
                "mae_period_debiased": [], "bias_period": [], "snap_km": [],
                "period_mean_days": 0,
                "windy_equivalent": r.get("windy_equivalent"),
            })
            for key, src in (("mae", f"mae{suffix}"),
                             ("bias", f"bias{suffix}"),
                             ("mae_debiased", f"mae_debiased{suffix}"),
                             ("corr", f"corr{suffix}")):
                value = r.get(src)
                if value is not None:
                    acc[key].append(value)

            # ── 파주기는 첨두(peak)로 잰 것만 쌓는다 ──
            # 기준값(Windfinder)이 첨두주기이므로 평균주기로 잰 날은 축이 다르다.
            # 버리지 않고 날 수만 세어 report() 가 몇 날이 그랬는지 밝힌다.
            period_value = r.get(f"mae_period_debiased{suffix}")
            if period_value is not None:
                if r.get("period_kind") == "peak":
                    acc["mae_period_debiased"].append(period_value)
                    if r.get(f"bias_period{suffix}") is not None:
                        acc["bias_period"].append(r[f"bias_period{suffix}"])
                else:
                    acc["period_mean_days"] += 1
            if r.get("snap_km") is not None:
                acc["snap_km"].append(r["snap_km"])
            # 예전 기록엔 windy_equivalent 가 없다. 나중 기록에서 채워지면 쓴다.
            if acc["windy_equivalent"] is None and r.get("windy_equivalent"):
                acc["windy_equivalent"] = r["windy_equivalent"]

        # 그날 편향제거 값이 있으면 그걸로, 없으면 MAE로 1위를 뽑는다.
        # 섞이면 아래 report() 가 몇 날이 옛 스키마인지 밝힌다.
        key = f"mae_debiased{suffix}" if has_debiased else f"mae{suffix}"
        best = min((r for r in rows if r.get(key) is not None),
                   key=lambda r: r[key], default=None)
        if best:
            daily_best.append((rec.get("date"), best["model"], best[key]))

    return (per_model, daily_best, sorted(d for d in dates if d),
            legacy_days, mean_period_days)


def cross_summary(records, label):
    """Windy와 Windfinder가 서로 얼마나 다른지의 누적 요약."""
    rows = [rec["cross_windy_vs_windfinder"] for rec in records
            if rec.get("label") == label and rec.get("cross_windy_vs_windfinder")]
    if not rows:
        return None
    return {
        "n": len(rows),
        "mae": mean([r["mae"] for r in rows if r.get("mae") is not None]),
        "bias": mean([r["bias"] for r in rows if r.get("bias") is not None]),
        "mae_debiased": mean([r["mae_debiased"] for r in rows
                              if r.get("mae_debiased") is not None]),
    }


# ══════════════════════════════════════════════════════════════════════
#  지점별 편향 요약 표
# ══════════════════════════════════════════════════════════════════════
#
# 아래 지점별 상세는 지점을 하나씩 따로 찍으므로 **열두 지점을 나란히 볼 수
# 없다.** 보정계수는 "이 지점에 상수를 박아도 되는가"를 묻는 것이고 그 답은
# 지점끼리 비교해야 나온다. 그래서 요약 표를 상세 위에 덧붙인다.
#
# **모델을 섞으면 의미가 없다.** 편향은 모델마다 다르므로, 각 지점에서
# **그 지역이 실제 수집에 쓰는 모델**(config.json 의 region_models)의 편향만 본다.
# 다른 모델이 그 지점에서 더 잘 맞아도 운영에 쓰이지 않으니 보정 대상이 아니다.

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
COVERAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "grid_coverage.json")

# 편향 절댓값이 이보다 작으면 보정할 게 없다. 격자 간 파고차(중앙값 0.020m)와
# 모델 1·2위 차(0.001m)를 감안한 선이다 — 그 아래는 측정 노이즈와 구분되지 않는다.
BIAS_NEGLIGIBLE_M = 0.05

# 첨두주기 쪽 대응값. **임시값이다** — 파고 0.05m 는 격자 간 파고차(0.020m)와
# 모델 1·2위 차(0.001m) 실측에서 나왔는데, 주기에는 아직 그 실측이 없다.
# 표본 5일이 모이면(10/1 예정) 다시 정한다.
PERIOD_BIAS_NEGLIGIBLE_S = 0.3


def region_models():
    """config.json 의 지역별 수집 모델. (지역→모델, 기본모델, 첨두주기모델)

    **파고와 첨두주기는 서로 다른 모델에서 온다.** 파고는 지역 모델이고
    첨두주기는 `peak_period_model` 하나다 — 첨두주기를 주는 모델이 ecmwf
    계열뿐이라 지역 모델(`ncep_gfswave016`·`best_match`)은 값을 전부 `None`
    으로 돌려준다. 그래서 요약 표도 두 축을 다른 모델로 재야 한다.
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            marine = json.load(f)["marine"]
        return (marine.get("region_models", {}), marine.get("default_model"),
                marine.get("peak_period_model"))
    except (OSError, ValueError, KeyError):
        return {}, None, None


def load_coverage():
    """grid_coverage.json 의 지점별 적용 가능 해변. 없으면 None."""
    if not os.path.exists(COVERAGE_PATH):
        return None
    try:
        with open(COVERAGE_PATH, encoding="utf-8") as f:
            return json.load(f).get("spots", {})
    except (OSError, ValueError):
        return None


def spot_regions():
    """지점이 담당하는 지역. model_compare 의 정의를 그대로 쓴다.

    import 를 함수 안에 둔 것은 순환 import 를 피하려는 것이다 —
    grid_coverage.py 가 model_compare 를 import 하고 있다.
    """
    try:
        from scripts.model_compare import REFERENCE_SPOTS
        return {n: s.get("regions", []) for n, s in REFERENCE_SPOTS.items()}
    except Exception:
        return {}


def verdict(n, bias, sigma, negligible):
    """보정계수를 상수로 박아도 되는지. 판정 규칙은 지점별 상세와 같다."""
    if n < MIN_SAMPLES:
        return "표본부족", f"n<{MIN_SAMPLES}"
    if bias is None:
        return "측정없음", "편향 값이 없다"
    if abs(bias) <= negligible:
        return "불필요", f"|편향|≤{negligible}"
    if sigma is None:
        return "σ모름", "표본 2일 미만"
    if sigma < abs(bias) / 2:
        return "가능", "σ<|편향|/2"
    return "σ초과", "상수화 금지"


def summary_table(records, suffix, ref_name, labels):
    """지점별 한 줄 요약. 파고와 첨두주기를 **다른 모델로** 따로 낸다."""
    rm, default, peak_model = region_models()
    coverage = load_coverage()
    regions_of = spot_regions()

    rows = []
    for label in labels:
        per_model, _, dates, _, _ = collect(records, label, suffix)
        if not per_model:
            continue

        regions = regions_of.get(label, [])
        wave_models = {rm.get(r, default) for r in regions} or {default}

        rows.append({
            "label": label, "regions": regions, "days": len(dates),
            "per_model": per_model,
            "wave_model": sorted(wave_models)[0] if len(wave_models) == 1 else None,
            "mixed": len(wave_models) > 1,
            "applies": coverage.get(label, {}).get("applies_to") if coverage else None,
        })

    if not rows:
        # 조용히 빠지면 --summary-only 가 아무 출력 없이 성공한 것처럼 보인다.
        # Windy 기준이 대표적이다 — 자동 수집이 Windy 를 안 받아 전부 null 이다.
        print(f"\n지점별 편향 요약: 기준 {ref_name} 로 집계할 값이 없다.")
        print(f"  검사한 지점 {len(labels)}곳 전부 그 기준의 기록이 비어 있다.")
        return

    has_coverage = coverage is not None

    def coverage_cell(applies):
        if not has_coverage:
            return ""
        if applies is None:
            return "커버리지 미상"
        if not applies:
            return "⚠ 0곳 — 이 편향은 쓸 데가 없다"
        return f"{len(applies)}곳  " + ", ".join(applies)

    def block(title, bias_key, unit, fmt, model_of, negligible):
        print(f"\n{'=' * 104}")
        print(f"지점별 편향 요약 · 기준 {ref_name} · {title}")
        print("=" * 104)
        # 한글은 터미널에서 두 칸을 차지한다. 헤더 폭을 데이터 행에 맞춰 손으로 뺀다.
        print(f"{'지점':<8}{'모델':>13}{'n':>4}{'편향평균':>6}{'편향σ':>8}"
              f"  {'판정':<6}" + ("적용 해변" if has_coverage else ""))
        print("-" * 104)

        for r in rows:
            label = r["label"]
            model = model_of(r)
            if model is None:
                print(f"{label:10}{'— 지역 혼재 —':>15}{'':>4}{'':>10}{'':>10}"
                      f"  담당 지역이 {r['regions']} 인데 모델이 다르다")
                continue
            acc = r["per_model"].get(model)
            if acc is None:
                print(f"{label:10}{model:>15}{'':>4}{'미측정':>10}{'':>10}"
                      f"  이 모델로 잰 기록이 없다")
                continue

            values = acc[bias_key]
            n = len(values)
            b, s = mean(values), stdev(values)
            verd, _ = verdict(n, b, s, negligible)

            print(f"{label:10}{model:>15}{n:>4}"
                  f"{(fmt(b) if b is not None else '—'):>10}"
                  f"{(f'{s:.3f}' if s is not None else '—'):>10}"
                  f"  {verd:8}{coverage_cell(r['applies'])}")

        print("-" * 104)
        print(f"판정: 표본부족 n<{MIN_SAMPLES} · 불필요 |편향|≤{negligible}{unit} · "
              f"가능 σ<|편향|/2 · σ초과는 상수화 금지")

    block("파고 (m) — 지역 수집 모델", "bias", "m",
          lambda v: f"{v:+.3f}", lambda r: r["wave_model"], BIAS_NEGLIGIBLE_M)

    # ── 첨두주기는 지역 모델이 아니라 peak_period_model 로 잰다 ──
    # 지역 모델(ncep_gfswave016 · best_match)은 wave_peak_period 를 전부 None
    # 으로 돌려준다. 그 모델의 첨두 편향을 찾으면 n=0 만 나오고, 그것은
    # "표본이 없다"가 아니라 "애초에 그 모델에 첨두주기가 없다"는 뜻이다.
    if peak_model:
        block(f"첨두주기 (초) — peak_period_model = {peak_model}",
              "bias_period", "초", lambda v: f"{v:+.2f}",
              lambda r: peak_model, PERIOD_BIAS_NEGLIGIBLE_S)
    else:
        print("\n(config.json 에 marine.peak_period_model 이 없어 "
              "첨두주기 표를 건너뛴다)")

    print()
    print("**편향은 격자가 같은 해변에만 전이된다.** 격자 간 파고차가 중앙값")
    print("0.020m 로 모델 1·2위 차(0.001m)를 20배 압도한다 (2026-09-27 실측).")
    print("적용 해변이 0곳인 지점의 편향은 구해도 쓸 곳이 없다.")
    if not has_coverage:
        print()
        print("⚠ data/grid_coverage.json 이 없어 적용 해변을 못 찍었다 —")
        print("  .venv/bin/python3 -m scripts.grid_coverage --save 로 만들 것.")
    print()
    print(f"⚠ 첨두주기의 '불필요' 기준 {PERIOD_BIAS_NEGLIGIBLE_S}초는 "
          "**임시값이고 근거가 약하다.**")
    print("  파고 0.05m 는 격자 간 파고차(0.020m)와 모델 1·2위 차(0.001m)에서")
    print("  나온 값인데, 주기에는 그에 대응하는 실측이 아직 없다. 표본이")
    print("  5일을 넘으면(10/1 예정) 이 임계값부터 다시 정할 것.")


def report(label, per_model, daily_best, dates, ref_name, cross,
           legacy_days=0, mean_period_days=0):
    print(f"\n{'=' * 78}")
    print(f"{label}  ·  기준 {ref_name}  ·  {len(dates)}일 "
          f"({dates[0]} ~ {dates[-1]})" if dates else f"{label}  ·  기준 {ref_name}")
    print("=" * 78)

    if not per_model:
        print("집계할 기록이 없다.")
        return

    if cross:
        print(f"\n[기준끼리 · {cross['n']}일 평균] Windy vs Windfinder — "
              f"MAE {cross['mae']:.3f}m · 편향 {cross['bias']:+.3f}m · "
              f"모양차 {cross['mae_debiased']:.3f}m")

    # 편향·상관 분리가 들어가기 전(2026-08)에 남은 기록은 MAE밖에 없다.
    # 그 날들을 편향제거 평균에 섞으면 안 되므로 표본 수(n)로 드러낸다.
    if legacy_days:
        print(f"\n⚠️ {legacy_days}일치는 편향·상관 분리 이전 기록이라 MAE만 있다.")
        print("   편향제거 열의 n 이 그만큼 작다. 결론은 n 을 보고 낼 것.")

    use_debiased = any(a["mae_debiased"] for a in per_model.values())

    header = (f"{'모델':<20}{'n':>4}{'편향제거':>10}{'편향평균':>10}"
              f"{'편향σ':>9}{'상관':>9}{'MAE':>9}{'격자':>8}")
    print(f"\n{header}")
    print("-" * max(len(header), 84))

    rank_key = "mae_debiased" if use_debiased else "mae"
    ranked = sorted(
        ((m, a) for m, a in per_model.items() if a[rank_key]),
        key=lambda kv: mean(kv[1][rank_key]))
    if not use_debiased:
        print("\n(편향제거 값이 하나도 없어 MAE로 순위를 매긴다 — 모양과 편향이 섞인 값이다)")

    def num(values, fmt, width):
        return (fmt.format(mean(values)) if values else "-").rjust(width)

    for model, acc in ranked:
        bias_sd = stdev(acc["bias"])
        corr_avg = mean(acc["corr"])
        mark = " *" if acc["windy_equivalent"] else ""
        print(f"{model + mark:<20}{len(acc[rank_key]):>4}"
              f"{num(acc['mae_debiased'], '{:.3f}', 10)}"
              f"{num(acc['bias'], '{:+.3f}', 10)}"
              f"{(f'{bias_sd:.3f}' if bias_sd is not None else '-'):>9}"
              f"{(f'{corr_avg:.4f}' if corr_avg is not None else '-'):>9}"
              f"{mean(acc['mae']):>9.3f}"
              f"{mean(acc['snap_km']):>7.1f}k")

    legend = [f"{m}={a['windy_equivalent']}" for m, a in ranked if a["windy_equivalent"]]
    if legend:
        print(f"  * Windy 등가 모델: {' · '.join(legend)}")

    # ── 날마다 1위가 바뀌는가 ──
    wins = {}
    for _date, model, _score in daily_best:
        wins[model] = wins.get(model, 0) + 1
    print(f"\n[날짜별 1위] " + " · ".join(
        f"{m} {c}회" for m, c in sorted(wins.items(), key=lambda kv: -kv[1])))

    n_days = len(daily_best)
    top_model, top_acc = ranked[0]
    n = len(top_acc[rank_key])

    print("\n[판정]")
    if not use_debiased:
        print("  편향·상관이 없는 옛 기록뿐이다. 모델 선택 근거로 쓸 수 없다.")
        print("  model_compare.py 를 --out 으로 다시 돌려 새 스키마로 쌓을 것.")
    elif n < MIN_SAMPLES:
        print(f"  표본 {n}일. {MIN_SAMPLES}일 미만이라 결론 보류.")
        print(f"  매일 model_compare.py 를 --out 으로 돌려 {MIN_SAMPLES - n}일 더 쌓을 것.")
    elif len(wins) > 1 and max(wins.values()) < n_days * 0.6:
        print(f"  1위가 날마다 바뀐다 ({len(wins)}개 모델이 돌아가며 1위).")
        print("  지금 모델을 바꾸면 하루치 노이즈를 상수로 박는 것이다. 더 쌓을 것.")
    else:
        print(f"  1위: {top_model} — 편향제거 MAE {mean(top_acc[rank_key]):.3f}m "
              f"({n}일, 1위 {wins.get(top_model, 0)}회)")
        bias_avg = mean(top_acc["bias"])
        bias_sd = stdev(top_acc["bias"])
        if bias_sd is not None and abs(bias_avg) > 0.05:
            if bias_sd < abs(bias_avg) / 2:
                print(f"  편향 {bias_avg:+.3f}m 이 {bias_sd:.3f}m 안에서 안정적이다.")
                print(f"  → MOS 보정계수 {-bias_avg:+.3f}m 를 검토할 만하다.")
            else:
                print(f"  편향 {bias_avg:+.3f}m 인데 흔들림이 {bias_sd:.3f}m 로 크다.")
                print("  → 상수 보정 금지. 날마다 다른 값을 상수로 박는 셈이다.")
        else:
            print("  편향이 작다. 보정계수 불필요.")

    # ── 파주기: 첨두주기로 잰 날만 쓴다 ──
    # 기준값(Windfinder)이 첨두주기다. 평균주기로 잰 날을 섞으면 축이 다른 값이
    # 한 평균에 들어가고, 정의 차이가 모델 차이로 보인다.
    period_rows = [(m, a) for m, a in ranked if a["mae_period_debiased"]]
    mean_only = [(m, a) for m, a in ranked
                 if not a["mae_period_debiased"] and a.get("period_mean_days")]

    print("\n[파주기 · 첨두주기로 잰 날만]")
    if mean_period_days:
        print(f"  ⚠️ {mean_period_days}일치는 평균주기 축으로 기록됐다 "
              f"(첨두 도입 2026-09-27 이전).")
        print("     축이 달라 집계에서 뺐다. 그 날들의 파주기 순위는 근거로 쓸 수 없다.")

    if not period_rows:
        print("  첨두주기로 잰 기록이 아직 없다.")
        print("  daily_compare.sh 가 매일 쌓는다 — --models 에 ecmwf_wam025·ecmwf_wam 가")
        print("  들어 있어야 한다. 결론까지 최소 "
              f"{MIN_SAMPLES}일.")
    else:
        for model, acc in sorted(period_rows,
                                 key=lambda kv: mean(kv[1]["mae_period_debiased"])):
            values = acc["mae_period_debiased"]
            bias_avg = mean(acc["bias_period"])
            bias_txt = f" · 편향 {bias_avg:+.2f}s" if bias_avg is not None else ""
            print(f"    {mean(values):.3f}s  {model}  ({len(values)}일{bias_txt})")

        best_p = min(period_rows, key=lambda kv: mean(kv[1]["mae_period_debiased"]))
        n_p = len(best_p[1]["mae_period_debiased"])
        if n_p < MIN_SAMPLES:
            print(f"  → 표본 {n_p}일. {MIN_SAMPLES}일 미만이라 파주기 결론 보류.")
        elif len(period_rows) < 2:
            print(f"  → 1위 {best_p[0]} — 다만 비교 대상이 하나뿐이라 순위가 아니다.")
        else:
            print(f"  → 1위 {best_p[0]} ({n_p}일)")

        if mean_only:
            names = " · ".join(m for m, _ in mean_only)
            print(f"  (평균주기만 주는 모델은 제외: {names})")

        if period_rows and best_p[0] != top_model:
            print(f"  파고 1위는 {top_model} 다. 첨두주기를 주는 모델이 ecmwf 계열뿐이라")
            print("  갈리는 게 정상이고, 수집도 파주기만 별도 모델에서 받고 있다")
            print("  (config.json 의 peak_period_model).")


def main():
    ap = argparse.ArgumentParser(description="model_compare 누적 기록을 집계한다")
    ap.add_argument("--path", default=DEFAULT_PATH, help="JSON Lines 경로")
    ap.add_argument("--spot", help="이 지점만 집계 (기본: 기록에 있는 전부)")
    ap.add_argument("--reference", choices=sorted(REFERENCES), default="windfinder",
                    help="어느 기준으로 순위를 낼지 (기본: windfinder)")
    ap.add_argument("--summary-only", action="store_true",
                    help="지점별 편향 요약 표만 (상세 생략)")
    ap.add_argument("--no-summary", action="store_true",
                    help="요약 표를 빼고 기존 상세만")
    args = ap.parse_args()

    records = load(args.path)
    if not records:
        sys.exit("기록이 비어 있다.")

    before = len(records)
    records = dedupe(records)
    if before != len(records):
        print(f"(같은 지점·날짜 중복 {before - len(records)}건은 최신 기록만 남겼다)")

    suffix, ref_name = REFERENCES[args.reference]
    labels = [args.spot] if args.spot else sorted(
        {r.get("label") for r in records if r.get("label")})

    # 요약을 상세보다 먼저 찍는다. 지점이 열둘이면 상세가 화면을 넘겨서
    # 뒤에 붙이면 안 보인다.
    if not args.no_summary:
        summary_table(records, suffix, ref_name, labels)
    if args.summary_only:
        return 0

    printed = 0
    for label in labels:
        (per_model, daily_best, dates,
         legacy_days, mean_period_days) = collect(records, label, suffix)
        if not per_model:
            print(f"\n{label}: 기준 {ref_name} 로 집계할 값이 없다.")
            if args.reference == "windy":
                print("  model_compare.py 에 --reference-windy 를 주고 다시 쌓을 것.")
            continue
        report(label, per_model, daily_best, dates, ref_name,
               cross_summary(records, label), legacy_days, mean_period_days)
        printed += 1

    if printed == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
