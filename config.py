"""
config.py -- central configuration for the OPUS outlier-analysis pipeline.

Every tunable knob for the study lives here so reviewers can see and challenge
each parameter in one place. No analysis logic belongs in this file.
"""

from __future__ import annotations
import os
import datetime as _dt

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Project root = the OPUS_Outlier_Analysis directory (where this file lives).
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Source workbook (OPUS full dump). IDB and CO-OPS are intentionally NOT here;
# they enter only at the later join stage, per project scope.
# Data now lives in an in-repo `data/` dir (tracked separately by the user).
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OPUS_XLSX = os.path.join(DATA_DIR, "OPUS__3-10-26.xlsx")

# Output tree
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
TABLES_DIR = os.path.join(OUTPUT_DIR, "tables")
FIGURES_DIR = os.path.join(OUTPUT_DIR, "figures")
GIS_DIR = os.path.join(OUTPUT_DIR, "gis")

# Intermediate output of stage 01
S01_CLEAN_CSV = os.path.join(TABLES_DIR, "s01_opus_clean.csv")

# CO-OPS tidal-datum workbook (enters only at the join stage, s06).
COOPS_XLSX = os.path.join(DATA_DIR, "CO-OPS__3-12-26.xlsx")

# ---------------------------------------------------------------------------
# Source column names (exactly as they appear in the OPUS workbook header).
# Centralized so a header change upstream is a one-line fix here.
# ---------------------------------------------------------------------------
COL_PID = "PID"
COL_DATE = "Observed Date"
COL_ELLIP = "Ellipsoid Height"
COL_ELLIP_P2P = "Ellipsoid Height (P2P)"
COL_ORTHO = "Orthometric Height"
COL_ORTHO_P2P = "Orthometric Height (P2P)"
COL_REF_FRAME = "Reference Frame"
COL_EPOCH = "Epoch"
COL_LAT = "Latitude (DD)"
COL_LON = "Longitude (DD)"
COL_AGENCY = "Observing Agency"
COL_OPUS_OUTLIER = "Outlier flag"          # OPUS's own pre-existing flag (kept for comparison)
COL_SHARE_LINK = "OPUS Share Link"         # audit trail back to the source datasheet
COL_DESIG = "Designation"
COL_COOP_BM_ID = "COOP Benchmark ID"
COL_TIDAL_STATION = "Tidal Station ID"

# The tidy column names we emit (source -> clean). Order here defines CSV order.
CLEAN_COLUMNS = {
    COL_PID: "pid",
    COL_DATE: "obs_date",
    COL_DESIG: "designation",
    COL_COOP_BM_ID: "coop_bm_id",
    COL_TIDAL_STATION: "tidal_station_id",
    COL_ELLIP: "ellip_ht",
    COL_ELLIP_P2P: "ellip_ht_p2p",
    COL_ORTHO: "ortho_ht",
    COL_ORTHO_P2P: "ortho_ht_p2p",
    COL_REF_FRAME: "ref_frame",
    COL_EPOCH: "epoch",
    COL_LAT: "lat_dd",
    COL_LON: "lon_dd",
    COL_AGENCY: "observing_agency",
    COL_OPUS_OUTLIER: "opus_outlier_flag",
    COL_SHARE_LINK: "opus_share_link",
}

# ---------------------------------------------------------------------------
# Temporal windows (nested / overlapping, by design).
#   W_NTDE  subset of  W_MOD  subset of  W_ALL
# start is inclusive; end is inclusive. None end = "to latest observation present".
# ---------------------------------------------------------------------------
WINDOWS = {
    "W_NTDE": {
        "label": "Current NTDE (2002-2020)",
        "start": _dt.date(2002, 1, 1),
        "end": _dt.date(2020, 12, 31),
    },
    "W_MOD": {
        "label": "Modern (2002-present)",
        "start": _dt.date(2002, 1, 1),
        "end": None,  # open-ended: include newest observations
    },
    "W_ALL": {
        "label": "All observations",
        "start": None,  # open-ended: include earliest observations
        "end": None,
    },
}

# ---------------------------------------------------------------------------
# Outlier-detection method parameters.
# ---------------------------------------------------------------------------
# Fixed physical tolerance (meters) about the group center.
FIXED_TOLERANCE_M = 0.04

# Sigma multipliers (classic, mean/std based, NON-robust).
SIGMA_1 = 1.0   # ~68% band
SIGMA_2 = 2.0   # ~95% band

# Modified z-score (robust, median/MAD based). Iglewicz & Hoaglin recommend 3.5.
MAD_THRESHOLD = 3.5
MAD_SCALE = 1.4826  # makes MAD a consistent estimator of sigma for normal data

# Group-size policy (per project decision):
#   n == 1  -> keep the single value as-is (method = 'single_obs'); no flagging
#   n == 2  -> plain mean (method = 'mean_n2'); no flagging (sigma/MAD undefined)
#   n >= 3  -> full four-method comparison
MIN_N_FOR_DETECTION = 3

# Heights to analyze independently (both, per project decision).
HEIGHT_TARGETS = ("ellip_ht", "ortho_ht")

