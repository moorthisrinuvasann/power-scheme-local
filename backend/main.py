import json
import re
import sqlite3
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from openai import AsyncOpenAI
from backend.calculator import calculate_all_rails
from backend.drc import run_drc, check_calc_failures, drc_summary
from backend.comparator import compare_schemes
from backend.agents import (
    agent_component_selector,
    agent_topology_designer,
    agent_schematic_generator,
    agent_correction,
)

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

# ── Parse requirements ────────────────────────────────────────────────
def parse_requirements(text: str) -> dict:
    req = {"ta": 85, "ripple_mv": 15, "psrr_db": 35}
    m = re.search(r'[Aa]mbient\s*[Tt]emp[^:]*:\s*([\d.]+)', text)
    if m: req["ta"] = float(m.group(1))
    m = re.search(r'[Rr]ipple[^:]*:\s*<?\s*([\d.]+)\s*m[Vv]', text)
    if m: req["ripple_mv"] = float(m.group(1))
    m = re.search(r'PSRR[^:]*:\s*>?\s*([\d.]+)\s*d[Bb]', text)
    if m: req["psrr_db"] = float(m.group(1))
    return req


def validate_requirements(text: str) -> str | None:
    """Returns an error string if requirements are invalid, else None."""
    if not text or len(text.strip()) < 10:
        return "Requirements text is too short. Please describe your voltage/current needs."
    if not re.search(r'\d+\.?\d*\s*[Vv]', text):
        return "No voltage specification found (e.g. '3.3V', '1.8V'). Please include target voltages."
    if not re.search(r'\d+\.?\d*\s*[Aa]', text):
        return "No current specification found (e.g. '2A', '500mA'). Please include load currents."
    return None

# ── SSE helper ────────────────────────────────────────────────────────────────
def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

