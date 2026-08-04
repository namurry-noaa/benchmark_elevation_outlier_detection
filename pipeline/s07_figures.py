"""
s07_figures.py -- Stage 07 of the OPUS outlier-analysis pipeline.

Renders the presentation figures from prior-stage CSV outputs. This stage is
the ONLY one that needs a plotting stack; it is deliberately decoupled so it
can run in a separate matplotlib-capable environment while the analysis stages
stay dependency-light.

Required packages (beyond the Python stdlib):
    matplotlib      (plotting)
    numpy           (matplotlib dependency; light array math here)
That is all. No pandas, no seaborn, no scipy required.

Figures produced (PNG, into outputs/figures/):
  fig1_detection_vs_offset.png   detection rate vs injected offset (4 methods)
  fig2_false_alarm_vs_offset.png false-alarm rate vs offset  (the money chart)
  fig3_roc_style.png             detection vs false-alarm, per offset (ROC-ish)
  fig4_shift_distribution.png    method-induced shift from raw mean (box/hist)
  fig5_flag_rate_by_window.png   % obs flagged per method x window
  fig6_worked_example.png        a representative caterpillar plot (one PID)
  fig7_station_temporal.png      per-mark temporal cleaning at 3 example stations
  fig8_station_spatial.png       spatial (inter-mark) 4cm gate vs robust screen

Run (in an env with matplotlib):  python pipeline/s07_figures.py
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

try:
    import matplotlib
    matplotlib.use("Agg")  # headless / file output
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "\nERROR: matplotlib is required for stage 07 but is not installed.\n"
        "Create/activate an env with:  matplotlib  numpy\n"
        f"(import error: {exc})\n"
    )
    sys.exit(2)

METHODS = ("fixed", "s1", "s2", "mad")
COLORS = {
    "fixed": "#d62728",      # red
    "s1": "#ff7f0e",         # orange
    "s2": "#9467bd",         # purple
    "mad": "#2ca02c",        # green
    "consensus": "#1f77b4",  # blue
}
# Per-method marker shapes so the four series are distinguishable WITHOUT color
# (508 / color-blind accessibility). Applied to the line plots (fig1-3).
MARKERS = {
    "fixed": "s",            # square
    "s1": "^",               # triangle-up
    "s2": "D",               # diamond
    "mad": "o",              # circle
    "consensus": "v",        # triangle-down
}
# Line styles reinforce the same distinction for the connecting lines.
LINESTYLES = {
    "fixed": "--",
    "s1": ":",
    "s2": "-.",
    "mad": "-",
    "consensus": (0, (3, 1, 1, 1)),
}
LABELS = config.FIG_METHOD_LABELS

# Flag-status glyphs for the per-observation / per-mark scatter plots (fig6/fig7).
# Redundant encoding: distinct COLOR *and* distinct SHAPE (and size) per status,
# so the meaning survives grayscale printing and color-blindness.
#   kept        -> green circle
#   flag/4cm    -> orange square   (dropped by the fixed/4cm rule)
#   outlier     -> red triangle    (a genuine outlier: MAD / robust screen)
STATUS_STYLE = {
    "kept":    {"color": "#2ca02c", "marker": "o", "size": 90,  "label": "kept"},
    "flag4cm": {"color": "#ff7f0e", "marker": "s", "size": 120, "label": "flagged by 4 cm rule"},
    "outlier": {"color": "#d62728", "marker": "^", "size": 150, "label": "outlier (robust)"},
}


def _f(s):
    if s is None or str(s).strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
def load_injection_summary():
    """offset -> method -> (detection_rate, false_alarm_rate)"""
    data = defaultdict(dict)
    with open(config.S05_INJECTION_SUMMARY_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            off = float(r["offset_m"])
            data[off][r["method"]] = (float(r["detection_rate"]),
                                      float(r["false_alarm_rate"]))
    return data


def fig1_detection(inj):
    offsets = sorted(inj)
    fig, ax = plt.subplots(figsize=(7, 5))
    for meth in METHODS:
        y = [inj[o][meth][0] for o in offsets]
        ax.plot([o * 100 for o in offsets], y,
                marker=MARKERS[meth], ls=LINESTYLES[meth], markersize=7,
                color=COLORS[meth], label=LABELS[meth])
    ax.set_xlabel("Injected outlier magnitude (cm)")
    ax.set_ylabel("Detection rate (planted outlier caught)")
    ax.set_title("Outlier detection power vs. injected offset")
    ax.set_ylim(-0.03, 1.03)
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, "fig1_detection_vs_offset.png")


def fig2_false_alarm(inj):
    offsets = sorted(inj)
    fig, ax = plt.subplots(figsize=(7, 5))
    for meth in METHODS:
        y = [inj[o][meth][1] for o in offsets]
        ax.plot([o * 100 for o in offsets], y,
                marker=MARKERS[meth], ls=LINESTYLES[meth], markersize=7,
                color=COLORS[meth], label=LABELS[meth])
    ax.set_xlabel("Injected outlier magnitude (cm)")
    ax.set_ylabel("False-alarm rate (good obs wrongly flagged)")
    ax.set_title("False alarms vs. injected offset\n"
                 "(flat = robust; rising = convicts bystanders)")
    ax.set_ylim(-0.03, 1.03)
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, "fig2_false_alarm_vs_offset.png")


def fig3_roc(inj):
    offsets = sorted(inj)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    for meth in METHODS:
        xs = [inj[o][meth][1] for o in offsets]  # false alarm
        ys = [inj[o][meth][0] for o in offsets]  # detection
        ax.plot(xs, ys, marker=MARKERS[meth], ls=LINESTYLES[meth], markersize=7,
                color=COLORS[meth], label=LABELS[meth])
        for o in offsets:
            ax.annotate(f"{o*100:.0f}", (inj[o][meth][1], inj[o][meth][0]),
                        fontsize=6, alpha=0.6)
    ax.plot([0, 1], [0, 1], "k--", alpha=0.3, label="chance")
    ax.set_xlabel("False-alarm rate  (good observations wrongly flagged)")
    ax.set_ylabel("Detection rate  (real outliers caught)")
    ax.set_title("Detection vs. false alarm (ROC-style)\n"
                 "upper-left is best; dashed line = chance; labels = offset (cm)")
    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(-0.03, 1.03)
    ax.grid(True, alpha=0.3)
    ax.legend()
    _save(fig, "fig3_roc_style.png")


# ---------------------------------------------------------------------------
def load_shifts():
    """method -> list of shift values (cm) for the config figure window/height."""
    shifts = defaultdict(list)
    path = config.S06_METHOD_COMPARE_CSV
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["window"] != config.FIG_WINDOW or r["height_target"] != config.FIG_HEIGHT:
                continue
            for meth in ("fixed", "s1", "s2", "mad", "consensus"):
                v = _f(r.get(f"shift_{meth}"))
                if v is not None:
                    shifts[meth].append(v * 100.0)
    return shifts


def fig4_shift(shifts):
    order = [m for m in config.FIG_METHOD_ORDER if shifts.get(m)]
    data = [shifts[m] for m in order]
    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(data, orientation="vertical", showfliers=True, patch_artist=True,
                    tick_labels=[LABELS[m] for m in order])
    for patch, m in zip(bp["boxes"], order):
        patch.set_facecolor(COLORS[m])
        patch.set_alpha(0.5)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylabel("Shift of cleaned average from raw mean (cm)")
    ax.set_title(f"How much each method moves the height "
                 f"({config.FIG_WINDOW}, {config.FIG_HEIGHT}, n>=3)")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, "fig4_shift_distribution.png")


# ---------------------------------------------------------------------------
def load_flag_rates():
    """window -> method -> (n_flagged_obs, n_obs) over multi_method groups."""
    counts = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    path = os.path.join(config.TABLES_DIR, "s03_obs_flags.csv")
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["height_target"] != config.FIG_HEIGHT:
                continue
            if r["group_method"] != "multi_method":
                continue
            win = r["window"]
            for meth in METHODS:
                counts[win][meth][1] += 1
                counts[win][meth][0] += int(r[f"flag_{meth}"])
    return counts


def fig5_flag_rate(counts):
    windows = list(config.WINDOWS.keys())
    import numpy as np
    x = np.arange(len(windows))
    w = 0.2
    # Distinct hatch per method reinforces the color (508 / grayscale safe).
    hatches = {"fixed": "//", "s1": "..", "s2": "xx", "mad": "\\\\"}
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, meth in enumerate(METHODS):
        rates = []
        for win in windows:
            fl, tot = counts[win][meth]
            rates.append(100.0 * fl / tot if tot else 0.0)
        ax.bar(x + (i - 1.5) * w, rates, w, color=COLORS[meth],
               hatch=hatches.get(meth, ""), edgecolor="k", label=LABELS[meth])
    ax.set_xticks(x)
    ax.set_xticklabels(windows)
    ax.set_ylabel("% of observations flagged (n>=3 groups)")
    ax.set_title(f"Flag rate by method and window ({config.FIG_HEIGHT})")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    _save(fig, "fig5_flag_rate_by_window.png")


# ---------------------------------------------------------------------------
def load_worked_example():
    """
    Pick a representative multi_method group: n>=3, MAD flags exactly one obs,
    and that obs is NOT flagged by 2sigma (illustrates the divergence).
    Return (pid, list of obs dicts with value/date/flags, group stats).
    """
    path = os.path.join(config.TABLES_DIR, "s03_obs_flags.csv")
    groups = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["window"] == config.FIG_WINDOW and r["height_target"] == config.FIG_HEIGHT \
               and r["group_method"] == "multi_method":
                groups[r["pid"]].append(r)
    best = None
    for pid, obs in groups.items():
        if len(obs) < 3:
            continue
        n_mad = sum(int(o["flag_mad"]) for o in obs)
        n_s2 = sum(int(o["flag_s2"]) for o in obs)
        n_fixed = sum(int(o["flag_fixed"]) for o in obs)
        # a clean teaching case: MAD isolates exactly 1, 2sigma misses it,
        # and 4cm over-flags (>=2). Prefer moderate n for readability.
        if n_mad == 1 and n_s2 == 0 and n_fixed >= 2 and 3 <= len(obs) <= 8:
            best = (pid, obs)
            break
    if best is None:  # fallback: any group MAD flags exactly one
        for pid, obs in groups.items():
            if sum(int(o["flag_mad"]) for o in obs) == 1 and len(obs) >= 3:
                best = (pid, obs)
                break
    return best


def fig6_worked(example):
    if not example:
        print("  (fig6 skipped: no suitable worked-example group found)")
        return
    pid, obs = example
    obs = sorted(obs, key=lambda o: o["obs_date"])
    xs = list(range(len(obs)))
    ys = [float(o["value"]) for o in obs]
    mean = float(obs[0]["grp_mean"])
    median = float(obs[0]["grp_median"])

    fig, ax = plt.subplots(figsize=(8, 5))
    # points encoded by flag status with REDUNDANT color + shape + size
    # (508 / color-blind safe): MAD-flagged = red triangle (real outlier);
    # 4cm-flagged-but-not-MAD = orange square; otherwise = green circle.
    used_status = set()
    for i, o in enumerate(obs):
        if int(o["flag_mad"]) == 1:
            status = "outlier"
        elif int(o["flag_fixed"]) == 1:
            status = "flag4cm"
        else:
            status = "kept"
        st = STATUS_STYLE[status]
        ax.scatter(xs[i], ys[i], s=st["size"], marker=st["marker"],
                   color=st["color"], edgecolor="k", zorder=3,
                   label=st["label"] if status not in used_status else None)
        used_status.add(status)
        # annotate the height value below each point (always) ...
        ax.annotate(f"{ys[i]:.3f} m", (xs[i], ys[i]),
                    textcoords="offset points", xytext=(0, -14),
                    ha="center", fontsize=7, color="#333333")
        # ... and which methods flagged it above (if any)
        tags = []
        for meth, sym in (("fixed", "4cm"), ("s1", "1s"), ("s2", "2s"), ("mad", "MAD")):
            if int(o[f"flag_{meth}"]) == 1:
                tags.append(sym)
        if tags:
            ax.annotate(",".join(tags), (xs[i], ys[i]),
                        textcoords="offset points", xytext=(8, 6), fontsize=7)
    ax.axhline(mean, color="#ff7f0e", ls="--", label="raw mean")
    ax.axhline(median, color="#1f77b4", ls=":", label="median")
    ax.set_xticks(xs)
    ax.set_xticklabels([o["obs_date"] for o in obs], rotation=30, ha="right", fontsize=7)
    # Give the categorical x-axis breathing room so near-identical dates
    # (e.g. observations one day apart) don't collide.
    ax.set_xlim(-0.5, len(obs) - 0.5)
    ax.margins(y=0.15)
    ax.set_xlabel("Observation date (equally spaced; not to time scale)", fontsize=8)
    ax.set_ylabel(f"{config.FIG_HEIGHT} (m)")
    ax.set_title(f"Worked example: PID {pid} ({config.FIG_WINDOW})\n"
                 f"shape+color = flag status; tags show which methods flagged each obs")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    _save(fig, "fig6_worked_example.png")


# ---------------------------------------------------------------------------
# fig7 / fig8 : station-level (spatial / inter-mark) worked examples
# ---------------------------------------------------------------------------
def load_station_examples():
    """
    Read Deliverable D and return an ordered list of (station_id, role, label,
    marks) for the configured example stations. `marks` is a list of dicts with
    per-mark elevation and both spatial-screen flags, plus station stats.
    """
    path = config.S06_STATION_CSV
    if not os.path.exists(path):
        return []
    by_station = defaultdict(list)
    stats_by_station = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_station[r["station_id"]].append(r)
            stats_by_station[r["station_id"]] = r  # any row carries station stats
    order = ("works", "both", "fails")
    examples = getattr(config, "STATION_EXAMPLES", {})
    picked = []
    for sid, meta in examples.items():
        if sid not in by_station:
            continue
        picked.append((sid, meta.get("role", ""), meta.get("label", sid),
                       by_station[sid], stats_by_station[sid]))
    picked.sort(key=lambda t: order.index(t[1]) if t[1] in order else 99)
    return picked


ROLE_TITLE = {
    "works": "tight station",
    "both": "one offset mark",
    "fails": "wide (real) spread",
}


def fig7_station_temporal(examples):
    """Per-mark cleaned elevations at each example station, one panel per station.
    Points are each benchmark's temporally-cleaned (MAD) elevation; the station
    median line and the +/- spatial-tolerance band are drawn for context."""
    if not examples:
        print("  (fig7 skipped: no station-example data)")
        return
    n = len(examples)
    fig, axes = plt.subplots(1, n, figsize=(5.2 * n, 5.0), squeeze=False)
    tol = config.SPATIAL_TOLERANCE_M
    for ax, (sid, role, label, marks, sstat) in zip(axes[0], examples):
        cmed = float(sstat["station_median_m"])
        xs = list(range(len(marks)))
        for i, m in enumerate(marks):
            e = float(m["mark_elevation_m"])
            cut4 = int(m["spatial_4cm_flag"]) == 1
            cutr = int(m["spatial_robust_flag"]) == 1
            # Redundant color + shape + size (508 / color-blind safe):
            #   robust-cut  -> red triangle   (a genuine spatial outlier)
            #   4cm-only cut -> orange square  (good mark the 4cm gate would drop)
            #   kept         -> green circle
            if cutr:
                st = STATUS_STYLE["outlier"]
            elif cut4:
                st = STATUS_STYLE["flag4cm"]
            else:
                st = STATUS_STYLE["kept"]
            ax.scatter(i, e, s=st["size"], marker=st["marker"],
                       color=st["color"], edgecolor="k", zorder=3)
            ax.annotate(m["pid"], (i, e), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=7)
        ax.axhline(cmed, color="#1f77b4", ls=":", label="station median")
        ax.axhspan(cmed - tol, cmed + tol, color="#1f77b4", alpha=0.08,
                   label=f"+/- {tol*100:.0f} cm band")
        ax.set_title(f"{sid} {label}\n({ROLE_TITLE.get(role, role)})", fontsize=9)
        ax.set_xticks(xs)
        ax.set_xticklabels([m["pid"] for m in marks], rotation=40, ha="right", fontsize=7)
        ax.set_ylabel(f"{config.STATION_HEIGHT} (m)")
        ax.margins(y=0.20)
        ax.grid(True, axis="y", alpha=0.3)
    # shared legend -- matches the redundant shape+color encoding above
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], marker="o", ls="", mfc="#2ca02c", mec="k", markersize=9,
               label="kept by both (green circle)"),
        Line2D([0], [0], marker="s", ls="", mfc="#ff7f0e", mec="k", markersize=10,
               label="4 cm drops, robust keeps (orange square)"),
        Line2D([0], [0], marker="^", ls="", mfc="#d62728", mec="k", markersize=11,
               label="both flag = real outlier (red triangle)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=8,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Per-benchmark elevations at example tide stations "
                 f"({config.STATION_WINDOW}, {config.STATION_HEIGHT})", fontsize=11)
    _save(fig, "fig7_station_temporal.png")

def fig8_station_spatial(examples):
    """Bar view: how many marks the SPATIAL 4 cm gate discards vs the robust
    screen at each example station. Makes the over-zealous-gate point directly."""
    if not examples:
        print("  (fig8 skipped: no station-example data)")
        return
    import numpy as np
    labels, n_marks, n_4cm, n_rob = [], [], [], []
    for (sid, role, label, marks, sstat) in examples:
        labels.append(f"{sid}\n{label.split(',')[0]}")
        n_marks.append(len(marks))
        n_4cm.append(sum(int(m["spatial_4cm_flag"]) for m in marks))
        n_rob.append(sum(int(m["spatial_robust_flag"]) for m in marks))
    x = np.arange(len(labels))
    w = 0.25
    fig, ax = plt.subplots(figsize=(8, 5))
    # Hatching gives each bar series a distinct texture (508 / grayscale safe),
    # so the three groups read even without color.
    ax.bar(x - w, n_marks, w, color="#7f7f7f", hatch="//",
           edgecolor="k", label="marks at station")
    ax.bar(x, n_4cm, w, color="#ff7f0e", hatch="..",
           edgecolor="k", label="discarded by 4 cm spatial gate")
    ax.bar(x + w, n_rob, w, color="#2ca02c", hatch="xx",
           edgecolor="k", label="flagged by robust screen")
    for i in range(len(labels)):
        ax.annotate(str(n_marks[i]), (x[i] - w, n_marks[i]), ha="center",
                    va="bottom", fontsize=8)
        ax.annotate(str(n_4cm[i]), (x[i], n_4cm[i]), ha="center", va="bottom", fontsize=8)
        ax.annotate(str(n_rob[i]), (x[i] + w, n_rob[i]), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Number of benchmarks")
    ax.set_title("Spatial (inter-mark) screen at example stations:\n"
                 "4 cm gate vs. robust screen")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    _save(fig, "fig8_station_spatial.png")


# ---------------------------------------------------------------------------
def _save(fig, name):
    config.ensure_dirs()
    out = os.path.join(config.FIGURES_DIR, name)
    fig.tight_layout()
    fig.savefig(out, dpi=config.FIG_DPI)
    plt.close(fig)
    print(f"  wrote {out}")


def main() -> None:
    print("=" * 70)
    print("STAGE 07  figures  -- rendering")
    print("=" * 70)
    inj = load_injection_summary()
    fig1_detection(inj)
    fig2_false_alarm(inj)
    fig3_roc(inj)
    fig4_shift(load_shifts())
    fig5_flag_rate(load_flag_rates())
    fig6_worked(load_worked_example())
    station_examples = load_station_examples()
    fig7_station_temporal(station_examples)
    fig8_station_spatial(station_examples)
    print("-" * 70)
    print(f"  figures dir: {config.FIGURES_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
