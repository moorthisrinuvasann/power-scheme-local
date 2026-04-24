# ⚡ AI Power Scheme Generator

An intelligent full-stack web application that automatically generates professional power scheme designs for electronic systems using LLM-based analysis via the OpenRouter API. The system selects optimal Buck Converters and LDO regulators from a local component database, performs per-rail engineering calculations, and exports a detailed HTML engineering report.

---

## 📸 Features

- **AI-Driven Design**: Uses OpenRouter LLM to analyze power requirements and generate 3 optimized power schemes
- **Per-Rail Engineering Analysis**: Ripple voltage, PSRR, and thermal calculations for **every individual output rail**
- **Interactive Schematics**: Auto-rendered Mermaid.js block diagrams showing the power distribution tree
- **Component Selection**: Picks optimal Buck Converters and LDOs from a local SQLite datasheet database with 1.5–1.75× current derating
- **Professional HTML Report**: Downloadable engineering report with Mermaid diagrams, calculation tables, and executive summary
- **Dual Input Mode**: Paste requirements directly in the textarea or upload a `.txt`/`.csv`/`.json` file
- **Thermal Validation**: Junction temperature estimates using `Tj = Ta + (Pdiss × Rθja)` from datasheet values

---

## 🗂️ Project Structure

```
openrouter-ai/
│
├── backend/
│   ├── main.py              # FastAPI server — LLM prompt engine, API routes, JSON parsing
│   └── ingest.py            # PDF datasheet ingestion → SQLite database builder
│
├── frontend/
│   ├── index.html           # Main UI — textarea input, upload zone, results layout
│   ├── app.js               # Core JS — generate flow, rail analysis renderer, HTML report exporter
│   └── style.css            # Dark-theme UI with glassmorphism, animations, responsive grid
│
├── datasheets/
│   ├── BuckConverter/       # PDF datasheets for all supported Buck Converters
│   │   ├── ltm4622.pdf
│   │   ├── ltm4630.pdf
│   │   ├── ltm4630a.pdf
│   │   ├── ltm4638.pdf
│   │   ├── ltm4650-1.pdf
│   │   ├── ltm4655.pdf
│   │   ├── ltm4671.pdf
│   │   ├── ltm4675.pdf
│   │   ├── ltm4676a.pdf
│   │   ├── ltm4680.pdf
│   │   ├── ltm4700.pdf
│   │   ├── ltm4705.pdf
│   │   ├── ltm8067fc.pdf
│   │   └── tpsm82866a.pdf
│   │
│   └── LDO/                 # PDF datasheets for all supported LDO Regulators
│       ├── 3070fc.pdf
│       ├── adp1763.pdf
│       ├── adp7159.pdf
│       ├── tps737.pdf
│       └── tps7a85a.pdf
│
├── requirement/
│   └── requirement1.txt     # Sample power requirement input file
│
├── html/
│   └── Power-Scheme-Report.html  # Sample exported engineering report
│
├── read_excel.py            # Utility: reads price/bug data from Excel into the database
├── ltm4638_info.txt         # Extracted datasheet text for LTM4638 (reference)
├── .gitignore               # Ignores __pycache__, .db files, venv, etc.
└── README.md                # This file
```

---

## ⚙️ Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10+, FastAPI, Uvicorn |
| **LLM API** | OpenRouter (`openrouter/free` model routing) |
| **LLM Client** | `openai` Python SDK (OpenAI-compatible) |
| **Database** | SQLite (component datasheet store) |
| **PDF Ingestion** | PyMuPDF (`fitz`) |
| **Frontend** | Vanilla HTML5, CSS3, JavaScript (ES6) |
| **Diagrams** | Mermaid.js (CDN) |
| **Styling** | Custom dark-theme CSS with glassmorphism |

---

## 🚀 Getting Started

### 1. Prerequisites

```bash
pip install fastapi uvicorn openai pymupdf openpyxl
```

### 2. Build the Component Database

Ingest all PDF datasheets into SQLite:

```bash
python backend/ingest.py
```

Optionally load pricing and bug data from Excel:

```bash
python read_excel.py
```

### 3. Start the Backend Server

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Open the Application

Navigate to **http://localhost:8000** in your browser.

---

## 📋 How to Use

