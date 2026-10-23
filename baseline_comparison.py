import csv
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "net_emissions_results.csv"

print("[EcoStack] Running Baseline vs. EcoStack Net Emissions Simulation...")

NUM_TASKS = 1000
GPU_ENERGY_KWH = 0.005
MIDDLEWARE_OVERHEAD_KWH = 3.836e-6
PEAK_INTENSITY = 250
VALLEY_INTENSITY = 102

results = []
total_immediate_carbon = 0
total_ecostack_carbon = 0

for task_id in range(1, NUM_TASKS + 1):
    immediate_emissions = GPU_ENERGY_KWH * PEAK_INTENSITY
    total_immediate_carbon += immediate_emissions

    ecostack_emissions = (
        GPU_ENERGY_KWH * VALLEY_INTENSITY
        + MIDDLEWARE_OVERHEAD_KWH * PEAK_INTENSITY
    )
    total_ecostack_carbon += ecostack_emissions

    results.append(
        {
            "task_id": task_id,
            "immediate_gCO2": round(immediate_emissions, 4),
            "ecostack_gCO2": round(ecostack_emissions, 4),
            "savings_gCO2": round(immediate_emissions - ecostack_emissions, 4),
        }
    )

total_savings = total_immediate_carbon - total_ecostack_carbon
percentage_saved = total_savings / total_immediate_carbon * 100

print(f"\n--- NET EMISSIONS RESULTS ({NUM_TASKS:,} Tasks) ---")
print(f"Total Emissions (Immediate): {total_immediate_carbon:.2f} gCO2")
print(f"Total Emissions (EcoStack):  {total_ecostack_carbon:.2f} gCO2")
print(f"Net Carbon Saved:            {total_savings:.2f} gCO2 ({percentage_saved:.1f}% Reduction)")
print(
    "Middleware Overhead Impact:  Minimal "
    f"({MIDDLEWARE_OVERHEAD_KWH * PEAK_INTENSITY * NUM_TASKS:.4f} gCO2 total)"
)

with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as csv_file:
    writer = csv.DictWriter(
        csv_file,
        fieldnames=[
            "task_id",
            "immediate_gCO2",
            "ecostack_gCO2",
            "savings_gCO2",
        ],
    )
    writer.writeheader()
    writer.writerows(results)

print(f"\nSUCCESS: Exported comparative results to {OUTPUT_FILE}")
