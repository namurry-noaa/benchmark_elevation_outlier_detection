"""
s02_window_filter.py -- Stage 02 of the OPUS outlier-analysis pipeline.

Purpose (narrow and mechanical):
  * Read the stage-01 clean CSV.
  * Tag each observation with membership in each temporal window
    (W_NTDE, W_MOD, W_ALL) as boolean columns.
  * Write s02_opus_windowed.csv.

No grouping, no statistics. An observation may belong to multiple windows
(the windows are nested/overlapping by design). Every observation with a
valid date is retained; rows are never dropped here -- a row that falls in
no window (e.g. the lone pre-2002 point) is kept with all window flags False
so it is auditable rather than silently discarded.

Run:  python pipeline/s02_window_filter.py
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402

S02_WINDOWED_CSV = os.path.join(config.TABLES_DIR, "s02_opus_windowed.csv")

# Emitted column name per window, e.g. "in_W_NTDE".
WINDOW_FLAG_COLS = {name: f"in_{name}" for name in config.WINDOWS}


def _in_window(d: dt.date, start, end) -> bool:
    """Inclusive membership test; None bound means unbounded on that side."""
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True


def run():
    """Read stage-01, tag windows, write stage-02. Returns a report dict."""
    src = config.S01_CLEAN_CSV
    if not os.path.exists(src):
        raise FileNotFoundError(
            f"Stage-01 output not found: {src}\nRun s01_load_normalize.py first."
        )

    report = {
        "n_rows": 0,
        "no_window": 0,
        "per_window_obs": {name: 0 for name in config.WINDOWS},
    }

    config.ensure_dirs()
    with open(src, newline="", encoding="utf-8") as fin, \
         open(S02_WINDOWED_CSV, "w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        out_fields = list(reader.fieldnames) + list(WINDOW_FLAG_COLS.values())
        writer = csv.DictWriter(fout, fieldnames=out_fields)
        writer.writeheader()

        for row in reader:
            report["n_rows"] += 1
            date_str = row.get("obs_date", "")
            d = dt.date.fromisoformat(date_str) if date_str else None

            any_window = False
            for name, spec in config.WINDOWS.items():
                flag = bool(d) and _in_window(d, spec["start"], spec["end"])
                row[WINDOW_FLAG_COLS[name]] = "1" if flag else "0"
                if flag:
                    report["per_window_obs"][name] += 1
                    any_window = True
            if not any_window:
                report["no_window"] += 1

            writer.writerow(row)

    report["output"] = S02_WINDOWED_CSV
    return report


def main() -> None:
    report = run()
    print("=" * 70)
    print("STAGE 02  window tagging  -- COMPLETE")
    print("=" * 70)
    print(f"  input rows        : {report['n_rows']}")
    for name, spec in config.WINDOWS.items():
        print(f"  {name:8} ({spec['label']:24}) : "
              f"{report['per_window_obs'][name]} obs")
    print(f"  in NO window      : {report['no_window']}  (kept, all flags 0)")
    print(f"  output CSV        : {report['output']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
