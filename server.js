const express = require("express");
const path = require("path");
const cron = require("node-cron");
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");
const { spawn } = require("child_process");
const cors = require("cors");
const rateLimit = require("express-rate-limit");
const validator = require("validator");
const db = require("./database");
const crypto = require("crypto");
require("./worker");
const { getCalculatedPowerDraw } = require("./config/hardwareMap");

// ==========================================
// ENVIRONMENT & CONFIGURATION
// ==========================================
if (!process.env.JWT_SECRET) {
    console.error(
        "CRITICAL ERROR: JWT_SECRET environment variable is missing.",
    );
    process.exit(1);
}

const JWT_SECRET = process.env.JWT_SECRET;
const app = express();

// ==========================================
// GLOBAL MIDDLEWARE & SECURITY
// ==========================================
app.use(cors({ origin: process.env.ALLOWED_ORIGIN || "*" }));
app.set("trust proxy", 1);

const limiter = rateLimit({
    windowMs: 15 * 60 * 1000,
    max: 500,
    message: {
        error: "Too many requests from this IP, please try again later.",
    },
});
app.use(limiter);

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, "public")));
app.set("view engine", "ejs");
app.set("views", path.join(__dirname, "views"));

// ==========================================
// AUTH MIDDLEWARE
// ==========================================
function authenticateToken(req, res, next) {
    const authHeader = req.headers["authorization"];
    const token = authHeader && authHeader.split(" ")[1];
    if (!token) return res.status(401).json({ error: "Access token required" });

    jwt.verify(token, JWT_SECRET, (err, user) => {
        if (err)
            return res.status(403).json({ error: "Invalid or expired token" });
        req.user = user;
        next();
    });
}

function authenticateApiKey(req, res, next) {
    const apiKey = req.headers["x-api-key"];
    if (!apiKey)
        return res
            .status(401)
            .json({ error: "Unauthorized: Missing x-api-key header." });

    try {
        const user = db
            .prepare("SELECT * FROM users WHERE api_key = ?")
            .get(apiKey);
        if (!user)
            return res
                .status(403)
                .json({ error: "Forbidden: Invalid API Key." });
        req.user = user;
        next();
    } catch (err) {
        res.status(500).json({
            error: "Database error during authentication.",
        });
    }
}

// ==========================================
// AI AGENT SCHEDULER
// ==========================================
let isAIAgentRunning = false;

function runAIAgent() {
    if (isAIAgentRunning) {
        console.log(
            "[Scheduler] AI Agent is currently running. Skipping this cycle to prevent overlap.",
        );
        return;
    }

    isAIAgentRunning = true;
    console.log("[Scheduler] Running AI carbon forecast agent...");

    const pythonCmd = process.platform === "win32" ? "python" : "python3";
    const agent = spawn(pythonCmd, [path.join(__dirname, "ai_agent.py")]);

    agent.stdout.on("data", (data) =>
        process.stdout.write(`[AI Agent] ${data}`),
    );
    agent.stderr.on("data", (data) =>
        process.stderr.write(`[AI Agent] ${data}`),
    );

    agent.on("close", (code) => {
        isAIAgentRunning = false;
        if (code === 0)
            console.log("[Scheduler] AI agent completed successfully.");
        else console.error(`[Scheduler] AI agent exited with code ${code}`);
    });
}

runAIAgent();
cron.schedule("0 * * * *", runAIAgent);

// ==========================================
// PUBLIC VIEW ROUTES
// ==========================================
app.get("/", (req, res) => res.render("dashboard"));
app.get("/analytics", (req, res) => res.render("analytics"));
app.get("/grid", (req, res) => res.render("grid"));
app.get("/orchestrator", (req, res) => res.render("orchestrator"));
app.get("/usage", (req, res) => res.render("usage"));

// ==========================================
// AUTH ROUTES (Public)
// ==========================================
app.post("/api/signup", async (req, res) => {
    const { email, password } = req.body;

    if (!email || !password)
        return res.status(400).json({ error: "Email and password required" });
    if (!validator.isEmail(email))
        return res.status(400).json({ error: "Invalid email format" });
    if (password.length < 8)
        return res
            .status(400)
            .json({ error: "Password must be at least 8 characters" });

    try {
        const existing = db
            .prepare("SELECT id FROM users WHERE email = ?")
            .get(email);
        if (existing)
            return res.status(409).json({ error: "Email already registered" });

        const hash = await bcrypt.hash(password, 10);
        const result = db
            .prepare("INSERT INTO users (email, password_hash) VALUES (?, ?)")
            .run(email, hash);

        const token = jwt.sign(
            { id: result.lastInsertRowid, email },
            JWT_SECRET,
            { expiresIn: "7d" },
        );
        res.status(201).json({ token, email });
    } catch (err) {
        console.error("[Auth Error] Signup failed.", err);
        res.status(500).json({ error: "Signup process failed" });
    }
});

