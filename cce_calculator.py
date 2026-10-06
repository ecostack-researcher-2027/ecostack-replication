import sqlite3

db_path = "src/database.sqlite"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Extract Completed Tasks (W_total)
cursor.execute("""
    SELECT id, task_name, actual_joules, created_at 
    FROM tasks 
    WHERE status = 'COMPLETED' AND actual_joules IS NOT NULL
    ORDER BY id DESC LIMIT 5
""")
tasks = cursor.fetchall()

print("--- ECOSTACK CCE TELEMETRY REPORT ---")
total_joules = 0
total_carbon_grams = 0

for task in tasks:
    task_id, name, joules, exec_time = task

    # 2. Find Carbon Intensity for this execution window
    cursor.execute(
        """
        SELECT predicted_intensity 
        FROM carbon_forecasts 
        WHERE forecast_time >= ? 
        ORDER BY forecast_time ASC LIMIT 1
    """,
        (exec_time,),
    )

    forecast = cursor.fetchone()

    if forecast:
        intensity = forecast[0]

        # 3. The Math
        energy_kwh = joules / 3600000.0
        carbon_emitted = energy_kwh * intensity

        total_joules += joules
        total_carbon_grams += carbon_emitted

        print(
            f"Task [{name}]: {joules} Joules at {intensity} gCO2/kWh -> {carbon_emitted:.6f}g CO2"
        )
    else:
        print(f"Task [{name}]: {joules} Joules (No matching forecast found)")

# 4. Global CCE
if total_carbon_grams > 0:
    cce_score = total_joules / total_carbon_grams
    print("-" * 37)
    print(f"TOTAL WORKLOAD (W_total): {total_joules:.2f} Joules")
    print(f"TOTAL CARBON EMITTED:     {total_carbon_grams:.6f} grams")
    print(f"SYSTEM CCE SCORE:         {cce_score:.2f} Joules/gCO2")
    print("-" * 37)
else:
    print("Not enough data to calculate CCE.")

conn.close()
