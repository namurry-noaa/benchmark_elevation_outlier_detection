"""
s06_deliverables.py -- Stage 06 of the OPUS outlier-analysis pipeline.

Builds the join / comparison deliverables from stage-01 and stage-04 outputs
plus the CO-OPS tidal-datum workbook.

Join policy (confirmed):
  * key    : PID (normalized upper/trim on both sides)
  * type   : INNER  -- only PIDs present in BOTH OPUS and CO-OPS
  * grain  : PID x station -- a PID tied to N CO-OPS stations yields N rows;
             the geodetic height is repeated, each row carries that station's
             tidal datums.

Deliverables produced:
  A  s06_deliverableA_join_mostrecent.csv
       CO-OPS  x  most-recent OPUS observation per (PID, window).
  B  s06_deliverableB_join_avg.csv
       CO-OPS  x  outlier-detected representative height per (PID, window),
       carrying ALL candidate cleaned averages so the comparison travels with
       the datum tie.
  C  s06_deliverableC_method_compare.csv
       per (PID, window, height) method-comparison roll-up:
       raw vs each cleaned average, the shift each method induces, and
       method-agreement summary. This is the core "which fits best" table.
  +  s06_join_coverage.csv
       PID coverage: in both / OPUS-only / CO-OPS-only counts.

Dependency-light: standard library + openpyxl.

Run:  python pipeline/s06_deliverables.py
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import statistics as stats
import sys
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402
import openpyxl  # noqa: E402


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_coops():
    """Return (rows_by_pid, all_pids_set). rows_by_pid: pid -> list of station dicts."""
    path = os.path.abspath(config.COOPS_XLSX)
    if not os.path.exists(path):
        raise FileNotFoundError(f"CO-OPS workbook not found: {path}")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    header = list(next(it))
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in config.COOPS_KEEP_COLS if c not in idx]
    if missing:
        wb.close()
        raise KeyError(f"CO-OPS header missing columns: {missing}")

    by_pid = defaultdict(list)
    pids = set()
    for r in it:
        pid = r[idx[config.COOPS_COL_PID]]
        pid = "" if pid is None else str(pid).strip().upper()
        if not pid:
            continue
        rec = {}
        for src, clean in config.COOPS_KEEP_COLS.items():
            v = r[idx[src]]
            rec[clean] = "" if v is None else (
                v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else str(v).strip()
            )
        by_pid[pid].append(rec)
        pids.add(pid)
    wb.close()
    return by_pid, pids


def load_s04():
    """Return dict keyed (pid,window,height) -> summary row dict, + set of pids."""
    path = config.S04_SUMMARY_CSV
    if not os.path.exists(path):
        raise FileNotFoundError(f"Stage-04 output not found: {path}")
    summ = {}
    pids = set()
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            summ[(r["pid"], r["window"], r["height_target"])] = r
            pids.add(r["pid"])
    return summ, pids


def load_s01_rows():
    """Return list of clean OPUS obs rows (for most-recent selection)."""
    path = config.S01_CLEAN_FOR_JOIN
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _f(s):
    if s is None or str(s).strip() == "":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _fmt(x):
    return "" if x is None else repr(x)


COOPS_OUT_COLS = list(config.COOPS_KEEP_COLS.values())
WINDOWS = list(config.WINDOWS.keys())
METHODS = ("fixed", "s1", "s2", "mad")
METHOD_LABEL = {"fixed": "4cm", "s1": "1sigma", "s2": "2sigma", "mad": "MAD"}


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------
def write_coverage(opus_pids, coops_pids):
    both = opus_pids & coops_pids
    opus_only = opus_pids - coops_pids
    coops_only = coops_pids - opus_pids
    with open(config.S06_COVERAGE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "n_pids"])
        w.writerow(["in_both_opus_and_coops", len(both)])
        w.writerow(["opus_only", len(opus_only)])
        w.writerow(["coops_only", len(coops_only)])
        w.writerow(["opus_total", len(opus_pids)])
        w.writerow(["coops_total", len(coops_pids)])
    return {"both": len(both), "opus_only": len(opus_only),
            "coops_only": len(coops_only)}


# ---------------------------------------------------------------------------
# Deliverable A : CO-OPS x most-recent OPUS obs per (PID, window)
# ---------------------------------------------------------------------------
def build_deliverable_A(s01_rows, coops_by_pid):
    # most-recent obs per (pid, window) using window flags on the s02 file.
    # We re-derive window membership here from obs_date to avoid a hard s02 dep.
    def in_window(d, spec):
        if spec["start"] and d < spec["start"]:
            return False
        if spec["end"] and d > spec["end"]:
            return False
        return True

    best = {}  # (pid, window) -> row with max date
    for r in s01_rows:
        ds = r.get("obs_date", "")
        if not ds:
            continue
        d = dt.date.fromisoformat(ds)
        pid = r["pid"]
        for win, spec in config.WINDOWS.items():
            if in_window(d, spec):
                key = (pid, win)
                if key not in best or d > dt.date.fromisoformat(best[key]["obs_date"]):
                    best[key] = r

    out_fields = (["pid", "window", "obs_date", "ellip_ht", "ortho_ht",
                   "ellip_ht_p2p", "ortho_ht_p2p", "lat_dd", "lon_dd",
                   "observing_agency"] + COOPS_OUT_COLS)
    n = 0
    with open(config.S06_JOIN_RECENT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for (pid, win), r in best.items():
            if pid not in coops_by_pid:   # INNER join
                continue
            for st in coops_by_pid[pid]:
                row = {
                    "pid": pid, "window": win, "obs_date": r["obs_date"],
                    "ellip_ht": r["ellip_ht"], "ortho_ht": r["ortho_ht"],
                    "ellip_ht_p2p": r["ellip_ht_p2p"], "ortho_ht_p2p": r["ortho_ht_p2p"],
                    "lat_dd": r["lat_dd"], "lon_dd": r["lon_dd"],
                    "observing_agency": r["observing_agency"],
                }
                row.update(st)
                w.writerow(row)
                n += 1
    return n


# ---------------------------------------------------------------------------
# Deliverable B : CO-OPS x representative (outlier-detected) height per PID/window
# ---------------------------------------------------------------------------
def build_deliverable_B(s04, coops_by_pid):
    # Pivot s04 so ellip + ortho for a (pid,window) sit on one row.
    keyset = {(pid, win) for (pid, win, ht) in s04}
    out_fields = (["pid", "window", "n_ellip", "n_ortho", "group_method",
                   "rep_ellip_ht", "rep_ellip_source",
                   "rep_ortho_ht", "rep_ortho_source",
                   # candidate cleaned averages (ellip)
                   "ellip_clean_fixed", "ellip_clean_s1", "ellip_clean_s2",
                   "ellip_clean_mad", "ellip_clean_consensus",
                   # candidate cleaned averages (ortho)
                   "ortho_clean_fixed", "ortho_clean_s1", "ortho_clean_s2",
                   "ortho_clean_mad", "ortho_clean_consensus"]
                  + COOPS_OUT_COLS)
    n = 0
    with open(config.S06_JOIN_AVG_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for (pid, win) in sorted(keyset):
            if pid not in coops_by_pid:   # INNER join
                continue
            e = s04.get((pid, win, "ellip_ht"))
            o = s04.get((pid, win, "ortho_ht"))
            if e is None and o is None:
                continue
            base = {
                "pid": pid, "window": win,
                "n_ellip": e["n"] if e else "",
                "n_ortho": o["n"] if o else "",
                "group_method": (e or o)["group_method"],
                "rep_ellip_ht": e["representative_height"] if e else "",
                "rep_ellip_source": e["representative_source"] if e else "",
                "rep_ortho_ht": o["representative_height"] if o else "",
                "rep_ortho_source": o["representative_source"] if o else "",
                "ellip_clean_fixed": e["clean_avg_fixed"] if e else "",
                "ellip_clean_s1": e["clean_avg_s1"] if e else "",
                "ellip_clean_s2": e["clean_avg_s2"] if e else "",
                "ellip_clean_mad": e["clean_avg_mad"] if e else "",
                "ellip_clean_consensus": e["clean_avg_consensus"] if e else "",
                "ortho_clean_fixed": o["clean_avg_fixed"] if o else "",
                "ortho_clean_s1": o["clean_avg_s1"] if o else "",
                "ortho_clean_s2": o["clean_avg_s2"] if o else "",
                "ortho_clean_mad": o["clean_avg_mad"] if o else "",
                "ortho_clean_consensus": o["clean_avg_consensus"] if o else "",
            }
            for st in coops_by_pid[pid]:
                row = dict(base)
                row.update(st)
                w.writerow(row)
                n += 1
    return n


# ---------------------------------------------------------------------------
# Deliverable C : method-comparison roll-up (PID x window x height)
# ---------------------------------------------------------------------------
def build_deliverable_C(s04):
    out_fields = ["pid", "window", "height_target", "n", "group_method",
                  "raw_mean", "raw_std", "range",
                  "n_flag_fixed", "n_flag_s1", "n_flag_s2", "n_flag_mad",
                  "clean_avg_fixed", "clean_avg_s1", "clean_avg_s2",
                  "clean_avg_mad", "clean_avg_consensus",
                  # shift of each method's cleaned avg from the raw mean (meters)
                  "shift_fixed", "shift_s1", "shift_s2", "shift_mad",
                  "shift_consensus",
                  "fixed_all_flagged"]
    n = 0
    with open(config.S06_METHOD_COMPARE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for (pid, win, ht), r in s04.items():
            if r["group_method"] != "multi_method":
                continue  # comparison only meaningful for n>=3
            raw = _f(r["raw_mean"])
            row = {k: r.get(k, "") for k in
                   ["pid", "window", "height_target", "n", "group_method",
                    "raw_mean", "raw_std", "range",
                    "n_flag_fixed", "n_flag_s1", "n_flag_s2", "n_flag_mad",
                    "clean_avg_fixed", "clean_avg_s1", "clean_avg_s2",
                    "clean_avg_mad", "clean_avg_consensus", "fixed_all_flagged"]}
            for meth, col in (("fixed", "clean_avg_fixed"), ("s1", "clean_avg_s1"),
                              ("s2", "clean_avg_s2"), ("mad", "clean_avg_mad"),
                              ("consensus", "clean_avg_consensus")):
                cv = _f(r.get(col))
                row[f"shift_{meth}"] = _fmt(cv - raw) if (cv is not None and raw is not None) else ""
            w.writerow(row)
            n += 1
    return n


# ---------------------------------------------------------------------------
# Deliverable D : station-level (spatial / inter-mark) screen
# ---------------------------------------------------------------------------
def _station_mark_elevation(summ_row):
    """
    The single elevation a benchmark contributes to its station, formed by the
    TEMPORAL cleaning already done in s04:
      * n>=3 (multi_method)  -> the MAD-cleaned average (robust survivors' mean),
                                falling back to the raw median if MAD flagged all.
      * n<3                  -> the policy value (single value or mean of two).
    Returns float or None.
    """
    gm = summ_row["group_method"]
    if gm == "multi_method":
        v = _f(summ_row.get("clean_avg_mad"))
        return v if v is not None else _f(summ_row.get("raw_median"))
    return _f(summ_row.get("raw_mean"))  # single_obs / mean_n2


def _median_abs_dev(values, med):
    return stats.median(abs(v - med) for v in values)


def build_deliverable_D(s04, coops_by_pid):
    """
    For each CO-OPS station (grouping its benchmarks), compare what a SPATIAL
    4 cm tolerance about the cross-mark mean would discard versus a robust
    (median / MAD) spatial screen. Emits one row per (station, mark).

    This is the second, inter-mark level of the analysis: the temporal cleaning
    (s03/s04) produced one elevation per mark; here we ask which marks agree well
    enough to be combined into a single station geodetic value.
    """
    win = config.STATION_WINDOW
    ht = config.STATION_HEIGHT

    # station_id -> list of (pid, mark_elevation, summ_row)
    stations = defaultdict(list)
    station_name = {}
    seen = set()  # (station, pid) dedup (deliverable-B fan-out repeats marks)
    for (pid, w, h), r in s04.items():
        if w != win or h != ht:
            continue
        if pid not in coops_by_pid:
            continue
        elev = _station_mark_elevation(r)
        if elev is None:
            continue
        for st in coops_by_pid[pid]:
            sid = st.get("station_id", "")
            if not sid:
                continue
            station_name[sid] = st.get("station_name", "")
            key = (sid, pid)
            if key in seen:
                continue
            seen.add(key)
            stations[sid].append((pid, elev, r))

    out_fields = [
        "station_id", "station_name", "n_marks_at_station",
        "pid", "mark_n_obs", "mark_group_method", "mark_elevation_m",
        "station_mean_m", "station_median_m", "station_mad_m",
        "station_spread_cm",
        "dev_from_mean_cm", "spatial_z_robust",
        "spatial_4cm_flag", "spatial_robust_flag",
        "example_role",
    ]
    tol = config.SPATIAL_TOLERANCE_M
    examples = getattr(config, "STATION_EXAMPLES", {})

    n = 0
    with open(config.S06_STATION_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for sid, marks in sorted(stations.items()):
            if len(marks) < config.STATION_MIN_MARKS:
                continue
            vals = [e for (_p, e, _r) in marks]
            cmean = stats.fmean(vals)
            cmed = stats.median(vals)
            cmad = _median_abs_dev(vals, cmed)
            spread_cm = (max(vals) - min(vals)) * 100.0
            denom = config.MAD_SCALE * cmad if cmad > 0 else None
            role = examples.get(sid, {}).get("role", "")
            for (pid, e, r) in marks:
                dev = e - cmean
                z = (e - cmed) / denom if denom is not None else None
                w.writerow({
                    "station_id": sid,
                    "station_name": station_name.get(sid, ""),
                    "n_marks_at_station": len(marks),
                    "pid": pid,
                    "mark_n_obs": r["n"],
                    "mark_group_method": r["group_method"],
                    "mark_elevation_m": _fmt(e),
                    "station_mean_m": _fmt(cmean),
                    "station_median_m": _fmt(cmed),
                    "station_mad_m": _fmt(cmad),
                    "station_spread_cm": _fmt(round(spread_cm, 2)),
                    "dev_from_mean_cm": _fmt(round(dev * 100.0, 2)),
                    "spatial_z_robust": _fmt(round(z, 2)) if z is not None else "",
                    "spatial_4cm_flag": 1 if abs(dev) > tol else 0,
                    "spatial_robust_flag": (
                        1 if (z is not None and abs(z) > config.SPATIAL_MAD_THRESHOLD) else 0
                    ),
                    "example_role": role,
                })
                n += 1
    return n


def main() -> None:
    coops_by_pid, coops_pids = load_coops()
    s04, opus_pids = load_s04()
    s01_rows = load_s01_rows()

    cov = write_coverage(opus_pids, coops_pids)
    nA = build_deliverable_A(s01_rows, coops_by_pid)
    nB = build_deliverable_B(s04, coops_by_pid)
    nC = build_deliverable_C(s04)
    nD = build_deliverable_D(s04, coops_by_pid)

    print("=" * 70)
    print("STAGE 06  join deliverables  -- COMPLETE")
    print("=" * 70)
    print(f"  PID coverage : both={cov['both']}  "
          f"OPUS-only={cov['opus_only']}  CO-OPS-only={cov['coops_only']}")
    print(f"  Deliverable A (most-recent join)  rows : {nA}")
    print(f"  Deliverable B (avg/representative join) rows : {nB}")
    print(f"  Deliverable C (method comparison) rows : {nC}")
    print(f"  Deliverable D (station spatial screen) rows : {nD}")
    print("-" * 70)
    print(f"  {config.S06_COVERAGE_CSV}")
    print(f"  {config.S06_JOIN_RECENT_CSV}")
    print(f"  {config.S06_JOIN_AVG_CSV}")
    print(f"  {config.S06_METHOD_COMPARE_CSV}")
    print(f"  {config.S06_STATION_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    main()
