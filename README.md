# ⚡ AI Power Scheme Generator — v2.0

A **multi-agent AI pipeline** that automates power supply design for embedded and industrial systems. Provide your voltage/current requirements and get three complete, professionally evaluated power schemes with schematics, BOM, engineering analysis, DRC validation, and a downloadable HTML report.

---

## 🚀 Key Features

| Feature | Description |
|---|---|
| **3-Agent Pipeline** | Specialized LLM agents for component selection, topology design, and schematic generation |
| **Python Engineering Engine** | Exact ripple, PSRR, thermal, and current derating calculations — no LLM estimates |
| **Design Rule Checker (DRC)** | Validates dropout voltage, current derating, input voltage range, output validity |
| **Correction Agent** | Auto-replaces failed components and re-runs calculations in a closed feedback loop |
| **Scheme Comparison Table** | Side-by-side comparison: price, PCB area, BOM, Tj min/max, efficiency, DRC status |
| **Live Progress Stream** | Real-time 6-step SSE progress bar with agent status chips |
| **HTML Report Download** | Full professional report with comparison, DRC, corrections, schematics, and analysis |

---

## 🏗️ Architecture

### Agent Pipeline (6 Steps)

```
User Requirements
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1 — 🔍 Agent 1: Component Selector                       │
│  • Queries SQLite DB (Buck + LDO components)                   │
│  • Filters by category (Buck/LDO) before sending to LLM        │
│  • Applies 1.5–1.75× current derating rule                     │
│  • Produces 3 scheme options with varied topology              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2 — 🏗️ Agent 2: Topology Designer                        │
│  • Assigns V_in for every rail                                  │
│  • Routes LDOs to upstream Buck output rails                   │
│  • Assigns switching frequencies from datasheets               │
│  • Generates executive summary comparing all 3 schemes         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3 — 📐 Agent 3: Schematic Generator                      │
│  • Generates valid Mermaid flow diagrams (graph TD)            │
│  • One complete schematic per scheme                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4 — 🧮 Python Engineering Calculator                     │
│  Per rail, per scheme:                                         │
│  • Ripple: ΔV = ΔIL / (8 × f × C)                            │
│  • PSRR: Attenuation = 10^(PSRR_dB/20), V_out = V_in/Atten   │
│  • Thermal: Tj = Ta + (Pdiss × Rθja)                          │
│  • Derating: Factor = I_max / I_load (Pass ≥1.5×, Warn ≥1.2×)│
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 5 — 🔬 Design Rule Checker (DRC)                         │
│  • Current derating < 1.5×  → ERROR                           │
│  • LDO dropout violation    → ERROR                           │
│  • LDO dropout marginal     → WARNING                         │
│  • Buck Vin out of range    → ERROR                           │
│  • Vout ≥ Vin               → ERROR                           │
│  ─────────────────────────────────────────────────────────     │
│  If failures found → Agent 1b: Correction Agent fires          │
│  • Replaces only failed rails with better components           │
│  • Re-runs Calculator + DRC to confirm fixes                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 6 — ✅ Scheme Comparator                                  │
│  Per-scheme metrics: price, BOM count, PCB area estimate,      │
│  Tj min/max, avg efficiency, DRC status, corrections applied   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    Final Result (SSE event)
```

---

## 📁 Project Structure

```
openrouter-ai/
├── backend/
│   ├── main.py          # FastAPI app, SSE pipeline, /api/generate, /api/export
│   ├── agents.py        # Agent 1, 1b, 2, 3 — LLM orchestration via OpenRouter
│   ├── calculator.py    # Python ripple / PSRR / thermal / derating engine
│   ├── drc.py           # Design Rule Checker — 5 hard engineering rules
│   ├── comparator.py    # Scheme comparison metrics (PCB area, BOM, Tj, efficiency)
│   └── components.db    # SQLite database of Buck + LDO components
├── frontend/
│   ├── index.html       # Single-page app shell
│   ├── style.css        # Dark UI theme with glassmorphism
│   └── app.js           # SSE stream reader, renderers, report builder
└── README.md
```

---

## 🔌 Backend Modules

### `backend/agents.py` — LLM Agents

| Agent | Task | Input | Output |
|---|---|---|---|
| **Agent 1** | Component Selector | Requirements + component DB | 3 schemes with component selections |
| **Agent 2** | Topology Designer | Schemes from Agent 1 | Rail assignments with V_in, upstream, freq |
| **Agent 3** | Schematic Generator | Rail assignments | 3 Mermaid diagram strings |
| **Agent 1b** | Correction Agent | Failed rails + violations | Replacement component selections |

All agents use `openrouter/auto` model via the OpenAI-compatible OpenRouter API.

---

### `backend/calculator.py` — Engineering Engine

Replaces LLM estimates with exact datasheet-derived Python math:

```python
# Voltage Ripple (Buck)
dIL    = (V_in - V_out) * D / (f_sw * L)
dV_mV  = (dIL / (8 * f_sw * C)) * 1000

# PSRR Attenuation (LDO)
atten     = 10 ** (PSRR_dB / 20)
V_out_rip = V_in_rip / atten

# Junction Temperature
P_diss = (V_in - V_out) * I_out        # LDO
P_diss = (1 - eta) * V_out * I_out     # Buck
Tj     = Ta + P_diss * Rθja

# Current Derating
factor = I_max / I_load   # Pass ≥1.5×, Warn ≥1.2×, Fail <1.2×
```

Supports all Analog Devices LTM µModules and TI power devices.

---

### `backend/drc.py` — Design Rule Checker

Validates every rail assignment against hard engineering constraints:

