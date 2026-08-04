"""
run_all.py -- Orchestrator for the OPUS outlier-analysis pipeline.

Runs the stages in dependency order. Stages are grouped by their runtime needs
so the pipeline degrades gracefully in a bare (stdlib + openpyxl) environment:

  CORE stages (stdlib + openpyxl) -- always run:
      s01 load/normalize -> s02 window -> s03 flags -> s04 per-PID summary
      -> s06 joins -> s05 injection

  VISUAL/GIS stages -- run only if their optional deps are present:
      s07 figures      (needs matplotlib, numpy)
      s08 gis export    STEP 1 always (stdlib); STEP 2 GeoPackage needs geopandas

Usage:
    python run_all.py                 # run everything available
    python run_all.py --core          # core analysis stages only
    python run_all.py --from s04      # resume from a given stage
    python run_all.py --only s06      # run a single stage

Each stage is imported and its main() invoked in-process, so a failure reports
the offending stage clearly and stops (fail-fast), leaving prior CSVs intact.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE_DIR = os.path.join(_THIS_DIR, "pipeline")
for p in (_THIS_DIR, _PIPELINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# Ordered pipeline definition. 'optional' stages are skipped (not failed) when
# their dependencies are missing.
STAGES = [
    ("s01", "s01_load_normalize", False),
    ("s02", "s02_window_filter", False),
    ("s03", "s03_group_methods", False),
    ("s04", "s04_per_pid_summary", False),
    ("s06", "s06_deliverables", False),
    ("s05", "s05_injection_experiment", False),
    ("s07", "s07_figures", True),
    ("s08", "s08_gis_export", False),  # STEP 1 always works; STEP 2 self-skips
]
STAGE_IDS = [s[0] for s in STAGES]


def _run_stage(stage_id, module_name, optional):
    print(f"\n>>> [{stage_id}] {module_name}")
    t0 = time.time()
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        if optional:
            print(f"    SKIPPED (optional deps missing): {exc}")
            return "skipped"
        raise
    try:
        mod.main()
    except SystemExit as exc:
        # s07 exits(2) when matplotlib is absent; treat as skip if optional.
        if optional and exc.code not in (0, None):
            print(f"    SKIPPED (stage exited {exc.code}; optional).")
            return "skipped"
        raise
    print(f"    done in {time.time() - t0:0.1f}s")
    return "ok"


def parse_args():
    ap = argparse.ArgumentParser(description="Run the OPUS outlier pipeline.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--core", action="store_true",
                   help="run only the core analysis stages (no figures/GIS).")
    g.add_argument("--from", dest="from_stage", metavar="STAGE",
                   choices=STAGE_IDS, help="resume from this stage onward.")
    g.add_argument("--only", dest="only_stage", metavar="STAGE",
                   choices=STAGE_IDS, help="run just this one stage.")
    return ap.parse_args()


def select_stages(args):
    if args.only_stage:
        return [s for s in STAGES if s[0] == args.only_stage]
    stages = STAGES
    if args.core:
        core_ids = {"s01", "s02", "s03", "s04", "s06", "s05"}
        stages = [s for s in stages if s[0] in core_ids]
    if args.from_stage:
        start = STAGE_IDS.index(args.from_stage)
        keep_ids = set(STAGE_IDS[start:])
        stages = [s for s in stages if s[0] in keep_ids]
    return stages


def main():
    args = parse_args()
    stages = select_stages(args)

    print("=" * 70)
    print("OPUS OUTLIER PIPELINE  run_all")
    print(f"  stages: {', '.join(s[0] for s in stages)}")
    print("=" * 70)

    results = {}
    t0 = time.time()
    for stage_id, module_name, optional in stages:
        results[stage_id] = _run_stage(stage_id, module_name, optional)

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    for stage_id, module_name, _ in stages:
        print(f"  {stage_id:5} {results.get(stage_id, '-'):8} {module_name}")
    print(f"  total time: {time.time() - t0:0.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
