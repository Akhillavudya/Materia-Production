"""
backend/app/services/md_plots.py
=================================
Generates Energy vs. Time and Temperature vs. Time plots from MD CSV outputs.

Uses matplotlib with a clean, publication-style theme.
Outputs PNG files into the session output directory.
Also returns base64-encoded PNG strings so the frontend can render them
inline without a separate file request.

Public API
----------
    from app.services.md_plots import generate_md_plots

    plots = generate_md_plots(
        energy_csv = "/session/md_energy.csv",
        temp_csv   = "/session/md_temp.csv",
        output_dir = "/session/",
    )
    # plots["energy_png"]   → absolute path to energy plot PNG
    # plots["temp_png"]     → absolute path to temperature plot PNG
    # plots["energy_b64"]   → base64 PNG string (data URI ready)
    # plots["temp_b64"]     → base64 PNG string
    # plots["combined_png"] → side-by-side combined plot path
"""

import csv
import base64
from pathlib import Path
from typing import Optional


# ── Public API ────────────────────────────────────────────────────────────────

def generate_md_plots(
    energy_csv:  str,
    temp_csv:    str,
    output_dir:  str,
    target_temp: Optional[float] = None,
    title:       Optional[str]   = None,
) -> dict:
    """
    Generate Energy vs. Time and Temperature vs. Time plots.

    Parameters
    ----------
    energy_csv   : Path to md_energy.csv (columns: step, time_fs, energy_eV).
    temp_csv     : Path to md_temp.csv   (columns: step, time_fs, temperature_K).
    output_dir   : Directory to write PNG files.
    target_temp  : Draw a horizontal dashed line at this temperature [K].
                   Auto-detected from the data mean if None.
    title        : Optional title prefix for both plots.

    Returns
    -------
    {
      "status":       "ok" | "error",
      "message":      str,
      "energy_png":   str | None,   # absolute path
      "temp_png":     str | None,
      "combined_png": str | None,
      "energy_b64":   str | None,   # base64-encoded PNG, data URI ready
      "temp_b64":     str | None,
      "combined_b64": str | None,
    }
    """
    try:
        import matplotlib
        matplotlib.use("Agg")   # non-interactive backend — safe in FastAPI
        import matplotlib.pyplot as plt
    except ImportError:
        return {
            "status":  "error",
            "message": "matplotlib is not installed. Run: pip install matplotlib",
            "energy_png": None, "temp_png": None, "combined_png": None,
            "energy_b64": None, "temp_b64": None, "combined_b64": None,
        }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Read CSVs ─────────────────────────────────────────────────────────────
    energy_data = _read_csv(energy_csv, x_col="time_fs", y_col="energy_eV")
    temp_data   = _read_csv(temp_csv,   x_col="time_fs", y_col="temperature_K")

    if not energy_data["x"] and not temp_data["x"]:
        return {
            "status":  "error",
            "message": "Both CSV files are empty or missing.",
            "energy_png": None, "temp_png": None, "combined_png": None,
            "energy_b64": None, "temp_b64": None, "combined_b64": None,
        }

    # ── Auto-detect target temperature ───────────────────────────────────────
    if target_temp is None and temp_data["y"]:
        import statistics
        target_temp = round(statistics.mean(temp_data["y"]), 1)

    # ── Style ─────────────────────────────────────────────────────────────────
    _apply_style(plt)

    # ── Plot 1: Energy vs. Time ───────────────────────────────────────────────
    energy_png = energy_b64 = None
    if energy_data["x"]:
        fig, ax = plt.subplots(figsize=(8, 4))
        _plot_energy(ax, energy_data, title=title)
        fig.tight_layout()
        energy_png = str(out_dir / "md_energy_plot.png")
        fig.savefig(energy_png, dpi=150, bbox_inches="tight")
        energy_b64 = _to_b64(energy_png)
        plt.close(fig)

    # ── Plot 2: Temperature vs. Time ─────────────────────────────────────────
    temp_png = temp_b64 = None
    if temp_data["x"]:
        fig, ax = plt.subplots(figsize=(8, 4))
        _plot_temperature(ax, temp_data, target_temp=target_temp, title=title)
        fig.tight_layout()
        temp_png = str(out_dir / "md_temp_plot.png")
        fig.savefig(temp_png, dpi=150, bbox_inches="tight")
        temp_b64 = _to_b64(temp_png)
        plt.close(fig)

    # ── Combined 2-panel plot ─────────────────────────────────────────────────
    combined_png = combined_b64 = None
    if energy_data["x"] and temp_data["x"]:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=False)
        _plot_energy(ax1, energy_data, title=title)
        _plot_temperature(ax2, temp_data, target_temp=target_temp)
        fig.suptitle(
            title or "MD Simulation Summary",
            fontsize=13, fontweight="bold", y=1.01,
        )
        fig.tight_layout()
        combined_png = str(out_dir / "md_combined_plot.png")
        fig.savefig(combined_png, dpi=150, bbox_inches="tight")
        combined_b64 = _to_b64(combined_png)
        plt.close(fig)

    files_written = [f for f in (energy_png, temp_png, combined_png) if f]
    message = f"Generated {len(files_written)} MD plot(s): {', '.join(Path(f).name for f in files_written)}."

    return {
        "status":       "ok",
        "message":      message,
        "energy_png":   energy_png,
        "temp_png":     temp_png,
        "combined_png": combined_png,
        "energy_b64":   energy_b64,
        "temp_b64":     temp_b64,
        "combined_b64": combined_b64,
    }


