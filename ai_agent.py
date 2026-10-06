import os
import sqlite3
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from sklearn.ensemble import RandomForestRegressor

# Ensure it points to the correct ecostack.db file in the same directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ecostack.db")

print("[AI Agent] EcoStack AI Agent Initializing...")

# ==========================================
# PHASE 1: DATA INGESTION
# ==========================================
print("Fetching historical grid data for training...")

now = datetime.now(timezone.utc)
past = now - timedelta(hours=24)
now_iso = now.strftime("%Y-%m-%dT%H:%MZ")
past_iso = past.strftime("%Y-%m-%dT%H:%MZ")

url = f"https://api.carbonintensity.org.uk/intensity/{past_iso}/{now_iso}"
response = requests.get(url, timeout=10)

if response.status_code != 200:
    print(f"API Error: {response.text}")
    exit(1)

json_response = response.json()
data = json_response.get("data", [])

if not data:
    print("No data received from the API.")
    exit(1)

# Extract timestamp and intensity (fallback to forecast if actual is missing)
df = pd.DataFrame(
    [
        {
            "timestamp": item["from"],
            "intensity": item["intensity"]["actual"]
            if item["intensity"]["actual"] is not None
            else item["intensity"]["forecast"],
        }
        for item in data
    ]
)

df["timestamp"] = pd.to_datetime(df["timestamp"])
df["hour"] = df["timestamp"].dt.hour
df["minute"] = df["timestamp"].dt.minute

# ==========================================
# PHASE 2: TRAIN THE MODEL
# ==========================================
print("Training Random Forest Regressor...")
X = df[["hour", "minute"]]
y = df["intensity"]

model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(X, y)
print("Model training complete.")

# ==========================================
# PHASE 3: PREDICTION & STORAGE
# ==========================================
print("Generating 24-hour forward predictions...")
predictions_to_save = []

now_utc = datetime.now(timezone.utc)

for i in range(48):
    future_time = now_utc + timedelta(minutes=30 * i)
    future_features = pd.DataFrame(
        [{"hour": future_time.hour, "minute": future_time.minute}]
    )
    predicted_intensity = int(model.predict(future_features)[0])

    predictions_to_save.append(
        (future_time.strftime("%Y-%m-%d %H:%M:%S"), predicted_intensity)
    )

# Connect to the correct database and insert into the correct table
try:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Target the grid_forecasts table specifically
    cur.execute("DELETE FROM grid_forecasts")

    # Match the columns expected by your Node.js backend
    cur.executemany(
        "INSERT INTO grid_forecasts (timestamp, predicted_carbon) VALUES (?, ?)",
        predictions_to_save,
    )

    con.commit()
    count = len(predictions_to_save)
    con.close()

    print(f"SUCCESS: {count} future carbon predictions saved to EcoStack database.")

except Exception as e:
    print(f"[DB Error] Failed to save predictions: {e}")
