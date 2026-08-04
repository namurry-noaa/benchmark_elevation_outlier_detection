"""
s04_per_pid_summary.py -- Stage 04 of the OPUS outlier-analysis pipeline.

Purpose:
  Collapse the stage-03 per-observation audit table to ONE ROW per
  (PID x window x height_target), computing:

    * group size and descriptive stats (raw mean/median/std/MAD, min/max/range)
    * per-method flag counts
    * each method's CLEANED AVERAGE = mean of its survivors (method A, confirmed)
    * a "consensus" cleaned average (drop obs flagged by >= 2 of the 4 methods)
    * the representative height that will flow to the CO-OPS join, chosen per
      the group-size policy:
          single_obs -> the single value
          mean_n2    -> plain mean of the two
          multi_method -> (carried; the *chosen* production method is a
                           downstream decision -- we expose all candidates here)

Edge handling:
  * If a method flags EVERY observation (e.g. the 4cm rule on a noisy mark),
    its cleaned average is undefined -> we record the count as n and leave the
    cleaned-average blank, plus set a *_all_flagged marker. This is itself a
    finding and must not silently fall back to the raw mean.

Output: s04_per_pid_summary.csv
Dependency-light: standard library only.

Run:  python pipeline/s04_per_pid_summary.py
"""

from __future__ import annotations

import csv
import os
import statistics as stats
import sys
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402

S03_OBS_FLAGS_CSV = os.path.join(config.TABLES_DIR, "s03_obs_flags.csv")
S04_SUMMARY_CSV = os.path.join(config.TABLES_DIR, "s04_per_pid_summary.csv")

METHODS = ("fixed", "s1", "s2", "mad")

OUT_FIELDS = [
    "pid", "window", "height_target",
    "n", "group_method",
    "raw_mean", "raw_median", "raw_std", "raw_mad",
    "min", "max", "range",
    # per-method flagged counts
    "n_flag_fixed", "n_flag_s1", "n_flag_s2", "n_flag_mad",
    # per-method cleaned averages (mean of survivors) + all-flagged markers
    "clean_avg_fixed", "fixed_all_flagged",
    "clean_avg_s1", "s1_all_flagged",
    "clean_avg_s2", "s2_all_flagged",
    "clean_avg_mad", "mad_all_flagged",
    # consensus: drop obs flagged by >= 2 methods
    "n_flag_consensus", "clean_avg_consensus", "consensus_all_flagged",
    # the value that flows to the CO-OPS join (policy-driven)
    "representative_height", "representative_source",
]


def _f(s):
    if s is None or s.strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(x):
    return "" if x is None else repr(x)


def _survivor_mean(members, flag_key):
    """Mean of members whose flag_key == '0'. Returns (mean_or_None, all_flagged_bool)."""
    survivors = [m["value"] for m in members if m[flag_key] == "0"]
    if not survivors:
        return None, True
    return stats.fmean(survivors), False


def _consensus_mean(members):
    """Mean of members with consensus_flags < 2. Returns (mean_or_None, all_flagged)."""
    survivors = [m["value"] for m in members if int(m["consensus_flags"]) < 2]
    if not survivors:
        return None, True
    return stats.fmean(survivors), False


def run():
    src = S03_OBS_FLAGS_CSV
    if not os.path.exists(src):
        raise FileNotFoundError(
            f"Stage-03 output not found: {src}\nRun s03_group_methods.py first."
        )

    # Group rows by (pid, window, height_target).
    groups = defaultdict(list)
    with open(src, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["value"] = _f(r["value"])
            groups[(r["pid"], r["window"], r["height_target"])].append(r)

    config.ensure_dirs()
    report = {"rows": 0, "all_flagged": defaultdict(int)}

    with open(S04_SUMMARY_CSV, "w", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=OUT_FIELDS)
        writer.writeheader()

        for (pid, window, height), members in groups.items():
            vals = [m["value"] for m in members]
            n = len(vals)
            gm = members[0]["group_method"]

            raw_mean = stats.fmean(vals)
            raw_median = stats.median(vals)
            raw_std = stats.stdev(vals) if n >= 2 else None
            raw_mad = stats.median(abs(v - raw_median) for v in vals)
            vmin, vmax = min(vals), max(vals)

            row = {
                "pid": pid, "window": window, "height_target": height,
                "n": n, "group_method": gm,
                "raw_mean": _fmt(raw_mean), "raw_median": _fmt(raw_median),
                "raw_std": _fmt(raw_std), "raw_mad": _fmt(raw_mad),
                "min": _fmt(vmin), "max": _fmt(vmax), "range": _fmt(vmax - vmin),
            }

            # Flag counts (0 for non-multi groups, which never carry flags).
            for meth in METHODS:
                row[f"n_flag_{meth}"] = sum(int(m[f"flag_{meth}"]) for m in members)

            if gm == "multi_method":
                for meth in METHODS:
                    avg, allflg = _survivor_mean(members, f"flag_{meth}")
                    row[f"clean_avg_{meth}"] = _fmt(avg)
                    row[f"{meth}_all_flagged"] = "1" if allflg else "0"
                    if allflg:
                        report["all_flagged"][(window, height, meth)] += 1
                cons_avg, cons_all = _consensus_mean(members)
                row["n_flag_consensus"] = sum(
                    1 for m in members if int(m["consensus_flags"]) >= 2
                )
                row["clean_avg_consensus"] = _fmt(cons_avg)
                row["consensus_all_flagged"] = "1" if cons_all else "0"
            else:
                # single_obs / mean_n2 : no detection; carry blanks + raw mean role.
                for meth in METHODS:
                    row[f"clean_avg_{meth}"] = ""
                    row[f"{meth}_all_flagged"] = ""
                row["n_flag_consensus"] = 0
                row["clean_avg_consensus"] = ""
                row["consensus_all_flagged"] = ""

            # Representative height flowing to the CO-OPS join.
            if gm == "single_obs":
                rep, src_lbl = raw_mean, "single_obs"      # mean of 1 == the value
            elif gm == "mean_n2":
                rep, src_lbl = raw_mean, "mean_n2"
            else:
                # For multi_method we expose all candidates; the production choice
                # (e.g. consensus or MAD) is settled in the deliverables stage.
                # Default representative = consensus cleaned avg, falling back to
                # raw mean only if consensus flagged everything (rare).
                if cons_avg is not None:
                    rep, src_lbl = cons_avg, "consensus_clean_avg"
                else:
                    rep, src_lbl = raw_mean, "raw_mean_fallback"

            row["representative_height"] = _fmt(rep)
            row["representative_source"] = src_lbl

            writer.writerow(row)
            report["rows"] += 1

    report["output"] = S04_SUMMARY_CSV
    return report


def main() -> None:
    report = run()
    print("=" * 70)
    print("STAGE 04  per-PID summary + cleaned averages  -- COMPLETE")
    print("=" * 70)
    print(f"  summary rows written : {report['rows']}")
    print("  (rows = PID x window x height-target)")
    if report["all_flagged"]:
        print("-" * 70)
        print("  ALL-FLAGGED groups (method flagged every obs; avg undefined):")
        for (win, ht, meth), c in sorted(report["all_flagged"].items()):
            print(f"    {win:8} {ht:9} {meth:6} : {c} groups")
    print("-" * 70)
    print(f"  output CSV : {report['output']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