# ── Main streaming endpoint ───────────────────────────────────────────────────
@app.post("/api/generate")
async def generate_scheme(file: UploadFile = File(...), api_key: str = Form(...)):
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is required.")
    try:
        content = await file.read()
        requirements = content.decode('utf-8')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {e}")

    req_params  = parse_requirements(requirements)
    components  = get_all_components()

    # ── Pre-flight validation ──────────────────────────────────────────
    err = validate_requirements(requirements)
    if err:
        raise HTTPException(status_code=422, detail=err)

    async def stream():
        try:
            # ── AGENT 1: Component Selection ──────────────────────────────
            yield sse_event("progress", {"step": 1, "total": 6,
                "message": "Agent 1/3: Selecting optimal components for each rail..."})

            agent1 = await agent_component_selector(requirements, components, api_key)

            yield sse_event("progress", {"step": 1, "total": 6,
                "message": f"Agent 1 done. Selected components for {len(agent1.get('schemes', []))} schemes."})

            # ── AGENT 2: Topology Design ───────────────────────────────
            yield sse_event("progress", {"step": 2, "total": 6,
                "message": "Agent 2/3: Designing power distribution topology..."})

            agent2 = await agent_topology_designer(requirements, agent1, api_key)

            yield sse_event("progress", {"step": 2, "total": 6,
                "message": "Agent 2 done. Power tree topology finalized."})

            # ── AGENT 3: Schematic Generation ───────────────────────────
            yield sse_event("progress", {"step": 3, "total": 6,
                "message": "Agent 3/3: Generating Mermaid schematics..."})

            schemes = agent2.get("schemes", [])
            mermaid_codes = await agent_schematic_generator(schemes, api_key)

            yield sse_event("progress", {"step": 3, "total": 6,
                "message": "Agent 3 done. Schematics generated."})

            # ── PYTHON CALCULATOR: Real engineering values ─────────────────
            yield sse_event("progress", {"step": 4, "total": 6,
                "message": "🧮 Running Python engineering calculator (ripple / PSRR / thermal)..."})

            agent1_schemes = agent1.get("schemes", [])

            for i, scheme in enumerate(schemes):
                scheme["schematics_mermaid"] = mermaid_codes[i] if i < len(mermaid_codes) else ""

                if i < len(agent1_schemes):
                    a1 = agent1_schemes[i]
                    scheme["selected_components"] = [
                        {"part_name": sel["component"],
                         "reasoning":  sel.get("reasoning", ""),
                         "price":      sel.get("price", 0.0)}
                        for sel in a1.get("component_selections", [])
                    ]
                    scheme["total_price"] = a1.get("total_price", 0.0)
                else:
                    scheme["selected_components"] = []
                    scheme["total_price"] = 0.0

                rail_assignments = scheme.get("rail_assignments", [])
                scheme["rail_analysis"] = calculate_all_rails(rail_assignments, req_params)

            # ── PHASE 3: Design Rule Check ─────────────────────────────────
            yield sse_event("progress", {"step": 5, "total": 6,
                "message": "🔬 Running Design Rule Check (DRC)..."})

            for scheme in schemes:
                rail_assignments = scheme.get("rail_assignments", [])
                drc_violations   = run_drc(rail_assignments, req_params)
                calc_failures    = check_calc_failures(scheme.get("rail_analysis", []))
                scheme["drc_violations"] = drc_violations
                scheme["drc_summary"]    = drc_summary(drc_violations)

                # ── PHASE 3: Correction Agent (only if failures found) ─────
                all_issues = drc_violations + calc_failures
                if all_issues:
                    yield sse_event("progress", {"step": 5, "total": 6,
                        "message": f"⚠️ {len(all_issues)} issue(s) in '{scheme['scheme_name']}'. Running correction agent..."})

                    try:
                        correction = await agent_correction(
                            requirements, components,
                            calc_failures, drc_violations,
                            rail_assignments, api_key
                        )
                        corrected = correction.get("corrected_rails", [])
                        if corrected:
                            # Fuzzy rail merge: normalize names before matching
                            def _norm(s): return re.sub(r'[^a-z0-9]', '', s.lower())
                            rail_map = {_norm(r["rail"]): r for r in rail_assignments}
                            changes  = []
                            for cr in corrected:
                                key = _norm(cr.get("rail", ""))
                                if key in rail_map:
                                    changes.append(f"{cr['rail']}: {cr.get('change_reason','replaced')}")
                                    rail_map[key] = cr
                            scheme["rail_assignments"] = list(rail_map.values())
                            scheme["correction_log"]   = changes

                            # Re-run calculator with corrected components
                            scheme["rail_analysis"] = calculate_all_rails(
                                scheme["rail_assignments"], req_params
                            )
                            # Re-run DRC to confirm fixes
                            new_violations = run_drc(scheme["rail_assignments"], req_params)
                            scheme["drc_violations"] = new_violations
                            scheme["drc_summary"]    = drc_summary(new_violations)
                    except Exception as corr_err:
                        scheme["correction_log"] = [f"Correction agent error: {str(corr_err)}"]

            yield sse_event("progress", {"step": 6, "total": 6,
                "message": "✅ All checks complete. Building final report..."})

            # ── Final result ───────────────────────────────────────────────
            result = {
                "final_summary": agent2.get("final_summary", ""),
                "schemes":       schemes,
                "comparison":    compare_schemes(schemes),
            }
            yield sse_event("result", result)

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Export endpoint: reliable server-side download ───────────────────────────
@app.post("/api/export")
async def export_report(request: Request):
    """
    Receives raw HTML from the frontend and returns it as a proper
    file download with Content-Disposition headers — works in all browsers.
    """
    body = await request.body()
    html_content = body.decode('utf-8')
    return Response(
        content=html_content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="Power-Engineering-Report.html"',
            "Content-Type": "text/html; charset=utf-8",
        }
    )

# ── Static file serving ───────────────────────────────────────────────────────
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