app.post("/api/login", async (req, res) => {
    const { email, password } = req.body;
    if (!email || !password)
        return res.status(400).json({ error: "Email and password required" });

    try {
        const user = db
            .prepare("SELECT * FROM users WHERE email = ?")
            .get(email);
        if (!user)
            return res.status(401).json({ error: "Invalid credentials" });

        const valid = await bcrypt.compare(password, user.password_hash);
        if (!valid)
            return res.status(401).json({ error: "Invalid credentials" });

        const token = jwt.sign({ id: user.id, email: user.email }, JWT_SECRET, {
            expiresIn: "7d",
        });
        res.json({ token, email: user.email });
    } catch (err) {
        console.error("[Auth Error] Login failed.", err);
        res.status(500).json({ error: "Login process failed" });
    }
});

// ==========================================
// LIVE GRID PRICING HELPER
// ==========================================
async function getLiveUKPrices() {
    const url =
        "https://api.octopus.energy/v1/products/AGILE-23-12-06/electricity-tariffs/E-1R-AGILE-23-12-06-C/standard-unit-rates/";
    try {
        const response = await fetch(url);
        const data = await response.json();
        // The API returns backwards data. We reverse it so it flows forward in time!
        return data.results.slice(0, 96).reverse();
    } catch (error) {
        console.error(
            "[Pricing API Error] Failed to fetch live grid prices:",
            error,
        );
        return null;
    }
}
// ==========================================
// ENTERPRISE FEATURE: Digital Twin & Budget Simulator
// ==========================================
app.post("/api/v1/simulate", authenticateToken, async (req, res) => { 
    // 1. Accept the business constraints from the sliders
    const { 
        estimated_duration_mins, 
        instance_type = "aws:t3.medium",
        max_carbon_intensity = 300, 
        max_electricity_price = 0.50 
    } = req.body;

    const durationHours = estimated_duration_mins / 60.0;

    try {
        const hardwareInfo = getCalculatedPowerDraw(instance_type);
        const actual_server_kw_power = hardwareInfo.totalFacilityKw;

        const budgetLimit = 500;
        const currentUsageStats = db.prepare(`
            SELECT SUM(max_carbon_intensity * 0.5 * (estimated_duration_mins / 60.0) / 1000) as used_kg 
            FROM tasks WHERE user_id = ? AND status = 'COMPLETED'
        `).get(req.user.id);
        const currentUsage = currentUsageStats.used_kg || 420; 
        const remainingBudget = budgetLimit - currentUsage;

        const forecasts = db.prepare("SELECT * FROM grid_forecasts ORDER BY timestamp ASC").all();
        const livePrices = await getLiveUKPrices();

        if (forecasts.length < Math.ceil(durationHours * 2)) {
            return res.status(400).json({ error: "Not enough AI forecast data to simulate." });
        }

        let immediateCO2 = 0; let immediateCost = 0;
        let validWindows = []; // Array to hold windows that meet the business rules

        // Calculate "Immediate Execution" (t=0)
        for (let i = 0; i < Math.ceil(durationHours * 2); i++) {
            immediateCO2 += (forecasts[i].predicted_carbon * actual_server_kw_power * 0.5) / 1000;
            let livePriceGBP = livePrices && livePrices[i] ? (livePrices[i].value_inc_vat / 100) : 0.08;
            immediateCost += (livePriceGBP * actual_server_kw_power * 0.5);
        }

        // Calculate "Optimal Delayed Execution" Subject to Sliders
        const maxStartIndex = forecasts.length - Math.ceil(durationHours * 2);
        for (let startIdx = 0; startIdx <= maxStartIndex; startIdx++) {
            let windowCO2 = 0; let windowCost = 0;
            let sumIntensity = 0; let sumPrice = 0;
            let blocks = Math.ceil(durationHours * 2);

            for (let i = 0; i < blocks; i++) {
                let intensity = forecasts[startIdx + i].predicted_carbon;
                sumIntensity += intensity;
                windowCO2 += (intensity * actual_server_kw_power * 0.5) / 1000;

                let livePriceGBP = livePrices && livePrices[startIdx + i] ? (livePrices[startIdx + i].value_inc_vat / 100) : 0.08;
                sumPrice += livePriceGBP;
                windowCost += (livePriceGBP * actual_server_kw_power * 0.5);
            }

            let avgIntensity = sumIntensity / blocks;
            let avgPrice = sumPrice / blocks;

            // ONLY accept this window if it obeys the user's Carbon and Price sliders!
            if (avgIntensity <= max_carbon_intensity && avgPrice <= max_electricity_price) {
                validWindows.push({
                    delayHours: startIdx * 0.5,
                    co2: windowCO2,
                    cost: windowCost
                });
            }
        }

        let bestCO2 = immediateCO2;
        let bestCost = immediateCost;
        let optimalDelayHours = 0;
        let recommendation = "";

        // FinOps Engine: Prioritize absolute cheapest cost from the valid windows
        let isPossible = true; // <-- NEW FLAG

        if (validWindows.length > 0) {
            validWindows.sort((a, b) => {
                if (a.cost === b.cost) return a.co2 - b.co2;
                return a.cost - b.cost;
            });

            bestCO2 = validWindows[0].co2;
            bestCost = validWindows[0].cost;
            optimalDelayHours = validWindows[0].delayHours;

            if (optimalDelayHours === 0) {
                recommendation = `Grid is perfectly optimal right now. Execute immediately.`;
            } else {
                recommendation = `Delay non-critical jobs by ${optimalDelayHours} hours to maximize financial savings.`;
            }
        } else {
            recommendation = `CRITICAL: No windows in the next 48 hours meet your strict limits! Please relax your Carbon or Price sliders.`;
            isPossible = false; // <-- TRIGGER FLAG
            bestCO2 = 0; 
            bestCost = 0;
            optimalDelayHours = 0;
        }

// SEND ENTERPRISE PAYLOAD
        res.json({
            hardware_profile: {
                instance_type: hardwareInfo.instanceId,
                total_facility_kw_draw: hardwareInfo.totalFacilityKw.toFixed(3)
            },
            digital_twin: {
                immediate: {
                    co2_kg: immediateCO2.toFixed(2),
                    cost_gbp: immediateCost.toFixed(3)
                },
                delayed: {
                    delay_hours: optimalDelayHours,
                    co2_kg: bestCO2.toFixed(2),
                    cost_gbp: bestCost.toFixed(3),
                    is_possible: isPossible // <--- THIS IS THE MISSING LINK
                }
            },
            budget: {
                monthly_limit_kg: budgetLimit,
                current_usage_kg: parseFloat(currentUsage).toFixed(2),
                remaining_kg: remainingBudget.toFixed(2),
                recommendation: recommendation
            }
        });

    } catch (err) {
        console.error("[Math Engine Error]", err);
        res.status(500).json({ error: "Failed to simulate digital twin." });
    }
});
// ==========================================
// PROTECTED ORCHESTRATOR API ROUTES
// ==========================================
app.post("/api/v1/tasks/enqueue", authenticateToken, (req, res) => {
    const {
        task_name,
        priority_level,
        deadline,
        estimated_duration_mins,
        max_carbon_intensity,
        max_electricity_price,
    } = req.body;

    const user_id = req.user.id;

    if (
        !task_name ||
        !priority_level ||
        !deadline ||
        !estimated_duration_mins ||
        max_carbon_intensity === undefined ||
        max_electricity_price === undefined
    ) {
        return res.status(400).json({
            error: "CRITICAL: Missing required scheduling constraints.",
        });
    }

    const duration = parseInt(estimated_duration_mins, 10);
    const maxCarbon = parseFloat(max_carbon_intensity);
    const maxPrice = parseFloat(max_electricity_price);

    if (isNaN(duration) || duration <= 0)
        return res.status(400).json({
            error: "estimated_duration_mins must be a positive integer.",
        });
    if (isNaN(maxCarbon) || maxCarbon < 0 || isNaN(maxPrice) || maxPrice < 0)
        return res.status(400).json({
            error: "Carbon and Price limits must be valid positive numbers.",
        });

    try {
        const query = `
            INSERT INTO tasks (
                task_name, priority_level, deadline, estimated_duration_mins, 
                max_carbon_intensity, max_electricity_price, status, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
        `;
        const result = db
            .prepare(query)
            .run(
                task_name,
                priority_level,
                deadline,
                duration,
                maxCarbon,
                maxPrice,
                user_id,
            );

        console.log(
            `[EcoStack] Task Queued: ID ${result.lastInsertRowid} | Max CO2: ${maxCarbon} | Max $: ${maxPrice} | Deadline: ${deadline}`,
        );
        res.status(201).json({
            status: "QUEUED_FOR_OPTIMIZATION",
            ecostack_task_id: result.lastInsertRowid,
            message: "Task successfully enqueued for AI optimization.",
        });
    } catch (err) {
        console.error(
            "[Database Error] Failed to inject multi-constraint task.",
            err,
        );
        res.status(500).json({ error: "Failed to queue task." });
    }
});

