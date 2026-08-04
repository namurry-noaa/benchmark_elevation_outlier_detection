"""
s03_group_methods.py -- Stage 03 of the OPUS outlier-analysis pipeline.

This is the first stage with real statistics.

Purpose:
  For each (PID x window) group, and independently for each target height
  (ellipsoid, orthometric), classify every observation with four outlier
  methods, then emit a per-OBSERVATION audit table.

Per-group-size policy (project decision):
    n == 1 -> single_obs : the one value is kept; no flags computed.
    n == 2 -> mean_n2    : plain mean will be used downstream; no flags.
    n >= 3 -> full four-method comparison:
                * FIXED : |x - mean| > FIXED_TOLERANCE_M         (physical)
                * S1    : |x - mean| > 1*std                     (~68%, non-robust)
                * S2    : |x - mean| > 2*std                     (~95%, non-robust)
                * MAD   : modified z = |x - median|/(1.4826*MAD) > 3.5 (robust)

Cleaned average policy (method A, confirmed): each method's cleaned average is
the MEAN OF ITS SURVIVORS (non-flagged points). The plain median is carried
separately as a robust reference. Those cleaned averages are computed in
stage 04; here we only emit the per-observation flags + a consensus count so
the audit trail is complete and inspectable.

Output: s03_obs_flags.csv  -- one row per (obs x window x height_target).
Dependency-light: standard library only (statistics module), no pandas.

Run:  python pipeline/s03_group_methods.py
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

S02_WINDOWED_CSV = os.path.join(config.TABLES_DIR, "s02_opus_windowed.csv")
S03_OBS_FLAGS_CSV = os.path.join(config.TABLES_DIR, "s03_obs_flags.csv")

WINDOW_FLAG_COLS = {name: f"in_{name}" for name in config.WINDOWS}

# A stable within-group observation id lets stage 04 / figures line rows back up.
OUT_FIELDS = [
    "pid",
    "window",
    "height_target",     # 'ellip_ht' or 'ortho_ht'
    "obs_date",
    "obs_uid",           # source row order, for traceability
    "value",             # the height value under test
    "p2p",               # this obs's stated peak-to-peak accuracy
    "group_n",           # n in this PID x window group
    "group_method",      # single_obs | mean_n2 | multi_method
    "grp_mean",
    "grp_median",
    "grp_std",
    "grp_mad",
    "resid_from_mean",
    "resid_from_median",
    "mod_zscore",        # robust modified z-score (blank if undefined)
    "flag_fixed",
    "flag_s1",
    "flag_s2",
    "flag_mad",
    "consensus_flags",   # 0..4 : how many methods flagged this obs
]

# height_target -> (value_col, p2p_col)
HEIGHT_COLS = {
    "ellip_ht": ("ellip_ht", "ellip_ht_p2p"),
    "ortho_ht": ("ortho_ht", "ortho_ht_p2p"),
}


def _f(s):
    """Parse a CSV string cell to float or None."""
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _median_abs_dev(values, med):
    """Median absolute deviation about the (given) median."""
    return stats.median(abs(v - med) for v in values)


def _classify_group(members, value_key):
    """
    members: list of dicts, each with at least value_key -> float and 'obs_uid'.
    Returns (group_method, group_stats, per_member_result_by_uid).

    Each per-member result dict carries residuals, mod z, and 4 boolean flags.
    """
    vals = [m[value_key] for m in members]
    n = len(vals)

    # Group-level stats (defined only where meaningful).
    mean = stats.fmean(vals) if n >= 1 else None
    median = stats.median(vals) if n >= 1 else None
    std = stats.stdev(vals) if n >= 2 else None          # sample std, needs n>=2
    mad = _median_abs_dev(vals, median) if n >= 1 else None

    gstats = {"mean": mean, "median": median, "std": std, "mad": mad}

    results = {}

    if n < config.MIN_N_FOR_DETECTION:
        method = "single_obs" if n == 1 else "mean_n2"
        for m in members:
            v = m[value_key]
            results[m["obs_uid"]] = {
                "resid_from_mean": (v - mean) if mean is not None else None,
                "resid_from_median": (v - median) if median is not None else None,
                "mod_zscore": None,
                "flag_fixed": 0, "flag_s1": 0, "flag_s2": 0, "flag_mad": 0,
                "consensus": 0,
            }
        return method, gstats, results

    # n >= 3 : full four-method comparison.
    denom = config.MAD_SCALE * mad if (mad and mad > 0) else None
    for m in members:
        v = m[value_key]
        rmean = v - mean
        rmed = v - median

        flag_fixed = 1 if abs(rmean) > config.FIXED_TOLERANCE_M else 0
        flag_s1 = 1 if (std and abs(rmean) > config.SIGMA_1 * std) else 0
        flag_s2 = 1 if (std and abs(rmean) > config.SIGMA_2 * std) else 0

        if denom is not None:
            modz = rmed / denom
            flag_mad = 1 if abs(modz) > config.MAD_THRESHOLD else 0
        else:
            # MAD == 0 : >half the points are identical; no robust spread to test.
            modz = None
            flag_mad = 0

        results[m["obs_uid"]] = {
            "resid_from_mean": rmean,
            "resid_from_median": rmed,
            "mod_zscore": modz,
            "flag_fixed": flag_fixed,
            "flag_s1": flag_s1,
            "flag_s2": flag_s2,
            "flag_mad": flag_mad,
            "consensus": flag_fixed + flag_s1 + flag_s2 + flag_mad,
        }
    return "multi_method", gstats, results


def _fmt(x):
    return "" if x is None else repr(x)


def run():
    src = S02_WINDOWED_CSV
    if not os.path.exists(src):
        raise FileNotFoundError(
            f"Stage-02 output not found: {src}\nRun s02_window_filter.py first."
        )

    # Read all rows once, assigning a stable obs_uid = source order.
    rows = []
    with open(src, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, r in enumerate(reader):
            r["_uid"] = i
            rows.append(r)

    config.ensure_dirs()
    report = {
        "obs_records": 0,
        "groups": defaultdict(int),          # (window,height) -> group count
        "flagged": defaultdict(lambda: defaultdict(int)),  # (win,ht) -> method -> flagged obs
    }

    with open(S03_OBS_FLAGS_CSV, "w", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=OUT_FIELDS)
        writer.writeheader()

        for window in config.WINDOWS:
            flag_col = WINDOW_FLAG_COLS[window]
            for height_target, (val_col, p2p_col) in HEIGHT_COLS.items():
                # Build groups: pid -> list of members (only obs in this window
                # that have a usable value for this height target).
                groups = defaultdict(list)
                for r in rows:
                    if r.get(flag_col) != "1":
                        continue
                    v = _f(r.get(val_col))
                    if v is None:
                        continue
                    groups[r["pid"]].append({
                        "obs_uid": r["_uid"],
                        "pid": r["pid"],
                        "obs_date": r.get("obs_date", ""),
                        "value": v,
                        "p2p": _f(r.get(p2p_col)),
                    })

                for pid, members in groups.items():
                    report["groups"][(window, height_target)] += 1
                    method, gstats, results = _classify_group(members, "value")
                    n = len(members)
                    for m in members:
                        res = results[m["obs_uid"]]
                        for meth in ("fixed", "s1", "s2", "mad"):
                            if res[f"flag_{meth}"]:
                                report["flagged"][(window, height_target)][meth] += 1
                        writer.writerow({
                            "pid": pid,
                            "window": window,
                            "height_target": height_target,
                            "obs_date": m["obs_date"],
                            "obs_uid": m["obs_uid"],
                            "value": _fmt(m["value"]),
                            "p2p": _fmt(m["p2p"]),
                            "group_n": n,
                            "group_method": method,
                            "grp_mean": _fmt(gstats["mean"]),
                            "grp_median": _fmt(gstats["median"]),
                            "grp_std": _fmt(gstats["std"]),
                            "grp_mad": _fmt(gstats["mad"]),
                            "resid_from_mean": _fmt(res["resid_from_mean"]),
                            "resid_from_median": _fmt(res["resid_from_median"]),
                            "mod_zscore": _fmt(res["mod_zscore"]),
                            "flag_fixed": res["flag_fixed"],
                            "flag_s1": res["flag_s1"],
                            "flag_s2": res["flag_s2"],
                            "flag_mad": res["flag_mad"],
                            "consensus_flags": res["consensus"],
                        })
                        report["obs_records"] += 1

    report["output"] = S03_OBS_FLAGS_CSV
    return report


def main() -> None:
    report = run()
    print("=" * 70)
    print("STAGE 03  grouping + four-method flagging  -- COMPLETE")
    print("=" * 70)
    print(f"  observation-records written : {report['obs_records']}")
    print("  (records = obs x window-membership x height-target)")
    print("-" * 70)
    print(f"  {'window':8} {'height':9} {'groups':>7} "
          f"{'FIXED':>7} {'1sig':>7} {'2sig':>7} {'MAD':>7}")
    for window in config.WINDOWS:
        for height in HEIGHT_COLS:
            g = report["groups"][(window, height)]
            fl = report["flagged"][(window, height)]
            print(f"  {window:8} {height:9} {g:7d} "
                  f"{fl['fixed']:7d} {fl['s1']:7d} {fl['s2']:7d} {fl['mad']:7d}")
    print("-" * 70)
    print(f"  output CSV : {report['output']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