| Rule | Condition | Severity |
|---|---|---|
| Current Derating | derating < 1.5× | ERROR |
| LDO Dropout Violation | V_in − V_out < V_dropout | ERROR |
| LDO Dropout Marginal | headroom < V_dropout × 1.2 | WARNING |
| Buck Vin Too Low | V_in < V_in_min (datasheet) | ERROR |
| Buck Vin Too High | V_in > V_in_max (datasheet) | ERROR |
| Output Voltage Invalid | V_out ≥ V_in | ERROR |

If **any** ERROR or WARNING is found, **Agent 1b (Correction Agent)** fires automatically, selects replacement components, and re-validates.

---

### `backend/comparator.py` — Scheme Comparator

Computes per-scheme metrics for the comparison table:

| Metric | Source |
|---|---|
| Total Price (INR) | Agent 1 component prices |
| Buck / LDO count | Rail assignments |
| PCB Area (mm²) | Datasheet package footprints × 1.4 routing margin |
| Output capacitors | C_out spec / 22µF per cap |
| Resistors | 2× feedback divider per rail + bootstrap |
| Tj Min / Tj Max | Calculator thermal results |
| Avg Efficiency | Datasheet η per buck rail |
| DRC errors/warnings | DRC module output |

---

## 🖥️ Frontend (`frontend/app.js`)

### SSE Stream Parser
Reads `text/event-stream` from `/api/generate` using proper **event-boundary parsing** (`\n\n` split), ensuring large JSON payloads are never dropped mid-stream.

### UI Sections (after generation)
1. **⚖️ Scheme Comparison Table** — side-by-side with ★ best-in-class highlighting
2. **Per Scheme:**
   - DRC Violations table (severity, rail, rule, detail, suggested fix)
   - Auto-Corrections log (which rail replaced and why)
   - Mermaid schematic diagram
   - Selected Components list with price and reasoning
   - Engineering Analysis per rail (Ripple, PSRR, Thermal, Derating)

### HTML Report Download
The **Download HTML Report** button POSTs the full report HTML to `/api/export` which returns it with `Content-Disposition: attachment` headers for reliable cross-browser download.

Report sections:
- Executive Summary
- Scheme Comparison Matrix (all metrics, ★ best values)
- Per scheme: DRC + Corrections → Schematics → Components → Engineering Table

---

## ⚙️ Setup & Run

### Prerequisites
- Python 3.10+
- OpenRouter API key → [openrouter.ai/keys](https://openrouter.ai/keys)

### Install
```bash
cd openrouter-ai
pip install fastapi uvicorn openai python-multipart
```

### Run
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
```

Open **http://localhost:8001**

### Usage
1. Enter your **OpenRouter API key**
2. Describe power requirements (e.g. `"12V input, need 3.3V@6A, 1.8V@2A, 1.0V@4A, 0.9V@1A, ambient 85°C"`)
3. Click **Generate Power Scheme**
4. Watch the 6-step live progress
5. Review comparison table, DRC results, schematics, and engineering analysis
6. Click **Download HTML Report** for the offline-ready report

---

## 🗄️ Component Database (`components.db`)

SQLite database with two tables:

### `components`
| Column | Description |
|---|---|
| `part_name` | IC part number (e.g. `LTM4638`) |
| `category` | `Buck Converter` or `LDO` |
| `price` | Unit price (INR) |
| `summary` | Datasheet key specs summary |

### Supported Components

**Buck Converters (Analog Devices LTM µModules + TI):**
LTM4638, LTM4622, LTM4622IV, LTM4630, LTM4630A, LTM4650, LTM4650-1, LTM4655, LTM4671, LTM4675, LTM4676A, LTM4680, LTM4700, LTM4705, TPSM82866A, LTM8067FC

**LDO Regulators:**
LT3070, ADP1763, ADP7159, TPS737, TPS73701DCQ, TPS7A85A

---

## 🔧 API Reference

### `POST /api/generate`
Accepts multipart form with:
- `file`: `.txt` requirements file
- `api_key`: OpenRouter API key

Returns: `text/event-stream` SSE with events:
- `event: progress` → `{"step": N, "total": 6, "message": "..."}`
- `event: result` → full JSON payload with schemes, comparison, DRC
- `event: error` → `{"message": "..."}`

### `POST /api/export`
Accepts raw HTML body, returns `Content-Disposition: attachment` response for download.

---

## 📊 Engineering Analysis — Per Rail

Each rail shows 4 rows:

| Analysis | Colour | What it shows |
|---|---|---|
| 🔵 Voltage Ripple | Blue | ΔV in mV at output caps |
| 🟣 PSRR | Purple | Noise attenuation in dB |
| 🩷 Thermal (Tj) | Pink | Junction temp in °C |
| 🟠 Current Derating | Orange | I_max/I_load ratio with 1.5× threshold |

Status badges: **Pass** (green) · **Warn** (amber) · **Fail** (red)

---

## 🔄 Phase Roadmap

| Phase | Status | Description |
|---|---|---|
| Phase 1 | ✅ Done | Single LLM call, basic HTML output |
| Phase 2 | ✅ Done | 3-agent pipeline, SSE streaming, Python calculator |
| Phase 3 | ✅ Done | DRC validator, correction agent, comparison table, derating |
| Phase 4 | 🔲 Planned | Follow-up chat for manual component override |
| Phase 5 | 🔲 Planned | Expanded component DB (TI, Renesas, Infineon) |

---

## 🔒 Security

- API keys are entered at runtime — never stored or committed
- `.env`, `*.db`, `__pycache__` are in `.gitignore`
- All LLM calls route through OpenRouter (no direct vendor API keys needed)

---

*Generated by AI Power Scheme Engineering System — Powered by OpenRouter*