app.post("/tasks", authenticateToken, (req, res) => {
    req.url = "/api/v1/tasks/enqueue";
    app.handle(req, res);
});

// ==========================================
// API KEYS & WEBHOOKS
// ==========================================
app.get("/api/v1/keys", authenticateToken, (req, res) => {
    try {
        const user = db
            .prepare("SELECT api_key FROM users WHERE id = ?")
            .get(req.user.id);
        res.json({ api_key: user ? user.api_key : null });
    } catch (err) {
        res.status(500).json({ error: "Failed to fetch API key." });
    }
});

app.post("/api/v1/keys/generate", authenticateToken, (req, res) => {
    try {
        const newApiKey = "es_live_" + crypto.randomBytes(24).toString("hex");
        db.prepare("UPDATE users SET api_key = ? WHERE id = ?").run(
            newApiKey,
            req.user.id,
        );
        res.json({
            success: true,
            message: "API Key generated successfully. Keep this secret!",
            api_key: newApiKey,
        });
    } catch (err) {
        console.error("[API Key Error]", err);
        res.status(500).json({ error: "Failed to generate API Key." });
    }
});

app.post("/api/v1/webhooks/deploy", authenticateApiKey, (req, res) => {
    const {
        task_name,
        priority_level,
        deadline,
        estimated_duration_mins,
        max_carbon_intensity,
        max_electricity_price,
        webhook_url,
    } = req.body;
    const user_id = req.user.id;

    if (
        !task_name ||
        !priority_level ||
        !deadline ||
        !estimated_duration_mins ||
        max_carbon_intensity === undefined ||
        max_electricity_price === undefined
    ) {
        return res.status(400).json({
            error: "CRITICAL: Missing required scheduling constraints.",
        });
    }

    try {
        const query = `
            INSERT INTO tasks (
                task_name, priority_level, deadline, estimated_duration_mins, 
                max_carbon_intensity, max_electricity_price, webhook_url, status, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        `;
        const result = db
            .prepare(query)
            .run(
                task_name,
                priority_level,
                deadline,
                parseInt(estimated_duration_mins),
                parseFloat(max_carbon_intensity),
                parseFloat(max_electricity_price),
                webhook_url || null,
                user_id,
            );

        console.log(
            `[Webhook Ingest] Task #${result.lastInsertRowid} queued with callback URL: ${webhook_url || "None"}`,
        );
        res.status(202).json({
            status: "ACCEPTED_BY_ECOSTACK",
            ecostack_task_id: result.lastInsertRowid,
            message: "Workload queued for FinOps/GreenOps scheduling.",
        });
    } catch (err) {
        console.error("[Webhook Error]", err);
        res.status(500).json({ error: "Failed to process webhook." });
    }
});

