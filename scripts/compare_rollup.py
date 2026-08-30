#!/usr/bin/env python3
"""`data/model_compare.jsonl` 누적분을 지점별로 집계한다.

`model_compare.py` 는 하루치 순위만 낸다. 하루치로 모델을 바꾸면
예전에 제거한 `+0.5` 보정의 재발이다 (docs/marine-data-plan.md).
이 스크립트가 여러 날을 모아서 결론을 내는 자리다.

사용:
    .venv/bin/python3 -m scripts.compare_rollup
    .venv/bin/python3 -m scripts.compare_rollup --spot sokcho
    .venv/bin/python3 -m scripts.compare_rollup --reference windy

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
    legacy_days = 0   # 편향·상관 분리(2026-08) 이전에 기록된 날

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
        for r in rows:
            acc = per_model.setdefault(r["model"], {
                "mae": [], "bias": [], "mae_debiased": [], "corr": [],
                "mae_period_debiased": [], "bias_period": [], "snap_km": [],
                "windy_equivalent": r.get("windy_equivalent"),
            })
            for key, src in (("mae", f"mae{suffix}"),
                             ("bias", f"bias{suffix}"),
                             ("mae_debiased", f"mae_debiased{suffix}"),
                             ("corr", f"corr{suffix}"),
                             ("mae_period_debiased", f"mae_period_debiased{suffix}"),
                             ("bias_period", f"bias_period{suffix}")):
                value = r.get(src)
                if value is not None:
                    acc[key].append(value)
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

    return per_model, daily_best, sorted(d for d in dates if d), legacy_days


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


def report(label, per_model, daily_best, dates, ref_name, cross, legacy_days=0):
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

    period_rows = [(m, a) for m, a in ranked if a["mae_period_debiased"]]
    if period_rows:
        best_p = min(period_rows, key=lambda kv: mean(kv[1]["mae_period_debiased"]))
        print(f"\n[파주기] 1위 {best_p[0]} — "
              f"편향제거 MAE {mean(best_p[1]['mae_period_debiased']):.3f}s "
              f"({len(best_p[1]['mae_period_debiased'])}일)")
        if best_p[0] != top_model:
            print(f"  ⚠️ 파고 1위({top_model})와 다르다. 한 모델로 둘 다 못 맞춘다.")


def main():
    ap = argparse.ArgumentParser(description="model_compare 누적 기록을 집계한다")
    ap.add_argument("--path", default=DEFAULT_PATH, help="JSON Lines 경로")
    ap.add_argument("--spot", help="이 지점만 집계 (기본: 기록에 있는 전부)")
    ap.add_argument("--reference", choices=sorted(REFERENCES), default="windfinder",
                    help="어느 기준으로 순위를 낼지 (기본: windfinder)")
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

    printed = 0
    for label in labels:
        per_model, daily_best, dates, legacy_days = collect(records, label, suffix)
        if not per_model:
            print(f"\n{label}: 기준 {ref_name} 로 집계할 값이 없다.")
            if args.reference == "windy":
                print("  model_compare.py 에 --reference-windy 를 주고 다시 쌓을 것.")
            continue
        report(label, per_model, daily_best, dates, ref_name,
               cross_summary(records, label), legacy_days)
        printed += 1

    if printed == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
