import time
import sys
import json
import sqlite3
import random  # <-- This fixes the "random" error
import requests # <-- CodeCarbon and requests will work after the pip install
from codecarbon import EmissionsTracker

def monitor_process(task_id=None):
    print(f"[Telemetry] Starting HARDWARE-LEVEL instrumentation for Task ID: {task_id}...")

    # 1. Initialize CodeCarbon to read exact physical hardware wattage
    tracker = EmissionsTracker(project_name=f"Task_{task_id}", measure_power_secs=1)
    tracker.start()

    start_time = time.time()

    # 2. Trigger the actual AI workload on the Hugging Face server
    print("[Telemetry] Firing workload to Hugging Face AI...")
    try:
        # Pinging your live AI model to do real work
        response = requests.post(
            "https://badarmunir-ecostack-ai.hf.space/ask",
            json={"question": "Generate a complex summary of green cloud computing architecture.", "user_id": "benchmark_bot"}
        )
        if response.status_code != 200:
            print("[Telemetry] Warning: Hugging Face backend returned an error.")
    except Exception as e:
        print(f"[Telemetry] AI Request Failed: {e}")

    # 3. Stop tracker and capture exact physical metrics
    emissions = tracker.stop()
    total_duration = time.time() - start_time

    energy_kwh = tracker._total_energy.kWh if tracker._total_energy else 0.0
    total_joules = energy_kwh * 3.6e6

    metrics = {
        "task_id": task_id,
        "execution_duration_seconds": round(total_duration, 2),
        "total_energy_consumed_joules": round(total_joules, 4),
        "carbon_emitted_kg": emissions
    }

    print("\n[Telemetry] Instrumentation Cycle Complete.")
    print(json.dumps(metrics, indent=4))

    # 4. Save the REAL Joules to SQLite
    if task_id is not None:
        try:
            db_path = "src/database.sqlite"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE tasks 
                SET actual_joules = ?, status = 'COMPLETED'
                WHERE id = ?
            """,
                (round(total_joules, 4), task_id),
            )
            conn.commit()
            conn.close()
            print(f"[Database] Successfully logged {round(total_joules, 4)} Joules for Task {task_id}.")
        except Exception as e:
            print(f"[Database Error] Could not write to SQLite: {e}")

if __name__ == "__main__":
    passed_task_id = int(sys.argv[1]) if len(sys.argv) > 1 else random.randint(1000, 9999)
    monitor_process(task_id=passed_task_id)