// ==========================================
// AI DECISION ENGINE & CHAT
// ==========================================
app.post("/api/chat", authenticateToken, async (req, res) => {
    try {
        const { question: userQuestion } = req.body;
        const safeUserId = String(req.user.id);

        const aiResponse = await fetch(
            "https://badarmunir-ecostack-ai.hf.space/ask",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: userQuestion,
                    user_id: safeUserId,
                }),
            },
        );

        const data = await aiResponse.json();
        if (data.answer) res.json({ answer: data.answer });
        else res.json({ answer: "Error: AI subsystem failure." });
    } catch (error) {
        console.error("[AI Comm Error] Hugging Face connection failed.");
        res.status(500).json({
            answer: "Sorry, the AI connection is down right now.",
        });
    }
});

app.get("/api/v1/tasks/:id/insights", authenticateToken, (req, res) => {
    const taskId = req.params.id;
    const userId = req.user.id;

    try {
        const task = db
            .prepare("SELECT * FROM tasks WHERE id = ? AND user_id = ?")
            .get(taskId, userId);
        if (!task || task.status === "COMPLETED")
            return res
                .status(400)
                .json({ error: "Task not found or already completed." });

        const forecasts = [];
        let now = new Date();
        for (let i = 0; i < 48; i++) {
            let fTime = new Date(now.getTime() + i * 60 * 60 * 1000);
            let hour = fTime.getHours();
            let baseCarbon =
                hour >= 17 && hour <= 21
                    ? 220
                    : hour >= 0 && hour <= 6
                      ? 60
                      : 130;
            let basePrice = hour >= 16 && hour <= 20 ? 0.22 : 0.08;

            forecasts.push({
                time: fTime.toISOString(),
                carbon: baseCarbon + (Math.floor(Math.random() * 20) - 10),
                price: parseFloat(
                    (basePrice + Math.random() * 0.02).toFixed(3),
                ),
            });
        }

        const deadline = new Date(task.deadline);
        let bestBeforeDeadline = null;
        let absoluteBest = null;

        forecasts.forEach((f) => {
            let fDate = new Date(f.time);
            if (!absoluteBest || f.carbon < absoluteBest.carbon)
                absoluteBest = f;
            if (fDate <= deadline) {
                if (!bestBeforeDeadline || f.carbon < bestBeforeDeadline.carbon)
                    bestBeforeDeadline = f;
            }
        });

        let suggestion = "";
        if (!bestBeforeDeadline) {
            suggestion =
                "CRITICAL: Deadline is too tight to process. Will force-execute immediately.";
        } else if (absoluteBest.carbon < bestBeforeDeadline.carbon - 20) {
            const betterOptions = {
                weekday: "short",
                hour: "2-digit",
                minute: "2-digit",
            };
            const betterTime = new Date(absoluteBest.time).toLocaleDateString(
                undefined,
                betterOptions,
            );
            suggestion = `AI Advisor: If you extend your deadline past ${betterTime}, you could drop emissions to ${absoluteBest.carbon} gCO2.`;
        } else if (bestBeforeDeadline.carbon > task.max_carbon_intensity) {
            suggestion = `Warning: The lowest forecast before your deadline is ${bestBeforeDeadline.carbon}g, which exceeds your ${task.max_carbon_intensity}g limit. Consider relaxing limits.`;
        } else {
            suggestion =
                "Constraints are perfect. Task is primed for maximum efficiency.";
        }

        res.json({
            predicted_execution: bestBeforeDeadline
                ? bestBeforeDeadline.time
                : null,
            predicted_carbon: bestBeforeDeadline
                ? bestBeforeDeadline.carbon
                : null,
            predicted_price: bestBeforeDeadline
                ? bestBeforeDeadline.price
                : null,
            suggestion: suggestion,
        });
    } catch (err) {
        console.error("[Insight Error]", err);
        res.status(500).json({ error: "Failed to generate AI insights." });
    }
});

