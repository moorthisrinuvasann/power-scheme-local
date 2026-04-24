import json
import re
import sqlite3
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from openai import AsyncOpenAI
from backend.calculator import calculate_all_rails

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_PATH = "components.db"

# ── Component DB ──────────────────────────────────────────────────────────────
def get_all_components():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT part_name, category, price, bug_details, summary_text FROM components")
    rows = cursor.fetchall()
    conn.close()
    return [{"part_name": r[0], "category": r[1], "price": r[2],
             "bug_details": r[3], "summary": (r[4] or "")[:800]} for r in rows]

# ── Parse requirements from text ──────────────────────────────────────────────
def parse_requirements(text: str) -> dict:
    """Extract numeric values from free-text requirements."""
    req = {"ta": 85, "ripple_mv": 15, "psrr_db": 35}
    m = re.search(r'[Aa]mbient\s*[Tt]emp[^:]*:\s*([\d.]+)', text)
    if m: req["ta"] = float(m.group(1))
    m = re.search(r'[Rr]ipple[^:]*:\s*<?\s*([\d.]+)\s*m[Vv]', text)
    if m: req["ripple_mv"] = float(m.group(1))
    m = re.search(r'PSRR[^:]*:\s*>?\s*([\d.]+)\s*d[Bb]', text)
    if m: req["psrr_db"] = float(m.group(1))
    return req

# ── Main API endpoint ─────────────────────────────────────────────────────────
@app.post("/api/generate")
async def generate_scheme(file: UploadFile = File(...), api_key: str = Form(...)):
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is required.")

    try:
        content = await file.read()
        requirements = content.decode('utf-8')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {e}")

    req_params = parse_requirements(requirements)
    components = get_all_components()
    components_json = json.dumps(components, indent=2)

    # ── Simplified LLM prompt: topology + components + mermaid ONLY ───────────
    prompt = f"""
You are an expert power electronics engineer. The user has provided the following electrical requirements:
{requirements}

Available components in the database:
{components_json}

DESIGN RULES:
1. Use Buck converters and LDOs. LDO inputs must come from a Buck output rail.
2. Apply 1.5-1.75x current derating when selecting components.
3. Each Buck is SINGLE-OUTPUT. Use separate Bucks or Buck+LDO tree for multiple rails.
4. Minimize dropout voltage for LDO selection.
5. Design EXACTLY THREE different power schemes.
6. In schematics_mermaid, use exact IC part numbers as node labels (e.g., A[LTM4638]).
7. JSON ONLY. No markdown. No comments. No trailing commas. Strict double quotes.

Return ONLY valid JSON matching this exact schema:
{{
    "final_summary": "Comparison of 3 schemes: price, efficiency, topology trade-offs.",
    "requirements_parsed": {{
        "ta_c": {req_params['ta']},
        "ripple_limit_mv": {req_params['ripple_mv']},
        "psrr_limit_db": {req_params['psrr_db']}
    }},
    "schemes": [
        {{
            "scheme_name": "Scheme 1 Name",
            "total_price": 0.0,
            "switching_frequency": "1MHz",
            "selected_components": [
                {{"part_name": "LTM4638", "reasoning": "why selected", "price": 0.0}}
            ],
            "rail_assignments": [
                {{
                    "rail": "V1 (3.3V @ 6A)",
                    "v_out": 3.3,
                    "i_out": 6.0,
                    "v_in": 12.0,
                    "component": "LTM4638",
                    "comp_type": "buck",
                    "upstream_component": ""
                }},
                {{
                    "rail": "V2 (1.8V @ 0.5A)",
                    "v_out": 1.8,
                    "i_out": 0.5,
                    "v_in": 3.3,
                    "component": "TPS7A85A",
                    "comp_type": "ldo",
                    "upstream_component": "LTM4638"
                }}
            ],
            "schematics_mermaid": "graph TD\\n A[12V Input] --> B[LTM4638 Buck]\\n B --> C[3.3V Rail]"
        }}
    ]
}}
"""

    result_text = ""
    try:
        client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        response = await client.chat.completions.create(
            model="openrouter/auto",
            messages=[
                {"role": "system", "content": "You output strictly valid JSON only. No markdown, no comments, no trailing commas."},
                {"role": "user", "content": prompt}
            ],
            extra_headers={
                "HTTP-Referer": "http://localhost:8001",
                "X-Title": "Power Scheme Generator"
            }
        )

        result_text = response.choices[0].message.content

        # Robustly extract JSON block
        start_idx = result_text.find("{")
        end_idx   = result_text.rfind("}")
        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON object found in LLM response.")
        result_text = result_text[start_idx:end_idx+1]

        llm_data = json.loads(result_text)

        # ── Phase 1: Replace LLM estimates with real Python calculations ──────
        for scheme in llm_data.get("schemes", []):
            rail_assignments = scheme.get("rail_assignments", [])
            if rail_assignments:
                scheme["rail_analysis"] = calculate_all_rails(rail_assignments, req_params)
            else:
                scheme["rail_analysis"] = []

            # Clean switching_frequency field
            sf = scheme.get("switching_frequency", "1MHz")
            scheme["switching_frequency"] = sf

        return JSONResponse(content=llm_data)

    except json.JSONDecodeError as e:
        print(f"DEBUG raw response:\n{result_text}")
        raise HTTPException(status_code=500, detail=f"JSON Parse Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Error: {str(e)}")


# ── Static file serving (no-cache) ────────────────────────────────────────────
@app.get("/")
def read_index():
    return FileResponse("frontend/index.html", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"
    })

@app.get("/static/{file_path:path}")
def serve_static(file_path: str):
    return FileResponse(f"frontend/{file_path}", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"
    })

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