# ---------------------------------------------------------------------------
# Synthetic-outlier injection experiment (stage 05).
#   Goal: an OBJECTIVE grading proxy. Take real, "clean-enough" groups, plant a
#   single outlier of known magnitude into one observation, then measure whether
#   each method (a) detects the planted point [true positive] and (b) leaves the
#   untouched points alone [false positives].
#
#   "Clean-enough" donor groups: real n>=3 groups whose native robust spread is
#   small, so a planted offset is unambiguously the outlier. This avoids grading
#   a method against data that was already dirty.
# ---------------------------------------------------------------------------
# Only use donor groups whose native MAD (meters) is at/below this -- i.e. the
# real observations already agree well, so injected offsets are clearly "bad".
INJ_MAX_DONOR_MAD_M = 0.02
# Require at least this many observations in a donor group.
INJ_MIN_DONOR_N = 4
# Offsets to inject (meters), spanning below-tolerance to gross blunder.
INJ_OFFSETS_M = (0.02, 0.04, 0.06, 0.10, 0.20, 0.50)
# Monte Carlo trials per (donor group x offset): pick a random obs, add offset,
# re-run all four methods. Averaged over trials -> detection/false-alarm rates.
INJ_TRIALS_PER_CASE = 20
# Deterministic seed for reproducibility (reviewers can re-run identically).
INJ_SEED = 20260728
# Which height target to run the experiment on (methodology is height-agnostic;
# ellipsoid is the honest observable, per earlier decision).
INJ_HEIGHT_TARGET = "ellip_ht"
# Window whose groups feed the experiment (W_MOD has the most n>=4 donors).
INJ_WINDOW = "W_MOD"

S05_INJECTION_CSV = os.path.join(TABLES_DIR, "s05_injection_results.csv")
S05_INJECTION_SUMMARY_CSV = os.path.join(TABLES_DIR, "s05_injection_summary.csv")

# ---------------------------------------------------------------------------
# Figure settings (stage 07).
# ---------------------------------------------------------------------------
FIG_DPI = 150
FIG_WINDOW = "W_MOD"          # window used for shift/flag-rate figures
FIG_HEIGHT = "ellip_ht"       # height target used for single-height figures
FIG_METHOD_ORDER = ("fixed", "s1", "s2", "mad", "consensus")
FIG_METHOD_LABELS = {
    "fixed": "4 cm fixed",
    "s1": "1-sigma",
    "s2": "2-sigma",
    "mad": "MAD (robust)",
    "consensus": "consensus (>=2)",
}

# ---------------------------------------------------------------------------
# CO-OPS join settings (stage 06).
#   Join: OPUS <-> CO-OPS on PID.
#   Type: INNER (only PIDs present in both tables), per project decision.
#   Grain: PID x station -- a PID tied to N stations yields N rows, the
#          geodetic height repeated, each row carrying that station's datums.
# ---------------------------------------------------------------------------
COOPS_COL_PID = "pid"
COOPS_KEEP_COLS = {
    "pid": "pid",
    "station_id": "station_id",
    "station_name": "station_name",
    "epoch": "coops_epoch",
    "datum_accepted_date_time": "datum_accepted_date",
    "navd88_ortho_on_sd_m": "navd88_ortho_on_sd_m",
    "lmsl_on_sd_m": "lmsl_on_sd_m",
    "mllw_on_sd_m": "mllw_on_sd_m",
    "mhw_on_sd_m": "mhw_on_sd_m",
    "mhhw_on_sd_m": "mhhw_on_sd_m",
    "mlw_on_sd_m": "mlw_on_sd_m",
    "bm_on_mllw_m": "bm_on_mllw_m",
    "bm_on_msl_m": "bm_on_msl_m",
}
COOPS_JOIN_TYPE = "inner"  # inner | left

# Which per-PID representative height / candidate averages feed the join tables.
# The join carries ALL candidate cleaned averages so the comparison travels
# with the datum tie; representative_height is the production default.
S04_SUMMARY_CSV = os.path.join(TABLES_DIR, "s04_per_pid_summary.csv")
S01_CLEAN_FOR_JOIN = S01_CLEAN_CSV

# Stage-06 outputs
S06_JOIN_AVG_CSV = os.path.join(TABLES_DIR, "s06_deliverableB_join_avg.csv")
S06_JOIN_RECENT_CSV = os.path.join(TABLES_DIR, "s06_deliverableA_join_mostrecent.csv")
S06_METHOD_COMPARE_CSV = os.path.join(TABLES_DIR, "s06_deliverableC_method_compare.csv")
S06_COVERAGE_CSV = os.path.join(TABLES_DIR, "s06_join_coverage.csv")
S06_STATION_CSV = os.path.join(TABLES_DIR, "s06_deliverableD_station_spatial.csv")