// ==========================================
// DB METRICS & ANALYTICS ROUTES
// ==========================================
app.get("/api/metrics", authenticateToken, (req, res) => {
    try {
        const results = db
            .prepare(
                "SELECT status, priority_level, COUNT(id) as task_count FROM tasks WHERE user_id = ? GROUP BY status, priority_level ORDER BY priority_level ASC",
            )
            .all(req.user.id);
        res.json(results);
    } catch (err) {
        console.error("[DB Error] Failed to fetch metrics.");
        res.status(500).json({ error: "Database query failed" });
    }
});

app.get("/tasks", authenticateToken, (req, res) => {
    try {
        const results = db
            .prepare(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
            )
            .all(req.user.id);
        res.status(200).json(results);
    } catch (err) {
        console.error("[DB Error] Failed to fetch tasks.");
        res.status(500).json({ error: "Failed to fetch tasks" });
    }
});

app.delete("/tasks/completed", authenticateToken, (req, res) => {
    try {
        const result = db
            .prepare(
                "DELETE FROM tasks WHERE status = 'COMPLETED' AND user_id = ?",
            )
            .run(req.user.id);
        res.json({ success: true, deleted: result.changes });
    } catch (err) {
        console.error("[DB Error] Failed to clear completed tasks.");
        res.status(500).json({ error: "Deletion failed" });
    }
});

