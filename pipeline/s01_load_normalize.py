"""
s01_load_normalize.py -- Stage 01 of the OPUS outlier-analysis pipeline.

Purpose (deliberately narrow):
  * Load the OPUS workbook.
  * Normalize the join key (PID -> uppercase, trimmed).
  * Parse the observation date to an ISO date.
  * Keep only the columns downstream stages need (+ lat/lon for later GIS).
  * Write a clean, human-readable CSV intermediate.

No statistics, no windowing, no grouping happen here. This stage must be
provably correct before anything else touches the data. It is dependency-light
on purpose: standard library + openpyxl only (no pandas), so it runs in any
environment including a bare ArcGIS conda env.

Run:  python pipeline/s01_load_normalize.py
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import sys

# Make the project root importable so `import config` works regardless of CWD.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402

import openpyxl  # noqa: E402


def _norm_pid(value) -> str:
    """Normalize a PID for use as a join key: string, stripped, uppercased."""
    if value is None:
        return ""
    return str(value).strip().upper()


def _parse_date(value):
    """
    Return a datetime.date, or None if unparseable/blank.
    OPUS dates were verified to be true datetimes, but we defend against
    strings and blanks so the stage never crashes on a dirty upstream dump.
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value):
    """Return float or None (blank/non-numeric become None rather than crash)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_and_normalize():
    """Read the OPUS workbook, return (clean_rows, report_dict)."""
    path = os.path.abspath(config.OPUS_XLSX)
    if not os.path.exists(path):
        raise FileNotFoundError(f"OPUS workbook not found: {path}")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    row_iter = ws.iter_rows(values_only=True)

    header = list(next(row_iter))
    src_index = {name: i for i, name in enumerate(header)}

    # Verify every source column we intend to keep actually exists.
    missing = [c for c in config.CLEAN_COLUMNS if c not in src_index]
    if missing:
        wb.close()
        raise KeyError(f"OPUS header is missing expected columns: {missing}")

    # These get type-coerced; everything else is passed through as string.
    float_srcs = {
        config.COL_ELLIP, config.COL_ELLIP_P2P,
        config.COL_ORTHO, config.COL_ORTHO_P2P,
        config.COL_LAT, config.COL_LON,
    }

    clean_rows = []
    report = {
        "source_path": path,
        "source_sheet": ws.title,
        "n_rows": 0,
        "blank_pid": 0,
        "unparseable_date": 0,
        "blank_ellip": 0,
        "blank_ortho": 0,
        "min_date": None,
        "max_date": None,
        "unique_pids": set(),
    }

    for raw in row_iter:
        report["n_rows"] += 1
        out = {}
        for src, clean_name in config.CLEAN_COLUMNS.items():
            val = raw[src_index[src]]
            if src == config.COL_PID:
                out[clean_name] = _norm_pid(val)
            elif src == config.COL_DATE:
                d = _parse_date(val)
                out[clean_name] = d.isoformat() if d else ""
                if d is None:
                    report["unparseable_date"] += 1
                else:
                    if report["min_date"] is None or d < report["min_date"]:
                        report["min_date"] = d
                    if report["max_date"] is None or d > report["max_date"]:
                        report["max_date"] = d
            elif src in float_srcs:
                f = _to_float(val)
                out[clean_name] = "" if f is None else repr(f)
            else:
                out[clean_name] = "" if val is None else str(val).strip()

        if not out["pid"]:
            report["blank_pid"] += 1
        else:
            report["unique_pids"].add(out["pid"])
        if out["ellip_ht"] == "":
            report["blank_ellip"] += 1
        if out["ortho_ht"] == "":
            report["blank_ortho"] += 1

        clean_rows.append(out)

    wb.close()
    return clean_rows, report


def write_csv(clean_rows) -> str:
    """Write clean rows to the stage-01 CSV. Returns the output path."""
    config.ensure_dirs()
    out_path = config.S01_CLEAN_CSV
    fieldnames = list(config.CLEAN_COLUMNS.values())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean_rows)
    return out_path


def main() -> None:
    clean_rows, report = load_and_normalize()
    out_path = write_csv(clean_rows)

    print("=" * 70)
    print("STAGE 01  load + normalize  -- COMPLETE")
    print("=" * 70)
    print(f"  source        : {report['source_path']}")
    print(f"  sheet         : {report['source_sheet']}")
    print(f"  data rows     : {report['n_rows']}")
    print(f"  unique PIDs   : {len(report['unique_pids'])}")
    print(f"  blank PID     : {report['blank_pid']}")
    print(f"  bad dates     : {report['unparseable_date']}")
    print(f"  blank ellip   : {report['blank_ellip']}")
    print(f"  blank ortho   : {report['blank_ortho']}")
    print(f"  date span     : {report['min_date']} -> {report['max_date']}")
    print(f"  output CSV    : {out_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
