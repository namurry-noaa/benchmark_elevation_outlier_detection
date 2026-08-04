"""
s05_injection_experiment.py -- Stage 05 of the OPUS outlier-analysis pipeline.

The objective "which method fits best" grading proxy.

Because real data has no ground-truth outlier labels, we manufacture ground
truth: take real, clean-enough donor groups (native MAD small, n large enough),
plant ONE synthetic outlier of known magnitude into a randomly chosen
observation, re-run all four detection methods, and record:

    * detection    : did the method flag the PLANTED point?         (true positive)
    * false alarm  : did the method flag any UNTOUCHED point?       (false positive)

Averaged over many trials and offset magnitudes this yields, per method:
    - detection rate  vs  injected offset  (sensitivity / power)
    - false-alarm rate                      (specificity cost)

This is the closest thing to an ROC-style, defensible comparison available for
this problem. It grades the methods, not the marks.

Outputs:
  s05_injection_results.csv  -- one row per (donor, offset, trial, method)
  s05_injection_summary.csv  -- aggregated detection/false-alarm rate per
                                (offset, method)

Dependency-light: standard library only.

Run:  python pipeline/s05_injection_experiment.py
"""

from __future__ import annotations

import csv
import os
import random
import statistics as stats
import sys
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402

S03_OBS_FLAGS_CSV = os.path.join(config.TABLES_DIR, "s03_obs_flags.csv")

METHODS = ("fixed", "s1", "s2", "mad")


def _median_abs_dev(values, med):
    return stats.median(abs(v - med) for v in values)


def classify(values):
    """
    Run all four methods on a list of floats (n>=3 assumed).
    Return a list of dicts (parallel to values), each with a bool per method.
    Mirrors the logic in s03 exactly so the experiment grades the real methods.
    """
    n = len(values)
    mean = stats.fmean(values)
    median = stats.median(values)
    std = stats.stdev(values) if n >= 2 else None
    mad = _median_abs_dev(values, median)
    denom = config.MAD_SCALE * mad if mad > 0 else None

    out = []
    for v in values:
        rmean = v - mean
        rmed = v - median
        flag_fixed = abs(rmean) > config.FIXED_TOLERANCE_M
        flag_s1 = bool(std) and abs(rmean) > config.SIGMA_1 * std
        flag_s2 = bool(std) and abs(rmean) > config.SIGMA_2 * std
        if denom is not None:
            flag_mad = abs(rmed / denom) > config.MAD_THRESHOLD
        else:
            flag_mad = False
        out.append({
            "fixed": flag_fixed, "s1": flag_s1, "s2": flag_s2, "mad": flag_mad,
        })
    return out


