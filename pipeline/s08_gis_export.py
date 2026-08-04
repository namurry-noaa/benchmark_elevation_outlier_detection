"""
s08_gis_export.py -- Stage 08 of the OPUS outlier-analysis pipeline.

Esri-agnostic GIS export. Two decoupled steps:

  STEP 1 (stdlib only): build a per-PID points CSV for one window, joining the
          stage-04 per-PID summary (all candidate cleaned averages + method
          disagreement metrics) with OPUS lat/lon. Runs in ANY environment.

  STEP 2 (needs geopandas): read that CSV and write a GeoPackage layer with
          point geometry (NAD83). If geopandas is unavailable, STEP 1 still
          succeeds and STEP 2 is skipped with a clear message -- so the CSV is
          always produced and can be dragged into ArcGIS Pro directly
          (Add XY Data) even without geopandas.

A separate, optional publish-to-AGOL script (GIS("pro")) is intentionally NOT
here: credentialed publishing stays isolated and is run by the user.

Attributes carried per PID (window-specific):
  * n, group_method
  * raw_mean, raw_std, range               (ellipsoid)
  * clean_avg_{fixed,s1,s2,mad,consensus}  (ellipsoid)
  * method_spread = max-min across the finite candidate averages (m)
        -> a single "how much do the methods disagree here" number, ideal
           for symbolizing the map.
  * fixed_all_flagged                      (legacy-rule failure marker)

Run:  python pipeline/s08_gis_export.py
"""

from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402

CAND_COLS = ("clean_avg_fixed", "clean_avg_s1", "clean_avg_s2",
             "clean_avg_mad", "clean_avg_consensus")


def _f(s):
    if s is None or str(s).strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(x):
    return "" if x is None else repr(x)


def load_pid_latlon():
    """
    Return pid -> (lat, lon) using the most recent OPUS obs for each PID
    (a stable representative location). Reads stage-01 clean CSV.
    """
    best = {}  # pid -> (date_str, lat, lon)
    with open(config.S01_CLEAN_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r["pid"]
            d = r.get("obs_date", "")
            lat = _f(r.get("lat_dd"))
            lon = _f(r.get("lon_dd"))
            if lat is None or lon is None:
                continue
            if pid not in best or d > best[pid][0]:
                best[pid] = (d, lat, lon)
    return {pid: (lat, lon) for pid, (d, lat, lon) in best.items()}


def build_points_csv():
    """STEP 1: write the per-PID points CSV for the configured window/height."""
    win = config.GIS_WINDOW
    ht = config.GIS_HEIGHT
    latlon = load_pid_latlon()

    out_fields = ["pid", "lat_dd", "lon_dd", "window", "height_target",
                  "n", "group_method",
                  "raw_mean", "raw_std", "range",
                  "clean_avg_fixed", "clean_avg_s1", "clean_avg_s2",
                  "clean_avg_mad", "clean_avg_consensus",
                  "representative_height", "representative_source",
                  "method_spread_m", "fixed_all_flagged"]

    n_written = 0
    n_no_geom = 0
    config.ensure_dirs()
    with open(config.S04_SUMMARY_CSV, newline="", encoding="utf-8") as fin, \
         open(config.S08_POINTS_CSV, "w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=out_fields)
        writer.writeheader()
        for r in reader:
            if r["window"] != win or r["height_target"] != ht:
                continue
            pid = r["pid"]
            if pid not in latlon:
                n_no_geom += 1
                continue
            lat, lon = latlon[pid]

            cands = [_f(r.get(c)) for c in CAND_COLS]
            finite = [c for c in cands if c is not None]
            spread = (max(finite) - min(finite)) if len(finite) >= 2 else None

            writer.writerow({
                "pid": pid, "lat_dd": _fmt(lat), "lon_dd": _fmt(lon),
                "window": win, "height_target": ht,
                "n": r["n"], "group_method": r["group_method"],
                "raw_mean": r["raw_mean"], "raw_std": r["raw_std"], "range": r["range"],
                "clean_avg_fixed": r["clean_avg_fixed"],
                "clean_avg_s1": r["clean_avg_s1"],
                "clean_avg_s2": r["clean_avg_s2"],
                "clean_avg_mad": r["clean_avg_mad"],
                "clean_avg_consensus": r["clean_avg_consensus"],
                "representative_height": r["representative_height"],
                "representative_source": r["representative_source"],
                "method_spread_m": _fmt(spread),
                "fixed_all_flagged": r.get("fixed_all_flagged", ""),
            })
            n_written += 1
    return n_written, n_no_geom


def build_geopackage():
    """STEP 2: write GeoPackage from the points CSV. Needs geopandas."""
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError as exc:
        print("  [STEP 2 skipped] geopandas/shapely not available "
              f"({exc.__class__.__name__}).")
        print("  The points CSV is complete and can be added to ArcGIS Pro via")
        print("  'Add XY Data' (X=lon_dd, Y=lat_dd, NAD83). Install geopandas")
        print("  (conda-forge) to also emit the GeoPackage.")
        return False

    rows = []
    with open(config.S08_POINTS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if not rows:
        print("  [STEP 2] points CSV empty; nothing to write.")
        return False

    lons = [float(r["lon_dd"]) for r in rows]
    lats = [float(r["lat_dd"]) for r in rows]
    geom = [Point(x, y) for x, y in zip(lons, lats)]

    # Coerce numeric attribute columns to float where possible.
    num_cols = ["n", "raw_mean", "raw_std", "range",
                "clean_avg_fixed", "clean_avg_s1", "clean_avg_s2",
                "clean_avg_mad", "clean_avg_consensus",
                "representative_height", "method_spread_m"]
    for r in rows:
        for c in num_cols:
            r[c] = _f(r.get(c))

    gdf = gpd.GeoDataFrame(rows, geometry=geom, crs=f"EPSG:{config.GIS_CRS_EPSG}")
    gdf.to_file(config.S08_GEOPACKAGE, layer=config.S08_GPKG_LAYER, driver="GPKG")
    print(f"  wrote GeoPackage: {config.S08_GEOPACKAGE}")
    print(f"    layer: {config.S08_GPKG_LAYER}  features: {len(gdf)}  "
          f"CRS: EPSG:{config.GIS_CRS_EPSG}")
    return True


def main() -> None:
    print("=" * 70)
    print("STAGE 08  GIS export (Esri-agnostic)  -- running")
    print("=" * 70)
    n, n_no_geom = build_points_csv()
    print(f"  STEP 1  points CSV written : {n} PIDs "
          f"(window={config.GIS_WINDOW}, height={config.GIS_HEIGHT})")
    if n_no_geom:
        print(f"          PIDs skipped (no lat/lon) : {n_no_geom}")
    print(f"          {config.S08_POINTS_CSV}")
    print("-" * 70)
    build_geopackage()
    print("=" * 70)


if __name__ == "__main__":
    main()
