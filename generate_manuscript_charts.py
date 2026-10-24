"""Create publication-ready 300-DPI PNG charts from the reproduction CSVs.

Run from the project root with:
    python src/generate_manuscript_charts.py

Colors are collected in COLORS below for easy editing. The script uses only
Python's standard library and the ImageMagick `magick` executable.
"""

import csv
import html
import math
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
FORECAST_CSV = BASE_DIR / "forecast_predictions_2023.csv"
EMISSIONS_CSV = BASE_DIR / "net_emissions_results.csv"
FORECAST_PNG = BASE_DIR / "forecast_plot.png"
EMISSIONS_PNG = BASE_DIR / "emissions_plot.png"
DPI = 300

# Edit these hex values to change the chart colors.
COLORS = {
    "true": "#1F74AD",
    "predicted": "#E98E2E",
    "immediate": "#8CCEDE",
    "ecostack": "#61A9BD",
    "grid": "#C1C1C1",
    "text": "#666666",
    "white": "#FFFFFF",
}

FONT = "DejaVu Sans, Arial, sans-serif"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def svg_text(x, y, text, size=16, anchor="middle", color=None, weight="normal"):
    color = color or COLORS["text"]
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}">{html.escape(str(text))}</text>'
    )


def rasterize_svg(svg_source, output_path):
    image_magick = shutil.which("magick") or shutil.which("convert")
    if not image_magick:
        raise RuntimeError("ImageMagick is required to rasterize the PNG charts.")

    with tempfile.TemporaryDirectory(prefix="ecostack-chart-") as temp_dir:
        svg_path = Path(temp_dir) / "chart.svg"
        svg_path.write_text(svg_source, encoding="utf-8")
        subprocess.run(
            [
                image_magick,
                "-density",
                str(DPI),
                str(svg_path),
                "-background",
                COLORS["white"],
                "-alpha",
                "remove",
                "-alpha",
                "off",
                "-units",
                "PixelsPerInch",
                "-density",
                str(DPI),
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def build_forecast_chart(rows):
    subset = rows[: 7 * 48]  # First seven days of the 2023 holdout (336 points).
    if len(subset) != 336:
        raise ValueError(f"Expected 336 forecast rows for the chart, got {len(subset)}.")

    timestamps = [
        datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        for row in subset
    ]
    true_values = [float(row["actual_intensity"]) for row in subset]
    predicted_values = [float(row["rf_prediction"]) for row in subset]
    if any(not math.isfinite(value) for value in true_values + predicted_values):
        raise ValueError("Forecast chart data contains a non-finite value.")

    width, height = 1200, 620
    left, right, top, bottom = 120, 1155, 140, 520
    plot_width, plot_height = right - left, bottom - top
    all_values = true_values + predicted_values
    value_span = max(all_values) - min(all_values)
    step = max(10, math.ceil((value_span * 1.18 / 5) / 10) * 10)
    y_min = math.floor((min(all_values) - value_span * 0.08) / step) * step
    y_max = math.ceil((max(all_values) + value_span * 0.08) / step) * step
    if y_max <= y_min:
        y_max = y_min + step

    def x_position(index):
        return left + plot_width * index / (len(subset) - 1)

    def y_position(value):
        return bottom - plot_height * (value - y_min) / (y_max - y_min)

    def line_path(values):
        return " ".join(
            ("M" if index == 0 else "L")
            + f" {x_position(index):.2f} {y_position(value):.2f}"
            for index, value in enumerate(values)
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="12in" height="6.2in" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{COLORS["white"]}"/>',
        svg_text(width / 2, 42, "True vs. Predicted Carbon Intensity", 25, weight="bold"),
        svg_text(
            width / 2,
            72,
            "Synthetic 2023 holdout · January 1–7 · 30-minute intervals · gCO₂/kWh",
            15,
        ),
    ]

    # Y-axis ticks and horizontal grid.
    tick_count = 5
    for index in range(tick_count + 1):
        value = y_min + (y_max - y_min) * index / tick_count
        y = y_position(value)
        parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" '
            f'stroke="{COLORS["grid"]}" stroke-width="1"/>'
        )
        parts.append(svg_text(left - 14, y + 5, f"{value:.0f}", 13, anchor="end"))

    # Daily ticks are evenly spaced because the input is a regular 30-minute trace.
    for index in range(0, len(subset), 48):
        x = x_position(index)
        label = timestamps[index].strftime("%b %d")
        parts.append(
            f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{bottom}" '
            f'stroke="{COLORS["grid"]}" stroke-width="1" stroke-dasharray="2 5"/>'
        )
        parts.append(
            f'<line x1="{x:.2f}" y1="{bottom}" x2="{x:.2f}" y2="{bottom + 6}" '
            f'stroke="{COLORS["text"]}" stroke-width="1"/>'
        )
        parts.append(svg_text(x, bottom + 27, label, 13))

    parts.extend(
        [
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" '
            f'stroke="{COLORS["text"]}" stroke-width="1.5"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" '
            f'stroke="{COLORS["text"]}" stroke-width="1.5"/>',
            f'<path d="{line_path(true_values)}" fill="none" '
            f'stroke="{COLORS["true"]}" stroke-width="2.6" '
            'stroke-linejoin="round" stroke-linecap="round"/>',
            f'<path d="{line_path(predicted_values)}" fill="none" '
            f'stroke="{COLORS["predicted"]}" stroke-width="2.2" '
            'stroke-dasharray="7 4" stroke-linejoin="round" stroke-linecap="round"/>',
        ]
    )

    # Legend.
    legend_y = 108
    parts.extend(
        [
            f'<line x1="432" y1="{legend_y}" x2="468" y2="{legend_y}" '
            f'stroke="{COLORS["true"]}" stroke-width="3"/>',
            svg_text(478, legend_y + 5, "True", 14, anchor="start"),
            f'<line x1="570" y1="{legend_y}" x2="606" y2="{legend_y}" '
            f'stroke="{COLORS["predicted"]}" stroke-width="3" stroke-dasharray="7 4"/>',
            svg_text(616, legend_y + 5, "Predicted", 14, anchor="start"),
            f'<text x="38" y="{(top + bottom) / 2:.2f}" '
            f'transform="rotate(-90 38 {(top + bottom) / 2:.2f})" '
            f'text-anchor="middle" font-family="{FONT}" font-size="15" '
            f'fill="{COLORS["text"]}">Carbon intensity (gCO₂/kWh)</text>',
            svg_text((left + right) / 2, 570, "Date (UTC)", 14),
            svg_text(
                width / 2,
                602,
                "Simulated values; not official UK grid measurements. No prediction interval available.",
                12,
            ),
            "</svg>",
        ]
    )
    return "\n".join(parts)


def build_emissions_chart(rows):
    if not rows:
        raise ValueError("The emissions CSV contains no task rows.")

    immediate = sum(float(row["immediate_gCO2"]) for row in rows)
    ecostack = sum(float(row["ecostack_gCO2"]) for row in rows)
    if not math.isfinite(immediate) or not math.isfinite(ecostack):
        raise ValueError("Emissions chart data contains a non-finite total.")

    width, height = 1000, 600
    left, right, top, bottom = 135, 930, 125, 475
    plot_width, plot_height = right - left, bottom - top
    y_max = math.ceil(max(immediate, ecostack) * 1.22 / 200) * 200
    y_max = max(y_max, 200)

    def y_position(value):
        return bottom - plot_height * value / y_max

    centers = [left + plot_width * 0.32, left + plot_width * 0.72]
    bar_width = 190
    values = [immediate, ecostack]
    labels = ["Immediate", "EcoStack"]
    colors = [COLORS["immediate"], COLORS["ecostack"]]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="10in" height="6in" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{COLORS["white"]}"/>',
        svg_text(width / 2, 42, "Total Emissions: Immediate vs. EcoStack", 23, weight="bold"),
        svg_text(width / 2, 72, f"{len(rows):,} trace-driven tasks · total gCO₂", 15),
    ]

    tick_step = 200
    for value in range(0, y_max + 1, tick_step):
        y = y_position(value)
        parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" '
            f'stroke="{COLORS["grid"]}" stroke-width="1"/>'
        )
        parts.append(svg_text(left - 14, y + 5, f"{value}", 13, anchor="end"))

    for center, value, label, color in zip(centers, values, labels, colors):
        y = y_position(value)
        bar_height = bottom - y
        parts.append(
            f'<rect x="{center - bar_width / 2:.2f}" y="{y:.2f}" '
            f'width="{bar_width}" height="{bar_height:.2f}" fill="{color}"/>'
        )
        parts.append(
            svg_text(center, y - 12, f"{value:,.3f} gCO₂", 15, weight="bold")
        )
        parts.append(svg_text(center, bottom + 32, label, 16, weight="bold"))

    parts.extend(
        [
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" '
            f'stroke="{COLORS["text"]}" stroke-width="1.5"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" '
            f'stroke="{COLORS["text"]}" stroke-width="1.5"/>',
            f'<text x="42" y="{(top + bottom) / 2:.2f}" '
            f'transform="rotate(-90 42 {(top + bottom) / 2:.2f})" '
            f'text-anchor="middle" font-family="{FONT}" font-size="15" '
            f'fill="{COLORS["text"]}">Total emissions (gCO₂)</text>',
            svg_text(
                width / 2,
                555,
                "Synthetic seeded trace · EcoStack includes nominal 13.81 J middleware overhead per task",
                12,
            ),
            svg_text(width / 2, 580, "Simulated values; not official UK grid measurements.", 12),
            "</svg>",
        ]
    )
    return "\n".join(parts), immediate, ecostack


def main():
    if not FORECAST_CSV.is_file() or not EMISSIONS_CSV.is_file():
        raise FileNotFoundError(
            "Run src/reproduce_all.py first to create the forecast and emissions CSVs."
        )

    forecast_rows = read_csv(FORECAST_CSV)
    emissions_rows = read_csv(EMISSIONS_CSV)
    forecast_svg = build_forecast_chart(forecast_rows)
    emissions_svg, immediate_total, ecostack_total = build_emissions_chart(
        emissions_rows
    )

    rasterize_svg(forecast_svg, FORECAST_PNG)
    rasterize_svg(emissions_svg, EMISSIONS_PNG)

    print(f"Saved {FORECAST_PNG} ({DPI} DPI; first 336 test points).")
    print(
        f"Saved {EMISSIONS_PNG} ({DPI} DPI; "
        f"Immediate={immediate_total:.6f} gCO2, EcoStack={ecostack_total:.6f} gCO2)."
    )


if __name__ == "__main__":
    main()