def load_donor_groups():
    """
    From stage-03, gather clean-enough donor groups for the configured window
    and height: real n>=INJ_MIN_DONOR_N groups with native MAD <= threshold.
    Returns dict pid -> list of float values.
    """
    win = config.INJ_WINDOW
    ht = config.INJ_HEIGHT_TARGET
    groups = defaultdict(list)
    with open(S03_OBS_FLAGS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["window"] == win and r["height_target"] == ht:
                try:
                    groups[r["pid"]].append(float(r["value"]))
                except (ValueError, TypeError):
                    pass

    donors = {}
    for pid, vals in groups.items():
        if len(vals) < config.INJ_MIN_DONOR_N:
            continue
        med = stats.median(vals)
        if _median_abs_dev(vals, med) <= config.INJ_MAX_DONOR_MAD_M:
            donors[pid] = vals
    return donors


def run():
    if not os.path.exists(S03_OBS_FLAGS_CSV):
        raise FileNotFoundError(
            f"Stage-03 output not found: {S03_OBS_FLAGS_CSV}\nRun s03 first."
        )
    donors = load_donor_groups()
    rng = random.Random(config.INJ_SEED)
    config.ensure_dirs()

    # detail rows + aggregation accumulators
    # agg[(offset, method)] = [n_trials, n_detected, n_false_alarm]
    agg = defaultdict(lambda: [0, 0, 0])

    detail_fields = ["pid", "donor_n", "offset_m", "trial", "injected_index",
                     "method", "detected_planted", "false_alarm"]

    with open(config.S05_INJECTION_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=detail_fields)
        w.writeheader()

        for pid, base_vals in donors.items():
            n = len(base_vals)
            for offset in config.INJ_OFFSETS_M:
                for trial in range(config.INJ_TRIALS_PER_CASE):
                    idx = rng.randrange(n)
                    # random sign so we don't bias high/low
                    sign = 1 if rng.random() < 0.5 else -1
                    trial_vals = list(base_vals)
                    trial_vals[idx] = base_vals[idx] + sign * offset

                    flags = classify(trial_vals)
                    for meth in METHODS:
                        planted = flags[idx][meth]
                        # false alarm: any NON-injected obs flagged
                        fa = any(flags[j][meth] for j in range(n) if j != idx)
                        agg[(offset, meth)][0] += 1
                        agg[(offset, meth)][1] += 1 if planted else 0
                        agg[(offset, meth)][2] += 1 if fa else 0
                        w.writerow({
                            "pid": pid, "donor_n": n, "offset_m": offset,
                            "trial": trial, "injected_index": idx,
                            "method": meth,
                            "detected_planted": int(planted),
                            "false_alarm": int(fa),
                        })

    # summary
    with open(config.S05_INJECTION_SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["offset_m", "method", "trials",
                    "detection_rate", "false_alarm_rate"])
        for (offset, meth) in sorted(agg.keys()):
            t, det, fa = agg[(offset, meth)]
            w.writerow([offset, meth, t,
                        round(det / t, 4) if t else "",
                        round(fa / t, 4) if t else ""])

    return {
        "n_donors": len(donors),
        "offsets": config.INJ_OFFSETS_M,
        "trials_per_case": config.INJ_TRIALS_PER_CASE,
        "agg": agg,
    }


def main() -> None:
    rep = run()
    print("=" * 70)
    print("STAGE 05  synthetic-outlier injection experiment  -- COMPLETE")
    print("=" * 70)
    print(f"  donor groups (clean, n>={config.INJ_MIN_DONOR_N}, "
          f"MAD<={config.INJ_MAX_DONOR_MAD_M} m) : {rep['n_donors']}")
    print(f"  window={config.INJ_WINDOW}  height={config.INJ_HEIGHT_TARGET}  "
          f"trials/case={rep['trials_per_case']}")
    print("-" * 70)
    print("  DETECTION RATE by injected offset (fraction of planted outliers caught):")
    print(f"    {'offset(cm)':>10} {'4cm':>8} {'1sig':>8} {'2sig':>8} {'MAD':>8}")
    for offset in config.INJ_OFFSETS_M:
        row = [f"{offset*100:6.0f}"]
        for meth in METHODS:
            t, det, fa = rep["agg"][(offset, meth)]
            row.append(f"{det/t:8.3f}" if t else "     n/a")
        print(f"    {row[0]:>10} {row[1]} {row[2]} {row[3]} {row[4]}")
    print("-" * 70)
    print("  FALSE-ALARM RATE (fraction of trials flagging an untouched obs):")
    print(f"    {'offset(cm)':>10} {'4cm':>8} {'1sig':>8} {'2sig':>8} {'MAD':>8}")
    for offset in config.INJ_OFFSETS_M:
        row = [f"{offset*100:6.0f}"]
        for meth in METHODS:
            t, det, fa = rep["agg"][(offset, meth)]
            row.append(f"{fa/t:8.3f}" if t else "     n/a")
        print(f"    {row[0]:>10} {row[1]} {row[2]} {row[3]} {row[4]}")
    print("-" * 70)
    print(f"  detail  : {config.S05_INJECTION_CSV}")
    print(f"  summary : {config.S05_INJECTION_SUMMARY_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    main()