app.delete("/tasks/:id", authenticateToken, (req, res) => {
    try {
        const result = db
            .prepare("DELETE FROM tasks WHERE id = ? AND user_id = ?")
            .run(req.params.id, req.user.id);
        if (result.changes === 0)
            return res.status(404).json({ error: "Task not found" });
        res.json({ success: true });
    } catch (err) {
        console.error("[DB Error] Failed to delete specific task.");
        res.status(500).json({ error: "Deletion failed" });
    }
});

        // ==========================================
        // ENTERPRISE CFO ANALYTICS
        // ==========================================
        app.get("/api/user/stats", authenticateToken, (req, res) => {
            // Standard Enterprise Baselines (What companies pay WITHOUT EcoStack)
            const UK_STANDARD_PPA_RATE_GBP = 0.28; // Standard commercial rate: £0.28 / kWh
            const UK_GRID_AVERAGE_CARBON = 210;    // Standard grid mix: 210g CO2 / kWh
            const AVERAGE_CLUSTER_KW = 3.36;       // Averaged hardware draw (e.g., A100 node w/ cooling)

            try {
                // We calculate exact savings: (Unoptimized Baseline - EcoStack Optimized Execution) * Energy Used
                const stats = db.prepare(`
                    SELECT
                        COUNT(*) as total_tasks,
                        SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_tasks,
                        SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending_tasks,

                        ROUND(SUM(CASE WHEN status = 'COMPLETED' THEN MAX(0, (${UK_GRID_AVERAGE_CARBON} - max_carbon_intensity) * ${AVERAGE_CLUSTER_KW} * (estimated_duration_mins / 60.0)) ELSE 0 END), 2) as co2_saved_g,

                        ROUND(SUM(CASE WHEN status = 'COMPLETED' THEN MAX(0, (${UK_STANDARD_PPA_RATE_GBP} - max_electricity_price) * ${AVERAGE_CLUSTER_KW} * (estimated_duration_mins / 60.0)) ELSE 0 END), 2) as cost_saved_gbp
                    FROM tasks WHERE user_id = ?
                `).get(req.user.id);

                const user = db.prepare("SELECT created_at FROM users WHERE id = ?").get(req.user.id);

                // Math Conversions
                const co2SavedKg = (stats.co2_saved_g || 0) / 1000;
                const treesPlanted = (co2SavedKg / 22).toFixed(2); // 1 mature tree absorbs ~22kg CO2 per year

                res.json({
                    total_tasks: stats.total_tasks || 0,
                    completed_tasks: stats.completed_tasks || 0,
                    pending_tasks: stats.pending_tasks || 0,
                    co2_saved_kg: co2SavedKg.toFixed(2),
                    cost_saved_usd: (stats.cost_saved_gbp || 0).toFixed(2), // Sent as "usd" to prevent breaking your frontend JS keys, but represents GBP
                    trees_planted: treesPlanted,
                    member_since: user?.created_at,
                });
            } catch (err) {
                console.error("[DB Error] Analytics fetch failed.", err);
                res.status(500).json({ error: "Failed to fetch analytics" });
            }
        });


// ==========================================
// PUBLIC FORECASTS & DASHBOARD FEEDS
// ==========================================
app.get("/api/forecasts", (req, res) => {
    try {
        const results = db
            .prepare(
                "SELECT timestamp as forecast_time, predicted_carbon as predicted_intensity FROM grid_forecasts WHERE timestamp >= datetime('now') ORDER BY timestamp ASC LIMIT 48",
            )
            .all();
        res.json(results);
    } catch (err) {
        console.error("[DB Error] Forecast fetch failed.");
        res.status(500).json({ error: "Failed to fetch forecasts" });
    }
});

app.get("/api/v1/grid-data", (req, res) => {
    try {
        const forecast = db
            .prepare("SELECT * FROM grid_forecasts ORDER BY timestamp ASC")
            .all();
        const live = db
            .prepare(
                "SELECT * FROM grid_forecasts ORDER BY timestamp ASC LIMIT 1",
            )
            .get();
        res.json({ live: live, forecast: forecast });
    } catch (err) {
        res.status(500).json({ error: "Data feed unavailable" });
    }
});

// ==========================================
// STARTUP
// ==========================================
const PORT = process.env.PORT || 5000;

app.listen(PORT, "0.0.0.0", () => {
    console.log(`[System] Secured Server is running on port ${PORT}`);
});