1. **Enter API Key** — Paste your [OpenRouter API key](https://openrouter.ai/keys) (`sk-or-v1-...`)
2. **Enter Requirements** — Type or paste your power requirements in the text area, e.g.:
   ```
   Input Voltage : 12 V
   Output Voltages(V) : V1 = 3.3, V2 = 5, V3 = 0.85, V4 = 1.8
   Output Currents (A) : A1 = 6, A2 = 3.5, A3 = 0.5, A4 = 1.0
   Efficiency(%) : 90
   Ambient Temperature(degCel): 85
   PSRR : >35dB
   Ripple: <15mV
   ```
3. **Upload File (optional)** — Upload a `.txt` file instead; content auto-populates the textarea
4. **Generate** — Click **"Generate Power Scheme"** and wait ~30–60 seconds
5. **Review** — Browse 3 scheme options with schematics, components, and per-rail analysis
6. **Export** — Click **"Download HTML Report"** for a professional offline report

---

## 📐 Engineering Analysis — Per Rail

For each output voltage rail, the system calculates and displays:

| Analysis | Formula Used |
|---|---|
| **Voltage Ripple** | `V_rip = I_out / (8 × f_sw × C_out)` |
| **PSRR** | From component datasheet at the operating frequency |
| **Thermal (Junction Temp)** | `Tj = Ta + (Pdiss × Rθja)` |

All three are evaluated for **Pass / Fail** against the input requirements.

---

## 🧩 Supported Components

### Buck Converters
| Part | Key Spec |
|---|---|
| LTM4622 | Dual 4A, 4V–20V input |
| LTM4630 / LTM4630A | Dual 15A, high efficiency |
| LTM4638 | Single 10A, 3.4V–20V |
| LTM4650-1 | Single 25A |
| LTM4655 | Single 15A, automotive |
| LTM4671 | Quad 4A |
| LTM4675 | Dual 13A |
| LTM4676A | Dual 13A with PMBus |
| LTM4680 | Dual 10A with PMBus |
| LTM4700 | Dual 50A |
| LTM4705 | Single 40A |
| LTM8067FC | Isolated |
| TPSM82866A | 6A, small form factor |

### LDO Regulators
| Part | Key Spec |
|---|---|
| LT3070 | 4A, ultra-low noise |
| ADP1763 | 1A, low dropout |
| ADP7159 | 500mA, high PSRR |
| TPS737 | 1A, low quiescent |
| TPS7A85A | 4A, high PSRR |

---

## 🔒 Design Constraints Applied by AI

1. Buck converters are **single-output only** — one device per voltage rail
2. LDOs are sourced from **buck converter output rails**, not directly from input
3. **1.5–1.75× current derating** applied to all component selections
4. LDO input selected for **minimum dropout voltage**
5. Thermal check: junction temperature must not exceed component max rating
6. Splitting to multiple converters if thermal budget fails

---

## 📦 Version History

### v1.3.0 — 2026-04-24
- ✅ **Per-Rail Engineering Analysis**: Ripple, PSRR, and Thermal calculated individually for every voltage rail
- ✅ **Professional HTML Report Export**: Light-theme report built from raw LLM data (not DOM scraping) with colour-coded rail tables
- ✅ **Robust JSON Parsing**: Backend now extracts JSON by finding first/last `{}` braces, handles messy LLM responses
- ✅ **Mermaid CDN in exports**: Downloaded reports render diagrams automatically in browser
- ✅ **GitHub integration**: Project version-controlled and pushed to remote repository

### v1.2.0 — 2026-04-23
- ✅ **Textarea Input**: Added direct requirements input — no file upload required
- ✅ **Generate Button Fixed**: Rewrote event listener using `onclick` instead of `addEventListener` to resolve silent failures
- ✅ **File Upload Populates Textarea**: Selecting a file auto-fills the requirements box
- ✅ **Switching Frequency Display**: Added per-scheme switching frequency label in UI
- ✅ **Download Button Fixed**: HTML report downloads correctly using `Blob` + `URL.createObjectURL`

### v1.1.0 — 2026-04-18
- ✅ **No-Cache Headers**: Backend serves all static files with `Cache-Control: no-store` to prevent stale JS/HTML
- ✅ **Label-Based File Upload**: Replaced broken JS click handler with native `<label for="fileInput">` architecture
- ✅ **File Status Indicator**: Green ✓ feedback shown immediately after file selection
- ✅ **Mermaid Diagram Fix**: Exported HTML includes raw Mermaid code + CDN script for dynamic rendering
- ✅ **Document-Level Event Delegation**: File input `change` listener attached to `document` for reliability

### v1.0.0 — 2026-04-17
- 🎉 **Initial Release**
- ✅ FastAPI backend with OpenRouter LLM integration
- ✅ SQLite component database from PDF datasheets
- ✅ Three-scheme comparative output (Buck + LDO combinations)
- ✅ Mermaid.js schematics rendering in browser
- ✅ Combined specifications and thermal analysis tables
- ✅ Dark-theme glassmorphism UI
- ✅ PDF datasheet ingestion pipeline

---

## 📝 License

This project is intended for internal engineering use. All datasheet PDFs remain the property of their respective manufacturers (Analog Devices / Texas Instruments).

---

## 👤 Author

**Moorthi Srinuvasan**  
📧 moorthisrinuvasan95@gmail.com  
🔗 [github.com/moorthisrinuvasann](https://github.com/moorthisrinuvasann)
