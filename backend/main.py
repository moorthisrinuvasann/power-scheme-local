import json
import re
import sqlite3
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from typing import List, Dict, Any
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


def generate_mermaid_from_rails(rail_assignments: List[Dict[str, Any]]) -> str:
    """
    Generate a Mermaid flowchart from rail assignments.
    Handles multi-output Buck converters by grouping channels under one component node.
    Handles multiple instances of the same component (e.g., LTM4638-1, LTM4638-2).
    """
    lines = ["graph TD"]
    lines.append('    VIN["VIN Input"]')

    # First pass: group rails by (component, instance_num) for proper node creation
    comp_instance_groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for ra in rail_assignments or []:
        comp = ra.get("component", "IC")
        instance_num = ra.get("instance_num", 1)
        key = (comp, instance_num)
        if key not in comp_instance_groups:
            comp_instance_groups[key] = []
        comp_instance_groups[key].append(ra)

    node_map: Dict[str, str] = {}  # rail_name -> node_id
    comp_instance_node_map: Dict[tuple, str] = {}  # (component, instance_num) -> node_id
    node_idx = 0

    # Second pass: create nodes
    for ra in rail_assignments or []:
        comp = re.sub(r'[^A-Za-z0-9]', '', ra.get("component", "IC"))
        rail = re.sub(r'[^A-Za-z0-9\s\.]', '', ra.get("rail", "Rail")).strip()
        vout = ra.get("v_out", "?")
        iout = ra.get("i_out", "?")
        ctype = (ra.get("comp_type", "") or "").lower()
        channels = ra.get("channels", 1)
        instance_num = ra.get("instance_num", 1)

        key = (comp, instance_num)

        # Create one node per (component, instance) pair
        if key not in comp_instance_node_map:
            comp_instance_node_map[key] = f"COMP{node_idx}"
            node_idx += 1

        node_id = comp_instance_node_map[key]
        node_map[ra.get("rail", "")] = node_id

        # Build label based on component type and channels
        if channels > 1 and ctype == "buck":
            # Multi-output Buck: show all channel outputs for this instance
            comp_data = comp_instance_groups[key]
            outputs = [f"{r.get('v_out', '?')}V/{r.get('i_out', '?')}A" for r in comp_data]
            label = f"{comp}-{instance_num}\\\\n{len(comp_data)}-Channel Buck\\\\n" + " + ".join(outputs)
        elif ctype == "buck":
            # Single-output Buck
            label = f"{comp}-{instance_num}\\\\nBuck\\\\n{vout}V/{iout}A"
        else:
            # LDO
            label = f"{comp}-{instance_num}\\\\nLDO\\\\n{vout}V/{iout}A"

        upstream = ra.get("upstream_component", "")
        src = "VIN"

        # If LDO with upstream, find its node
        if ctype == "ldo" and upstream:
            v_in = ra.get("v_in", 12)
            # Find the Buck rail that provides the LDO's input voltage
            for ra2 in rail_assignments or []:
                if ra2.get("component") == upstream:
                    # Check if this Buck's output voltage matches the LDO's input voltage
                    if abs(float(ra2.get("v_out", 0)) - v_in) < 0.1:
                        upstream_instance = ra2.get("instance_num", 1)
                        upstream_key = (upstream, upstream_instance)
                        if upstream_key in comp_instance_node_map:
                            src = comp_instance_node_map[upstream_key]
                            break
            # If no matching Buck found, LDO connects to VIN directly

        # Connect component to rail
        lines.append(f'    {src} -->|"{vout}V {iout}A"| {node_id}["{label}"]')

    if len(lines) == 2:
        lines.append('    VIN -->|"12V"| OUT["Output Rails"]')

    return "\n".join(lines)

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
        return "Requirements text is too short. Please describe your power supply needs."
    # Just check there's at least one number in the text — the LLM handles the rest
    if not re.search(r'\d', text):
        return "No numeric values found in requirements. Please include voltages and currents (e.g. 3.3V, 2A)."
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

                # Add instance numbers and channel info to rail assignments
                # Group by component to assign instance numbers correctly
                from collections import defaultdict
                from backend.calculator import COMPONENT_SPECS
                comp_instance_map: Dict[str, int] = {}  # (comp, type) -> current instance number
                comp_channel_index: Dict[str, int] = {}  # (comp, type) -> next channel index (0-based)

                for ra in rail_assignments:
                    comp = ra.get("component", "")
                    ctype = ra.get("comp_type", "buck")

                    # Look up channels from COMPONENT_SPECS for both Buck and LDO
                    channels = ra.get("channels", 1)
                    # Try to get from COMPONENT_SPECS
                    spec = COMPONENT_SPECS.get(comp, {})
                    if not spec:
                        # Fuzzy match
                        for k, v in COMPONENT_SPECS.items():
                            if k.upper().replace("-", "") == comp.upper().replace("-", ""):
                                spec = v
                                break
                    if spec:
                        channels = spec.get("channels", 1)
                        ra["channels"] = channels

                    key = (comp, ctype)
                    if key not in comp_instance_map:
                        comp_instance_map[key] = 1
                        comp_channel_index[key] = 0  # Start channel index at 0 for new instance
                    ra["instance_num"] = comp_instance_map[key]
                    ra["channel_index"] = comp_channel_index[key]  # Override LLM's channel_index
                    comp_channel_index[key] += 1  # Increment for next rail with same component
                    ra["component_display"] = f"{comp}-{comp_instance_map[key]}"

                    # Only increment instance number for single-output
                    if channels == 1:
                        comp_instance_map[key] += 1
                    # For multi-output, all channels share the same instance number

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
                    # Save BEFORE-correction state for comparison
                    scheme["before_correction"] = {
                        "rail_assignments": rail_assignments,
                        "rail_analysis": scheme.get("rail_analysis", []),
                        "drc_violations": drc_violations,
                        "drc_summary": drc_summary(drc_violations),
                    }

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
                                    # Preserve instance number from original rail
                                    cr["instance_num"] = rail_map[key].get("instance_num", 1)
                                    cr["component_display"] = rail_map[key].get("component_display", cr.get("component", ""))
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

                            # Generate BEFORE-correction Mermaid diagram
                            before_mermaid = generate_mermaid_from_rails(
                                scheme["before_correction"]["rail_assignments"]
                            )
                            scheme["before_correction"]["schematics_mermaid"] = before_mermaid
                    except Exception as corr_err:
                        import traceback
                        err_msg = f"Correction agent error: {str(corr_err)}"
                        tb = traceback.format_exc().replace('\n', ' | ').replace('<', '[').replace('>', ']')
                        scheme["correction_log"] = [f"{err_msg} | {tb}"]

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
            yield sse_event("error", {"message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Phase 4: Step 1 — Design endpoint (Agents 1-3 only) ─────────────────────
@app.post("/api/design")
async def design_scheme(file: UploadFile = File(...), api_key: str = Form(...)):
    """Runs Agents 1-3 and returns intermediate design for human override."""
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is required.")
    try:
        content = await file.read()
        requirements = content.decode('utf-8')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {e}")

    err = validate_requirements(requirements)
    if err:
        raise HTTPException(status_code=422, detail=err)

    components = get_all_components()

    async def stream():
        try:
            yield sse_event("progress", {"step": 1, "total": 3,
                "message": "Agent 1/3: Selecting optimal components for each rail..."})

            agent1 = await agent_component_selector(requirements, components, api_key)

            yield sse_event("progress", {"step": 1, "total": 3,
                "message": f"Agent 1 done — {len(agent1.get('schemes', []))} schemes selected."})

            yield sse_event("progress", {"step": 2, "total": 3,
                "message": "Agent 2/3: Designing power distribution topology..."})

            agent2 = await agent_topology_designer(requirements, agent1, api_key)

            yield sse_event("progress", {"step": 2, "total": 3,
                "message": "Agent 2 done — topology finalized."})

            yield sse_event("progress", {"step": 3, "total": 3,
                "message": "Agent 3/3: Generating schematics..."})

            schemes = agent2.get("schemes", [])
            mermaid_codes = await agent_schematic_generator(schemes, api_key)

            # Merge Agent 1 component data + schematics into schemes
            agent1_schemes = agent1.get("schemes", [])
            for i, scheme in enumerate(schemes):
                scheme["schematics_mermaid"] = mermaid_codes[i] if i < len(mermaid_codes) else ""

                # Add instance numbers and channel info to rail assignments
                from collections import defaultdict
                comp_instance_map: Dict[str, int] = {}

                rail_assignments = scheme.get("rail_assignments", [])
                for ra in rail_assignments:
                    comp = ra.get("component", "")
                    ctype = ra.get("comp_type", "buck")
                    channels = ra.get("channels", 1)
                    # Look up channels from COMPONENT_SPECS
                    spec = COMPONENT_SPECS.get(comp, {})
                    if spec:
                        channels = spec.get("channels", 1)
                        ra["channels"] = channels

                    key = (comp, ctype)
                    if key not in comp_instance_map:
                        comp_instance_map[key] = 1
                    ra["instance_num"] = comp_instance_map[key]
                    ra["component_display"] = f"{comp}-{comp_instance_map[key]}"

                    if channels == 1:
                        comp_instance_map[key] += 1

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

            yield sse_event("progress", {"step": 3, "total": 3,
                "message": "✅ Agent 3 done — ready for component review."})

            yield sse_event("design_complete", {
                "requirements": requirements,
                "final_summary": agent2.get("final_summary", ""),
                "schemes": schemes,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Phase 4: Step 2 — Analyze endpoint (Calculator + DRC + Compare) ──────────
@app.post("/api/analyze")
async def analyze_scheme(request: Request):
    """Runs Calculator, DRC, Correction Agent and Comparator on (possibly modified) schemes."""
    body = await request.json()
    requirements = body.get("requirements", "")
    schemes      = body.get("schemes", [])
    api_key      = body.get("api_key", "")

    if not api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is required.")
    if not schemes:
        raise HTTPException(status_code=400, detail="No schemes provided.")

    req_params = parse_requirements(requirements)
    components = get_all_components()

    async def stream():
        try:
            yield sse_event("progress", {"step": 1, "total": 3,
                "message": "🧮 Running engineering calculator (ripple / PSRR / thermal / derating)..."})

            for scheme in schemes:
                rail_assignments = scheme.get("rail_assignments", [])

                # Add instance numbers and channel info to rail assignments
                from collections import defaultdict
                comp_instance_map: Dict[str, int] = {}

                for ra in rail_assignments:
                    comp = ra.get("component", "")
                    ctype = ra.get("comp_type", "buck")
                    channels = ra.get("channels", 1)
                    # Look up channels from COMPONENT_SPECS
                    spec = COMPONENT_SPECS.get(comp, {})
                    if spec:
                        channels = spec.get("channels", 1)
                        ra["channels"] = channels

                    key = (comp, ctype)
                    if key not in comp_instance_map:
                        comp_instance_map[key] = 1
                    ra["instance_num"] = comp_instance_map[key]
                    ra["component_display"] = f"{comp}-{comp_instance_map[key]}"

                    if channels == 1:
                        comp_instance_map[key] += 1

                scheme["rail_analysis"] = calculate_all_rails(rail_assignments, req_params)

            yield sse_event("progress", {"step": 2, "total": 3,
                "message": "🔬 Running Design Rule Check (DRC)..."})

            for scheme in schemes:
                rail_assignments = scheme.get("rail_assignments", [])
                drc_violations   = run_drc(rail_assignments, req_params)
                calc_failures    = check_calc_failures(scheme.get("rail_analysis", []))
                scheme["drc_violations"] = drc_violations
                scheme["drc_summary"]    = drc_summary(drc_violations)

                all_issues = drc_violations + calc_failures
                if all_issues:
                    # Save BEFORE-correction state for comparison
                    scheme["before_correction"] = {
                        "rail_assignments": rail_assignments,
                        "rail_analysis": scheme.get("rail_analysis", []),
                        "drc_violations": drc_violations,
                        "drc_summary": drc_summary(drc_violations),
                    }

                    yield sse_event("progress", {"step": 2, "total": 3,
                        "message": f"⚠️ {len(all_issues)} issue(s) in '{scheme.get('scheme_name','')}'. Running correction agent..."})
                    try:
                        correction = await agent_correction(
                            requirements, components,
                            calc_failures, drc_violations,
                            rail_assignments, api_key
                        )
                        corrected = correction.get("corrected_rails", [])
                        if corrected:
                            def _norm(s): return re.sub(r'[^a-z0-9]', '', s.lower())
                            rail_map = {_norm(r["rail"]): r for r in rail_assignments}
                            changes  = []
                            for cr in corrected:
                                key = _norm(cr.get("rail", ""))
                                if key in rail_map:
                                    changes.append(f"{cr['rail']}: {cr.get('change_reason','replaced')}")
                                    # Preserve instance number from original rail
                                    cr["instance_num"] = rail_map[key].get("instance_num", 1)
                                    cr["component_display"] = rail_map[key].get("component_display", cr.get("component", ""))
                                    rail_map[key] = cr
                            scheme["rail_assignments"] = list(rail_map.values())
                            scheme["correction_log"]   = changes

                            # Re-assign instance numbers after correction
                            comp_instance_map: Dict[str, int] = {}
                            for ra in scheme["rail_assignments"]:
                                comp = ra.get("component", "")
                                ctype = ra.get("comp_type", "buck")
                                channels = ra.get("channels", 1)
                                # Look up channels from COMPONENT_SPECS
                                spec = COMPONENT_SPECS.get(comp, {})
                                if spec:
                                    channels = spec.get("channels", 1)
                                    ra["channels"] = channels
                                key = (comp, ctype)
                                if key not in comp_instance_map:
                                    comp_instance_map[key] = 1
                                ra["instance_num"] = comp_instance_map[key]
                                ra["component_display"] = f"{comp}-{comp_instance_map[key]}"
                                if channels == 1:
                                    comp_instance_map[key] += 1

                            scheme["rail_analysis"]    = calculate_all_rails(scheme["rail_assignments"], req_params)
                            new_v = run_drc(scheme["rail_assignments"], req_params)
                            scheme["drc_violations"]   = new_v
                            scheme["drc_summary"]      = drc_summary(new_v)

                            # Generate BEFORE-correction Mermaid diagram
                            before_mermaid = generate_mermaid_from_rails(
                                scheme["before_correction"]["rail_assignments"]
                            )
                            scheme["before_correction"]["schematics_mermaid"] = before_mermaid
                    except Exception as corr_err:
                        import traceback
                        err_msg = f"Correction agent error: {str(corr_err)}"
                        tb = traceback.format_exc().replace('\n', ' | ').replace('<', '[').replace('>', ']')
                        scheme["correction_log"] = [f"{err_msg} | {tb}"]

            yield sse_event("progress", {"step": 3, "total": 3,
                "message": "✅ All checks complete. Building final report..."})

            result = {
                "final_summary": body.get("final_summary", ""),
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
