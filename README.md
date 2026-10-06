# EcoStack: Predictive Orchestration for Zero-Carbon Cloud Computing
**Anonymous Replication Package for Peer Review (The Web Conference 2027)**

This repository contains the core orchestration middleware, predictive AI agent, and hardware-level telemetry scripts for the EcoStack framework, as detailed in our manuscript. 

To maintain double-blind review integrity, all author-identifying information, proprietary API keys, and production database credentials have been stripped.

## Repository Structure

*   `server.js`: The localized Node.js API interceptor and Time-To-Live (TTL) priority queue manager.
*   `ai_agent.py`: The predictive Random Forest forecasting agent that polls the UK National Grid ESO API for low-carbon execution windows.
*   `telemetry.py`: The CodeCarbon instrumentation script used to isolate and measure the physical hardware energy (Joules) consumed by the middleware layer.
*   `cce_calculator.py`: The validation script that calculates the empirical Compute-to-Carbon Efficiency (CCE) score.

## Replication Instructions

**1. Environment Setup**
The middleware requires Node.js (v18+) and Python (3.10+).
```bash
npm install express sqlite3 node-cron
pip install codecarbon requests
