EcoStack: Predictive Orchestration for Carbon-Aware Web-Facing AI Cloud Computing
Anonymous Replication Package for Peer Review (The Web Conference 2027)

This repository contains the core orchestration middleware, predictive AI agent, and hardware-level telemetry scripts for the EcoStack framework, as detailed in our manuscript. To maintain double-blind review integrity, all author-identifying information and API keys have been stripped.

Repository Structure
- /src/ai_agent.py: The predictive Random Forest agent. Evaluates the 2021-2023 historical dataset to calculate the reported MAE, R^2, and 92% SLA success metrics.
- /src/baseline_comparison.py: Simulates the 1,000 synthetic RAG prompts to generate `net_emissions_results.csv`, mathematically proving the net carbon savings versus immediate execution.
- /src/telemetry.py: The CodeCarbon instrumentation script isolating the physical hardware energy (Joules) consumed by the middleware layer, outputting to `telemetry_results.csv`.
- /src/server.js: The localized Node.js API interceptor and Time-To-Live (TTL) priority queue manager.

Replication Instructions
1. Environment Setup
The middleware requires Node.js (v18+) and Python (3.10+).
```bash
python3 -m venv venv
source venv/bin/activate
pip install pandas numpy scikit-learn codecarbon requests
npm install express sqlite3 node-cron