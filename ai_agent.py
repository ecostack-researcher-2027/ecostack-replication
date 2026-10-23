import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
import warnings

warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ecostack.db")
DATA_PATH = os.path.join(BASE_DIR, "uk_grid_2021_2023.csv")

print("[EcoStack AI Agent] Initializing Predictive Orchestrator...")

# ==========================================
# PHASE 1: HISTORICAL DATA INGESTION
# ==========================================
print("Loading 2021-2023 historical grid dataset...")
if not os.path.exists(DATA_PATH):
    print(f"[ERROR] Dataset missing. Please place '{DATA_PATH}' in the directory to reproduce paper metrics.")
    exit(1)

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"])
df = df.sort_values(by="timestamp").reset_index(drop=True)

# Feature Engineering
df["hour"] = df["timestamp"].dt.hour
df["minute"] = df["timestamp"].dt.minute
df["day_of_week"] = df["timestamp"].dt.dayofweek
df["month"] = df["timestamp"].dt.month

features = ["month", "day_of_week", "hour", "minute"]
X = df[features]
y = df["intensity"]

# ==========================================
# PHASE 2: CHRONOLOGICAL 80/20 SPLIT & TRAINING
# ==========================================
print("Executing chronological 80/20 train-test split to prevent temporal leakage...")
split_idx = int(len(df) * 0.8)

X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
test_timestamps = df["timestamp"].iloc[split_idx:].reset_index(drop=True)

print(f"Training Data: {len(X_train)} records")
print(f"Testing Data: {len(X_test)} records")

print("Training Random Forest Regressor (this may take a moment)...")
model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)

# ==========================================
# PHASE 3: EVALUATION & METRICS REPRODUCTION
# ==========================================
print("\n--- REPRODUCING MANUSCRIPT METRICS ---")
y_pred = model.predict(X_test)

# 1. Standard Error Metrics
mae = mean_absolute_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)

print(f"Mean Absolute Error (MAE): {mae:.2f} gCO2/kWh (Paper claims ~12.4)")
print(f"R^2 Score:                 {r2:.2f} (Paper claims ~0.89)")

# 2. The 92% SLA Success Rate Metric
# "Successfully identifying a low-carbon execution window within 5% of the absolute minimum intensity for that day"
test_results = pd.DataFrame({
    'timestamp': test_timestamps,
    'actual_intensity': y_test.values,
    'predicted_intensity': y_pred,
    'date': test_timestamps.dt.date
})

successful_days = 0
total_days = test_results['date'].nunique()

for date, group in test_results.groupby('date'):
    if len(group) < 48:
        total_days -= 1 # Skip incomplete days
        continue

    actual_min = group['actual_intensity'].min()
    acceptable_threshold = actual_min * 1.05 # Within 5% of daily minimum

    # The orchestrator picks the window with the lowest PREDICTED intensity
    orchestrator_choice_idx = group['predicted_intensity'].idxmin()
    actual_intensity_at_choice = group.loc[orchestrator_choice_idx, 'actual_intensity']

    if actual_intensity_at_choice <= acceptable_threshold:
        successful_days += 1

success_rate = (successful_days / total_days) * 100 if total_days > 0 else 0
print(f"Daily Minimum Window Selection Accuracy: {success_rate:.1f}% (Paper claims 92.0%)")
print("--------------------------------------\n")

# ==========================================
# PHASE 4: LIVE FORECAST & SQLITE INJECTION
# ==========================================
print("Generating 24-hour forward predictions for Node.js Queue...")
now_utc = datetime.now(timezone.utc)
predictions_to_save = []

for i in range(48):
    future_time = now_utc + timedelta(minutes=30 * i)
    future_features = pd.DataFrame([{
        "month": future_time.month,
        "day_of_week": future_time.weekday(),
        "hour": future_time.hour, 
        "minute": future_time.minute
    }])

    predicted_intensity = float(model.predict(future_features)[0])
    predictions_to_save.append(
        (future_time.strftime("%Y-%m-%d %H:%M:%S"), predicted_intensity)
    )

try:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Ensure table exists and schemas match
    cur.execute('''
        CREATE TABLE IF NOT EXISTS grid_forecasts (
            timestamp TEXT PRIMARY KEY,
            predicted_carbon REAL
        )
    ''')

    cur.execute("DELETE FROM grid_forecasts")
    cur.executemany(
        "INSERT INTO grid_forecasts (timestamp, predicted_carbon) VALUES (?, ?)",
        predictions_to_save,
    )

    con.commit()
    count = len(predictions_to_save)
    con.close()
    print(f"SUCCESS: {count} future carbon predictions saved to EcoStack database (grid_forecasts table).")

except Exception as e:
    print(f"[DB Error] Failed to save predictions: {e}")