# ---------------------------------------------------------------------------
# Station-level (spatial / inter-mark) analysis  -- Deliverable D (stage 06).
#   The temporal work (s03/s04) cleans EACH benchmark's repeat observations over
#   time. A tide station, however, has MULTIPLE benchmarks; a single geodetic
#   value for the station is formed by combining those per-mark elevations. This
#   is a SECOND, SPATIAL question: which marks agree well enough to be combined?
#
#   Legacy CO-OPS practice applies the same 4 cm tolerance ACROSS marks (about
#   the cross-mark mean). This deliverable measures, per station, what that
#   spatial 4 cm gate would discard versus a robust (median/MAD) spatial screen.
#
#   Per-mark elevation used as the station input = the mark's temporally
#   MAD-cleaned average when n>=3, else its policy value (single/mean) for n<3.
# ---------------------------------------------------------------------------
SPATIAL_TOLERANCE_M = 0.04         # 4 cm across marks (mirrors legacy practice)
SPATIAL_MAD_THRESHOLD = 3.5        # robust spatial screen (mirrors MAD_THRESHOLD)
STATION_WINDOW = "W_MOD"
STATION_HEIGHT = "ellip_ht"
STATION_MIN_MARKS = 3
# Three worked-example stations spanning the spectrum (used in docs + fig7/fig8):
#   works : tight station; 4 cm spatial gate is harmless.
#   both  : one genuinely offset mark; temporal + spatial both act cleanly.
#   fails : wide but real cross-mark scatter; 4 cm spatial gate discards most of
#           the (good) marks while the robust screen keeps them.
STATION_EXAMPLES = {
    "8741041": {"role": "works", "label": "Dock E, Port of Pascagoula"},
    "8729882": {"role": "both",  "label": "Fort Pickens, Pensacola Bay"},
    "8638610": {"role": "fails", "label": "Sewells Point, Hampton Roads"},
}

# ---------------------------------------------------------------------------
# Station-level (spatial / inter-mark) analysis  -- Deliverable D (stage 06).
#   The temporal work (s03/s04) cleans EACH benchmark's repeat observations over
#   time. A tide station, however, has MULTIPLE benchmarks; a single geodetic
#   value for the station is formed by combining those per-mark elevations. This
#   is a SECOND, SPATIAL question: which marks agree well enough to be combined?
#
#   Legacy CO-OPS practice applies the same 4 cm tolerance ACROSS marks (about
#   the cross-mark mean). This deliverable measures, per station, what that
#   spatial 4 cm gate would discard versus a robust (median/MAD) spatial screen,
#   so the two can be compared on real stations.
#
#   Per-mark elevation used as the station input = the mark's temporally
#   MAD-cleaned average when n>=3, else its policy value (single/mean) for n<3.
# ---------------------------------------------------------------------------
# Spatial tolerance applied across marks at a station (meters). Same 4 cm value
# the legacy rule uses temporally -- reused here to mirror current practice.
SPATIAL_TOLERANCE_M = 0.04
# Robust spatial screen threshold (modified z across marks); mirrors MAD_THRESHOLD.
SPATIAL_MAD_THRESHOLD = 3.5
# Window / height the station-level analysis runs on (matches figure defaults).
STATION_WINDOW = "W_MOD"
STATION_HEIGHT = "ellip_ht"
# Minimum benchmarks at a station to attempt a spatial comparison.
STATION_MIN_MARKS = 3
S06_STATION_CSV = os.path.join(TABLES_DIR, "s06_deliverableD_station_spatial.csv")

# The three worked-example stations used in the docs and figures (fig7/fig8).
# Chosen to span the spectrum:
#   works     : tight station; 4 cm spatial gate is harmless (all marks agree).
#   both      : one genuinely offset mark; temporal + spatial both act cleanly.
#   fails     : wide but real cross-mark scatter; the 4 cm spatial gate discards
#               most of the (good) marks, while the robust screen keeps them.
STATION_EXAMPLES = {
    "8741041": {"role": "works", "label": "Dock E, Port of Pascagoula"},
    "8729882": {"role": "both",  "label": "Fort Pickens, Pensacola Bay"},
    "8638610": {"role": "fails", "label": "Sewells Point, Hampton Roads"},
}

# ---------------------------------------------------------------------------
# GIS export settings (stage 08).
#   Esri-agnostic core: write a GeoPackage (and CSV) of per-PID results with
#   point geometry from OPUS lat/lon. An optional, separate publish script
#   (using GIS("pro")) can push to AGOL later without secrets touching code.
# ---------------------------------------------------------------------------
GIS_WINDOW = "W_MOD"            # which window's results become the feature layer
GIS_HEIGHT = "ellip_ht"         # height target carried as the primary attribute
GIS_CRS_EPSG = 4269             # NAD83 geographic (OPUS lat/lon are NAD83(2011))
S08_POINTS_CSV = os.path.join(GIS_DIR, "s08_pid_points.csv")
S08_GEOPACKAGE = os.path.join(GIS_DIR, "opus_outlier_results.gpkg")
S08_GPKG_LAYER = "pid_outlier_results"

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
INTERMEDIATE_FORMAT = "csv"  # 'csv' for now; switchable to 'parquet' later.


def ensure_dirs() -> None:
    """Create the output directory tree if it does not exist."""
    for d in (OUTPUT_DIR, TABLES_DIR, FIGURES_DIR, GIS_DIR):
        os.makedirs(d, exist_ok=True)