# ── Private: plot helpers ─────────────────────────────────────────────────────

def _plot_energy(ax, data: dict, title: Optional[str] = None):
    """Draw energy vs time on ax."""
    import numpy as np

    x_ps = [t / 1000.0 for t in data["x"]]   # fs → ps
    y    = data["y"]

    ax.plot(x_ps, y, color="#2563EB", linewidth=1.0, alpha=0.85, label="E (eV)")

    # Rolling mean overlay (window = 5% of data)
    if len(y) > 20:
        window = max(5, len(y) // 20)
        y_arr  = np.array(y, dtype=float)
        kernel = np.ones(window) / window
        y_smooth = np.convolve(y_arr, kernel, mode="valid")
        x_smooth = x_ps[window - 1:]
        ax.plot(x_smooth, y_smooth, color="#DC2626", linewidth=1.8,
                linestyle="--", label=f"Rolling mean (w={window})", alpha=0.9)

    ax.set_xlabel("Time (ps)", fontsize=11)
    ax.set_ylabel("Energy (eV)", fontsize=11)
    ax.set_title(
        f"{title + ' — ' if title else ''}Potential Energy vs. Time",
        fontsize=12,
    )
    ax.legend(fontsize=9, framealpha=0.6)
    ax.grid(True, linestyle=":", alpha=0.5)
    _tight_ylim(ax, y)


def _plot_temperature(ax, data: dict, target_temp: Optional[float], title: Optional[str] = None):
    """Draw temperature vs time on ax."""
    import numpy as np

    x_ps = [t / 1000.0 for t in data["x"]]   # fs → ps
    y    = data["y"]

    ax.plot(x_ps, y, color="#16A34A", linewidth=0.8, alpha=0.7, label="T (K)")

    # Rolling mean overlay
    if len(y) > 20:
        window = max(5, len(y) // 20)
        y_arr  = np.array(y, dtype=float)
        kernel = np.ones(window) / window
        y_smooth = np.convolve(y_arr, kernel, mode="valid")
        x_smooth = x_ps[window - 1:]
        ax.plot(x_smooth, y_smooth, color="#15803D", linewidth=2.0,
                linestyle="--", label=f"Rolling mean (w={window})", alpha=0.95)

    # Target temperature line
    if target_temp is not None:
        ax.axhline(
            y=target_temp, color="#EA580C", linewidth=1.5,
            linestyle="-.", label=f"Target {target_temp:.0f} K", alpha=0.8,
        )

    ax.set_xlabel("Time (ps)", fontsize=11)
    ax.set_ylabel("Temperature (K)", fontsize=11)
    ax.set_title(
        f"{title + ' — ' if title else ''}Temperature vs. Time",
        fontsize=12,
    )
    ax.legend(fontsize=9, framealpha=0.6)
    ax.grid(True, linestyle=":", alpha=0.5)
    _tight_ylim(ax, y, padding_fraction=0.15)


def _tight_ylim(ax, y: list, padding_fraction: float = 0.1):
    """Set y-limits with a small padding around the data range."""
    if not y:
        return
    import numpy as np
    y_arr = np.array(y, dtype=float)
    y_arr = y_arr[~np.isnan(y_arr)]
    if len(y_arr) == 0:
        return
    y_min, y_max = float(y_arr.min()), float(y_arr.max())
    span = y_max - y_min
    if span < 1e-10:
        span = abs(y_min) * 0.1 or 1.0
    pad = span * padding_fraction
    ax.set_ylim(y_min - pad, y_max + pad)


def _apply_style(plt):
    """Apply a clean, minimal style."""
    plt.rcParams.update({
        "figure.facecolor":   "white",
        "axes.facecolor":     "#F8FAFC",
        "axes.edgecolor":     "#CBD5E1",
        "axes.spines.top":    False,
        "axes.spines.right":  False,
        "axes.labelcolor":    "#1E293B",
        "xtick.color":        "#475569",
        "ytick.color":        "#475569",
        "font.family":        "sans-serif",
        "font.size":          10,
    })


# ── Private: I/O helpers ──────────────────────────────────────────────────────

def _read_csv(path: str, x_col: str, y_col: str) -> dict:
    """Read two columns from a CSV file. Returns {"x": [...], "y": [...]}."""
    result: dict = {"x": [], "y": []}
    p = Path(path)
    if not p.exists():
        return result
    try:
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    result["x"].append(float(row[x_col]))
                    result["y"].append(float(row[y_col]))
                except (KeyError, ValueError):
                    continue
    except Exception as e:
        print(f"[MDPlots] CSV read error ({path}): {e}")
    return result


def _to_b64(png_path: str) -> Optional[str]:
    """Read a PNG file and return a base64-encoded data URI string."""
    try:
        with open(png_path, "rb") as f:
            raw = f.read()
        encoded = base64.b64encode(raw).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    except Exception as e:
        print(f"[MDPlots] base64 encode error: {e}")
        return None