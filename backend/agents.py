"""
Phase 2 + Phase 3 Agent Orchestration
Agent 1: Component Selector
Agent 2: Topology Designer
Agent 3: Schematic Generator
Agent 1b: Correction Agent (Phase 3 - feedback loop)
"""
import json
import asyncio
from openai import AsyncOpenAI


def _make_client(api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

HEADERS = {
    "HTTP-Referer": "http://localhost:8001",
    "X-Title": "Power Scheme Generator",
}

SYS_JSON = "You output strictly valid JSON only. No markdown fences, no comments, no trailing commas."


async def _llm(client, prompt: str, max_tokens: int = 4000) -> str:
    """Single LLM call with 180s timeout, returns raw text."""
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="openrouter/auto",
                messages=[
                    {"role": "system", "content": SYS_JSON},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=max_tokens,
                extra_headers=HEADERS,
            ),
            timeout=180.0,
        )
        return resp.choices[0].message.content
    except asyncio.TimeoutError:
        raise RuntimeError("LLM call timed out after 180s. OpenRouter may be slow — please retry.")


def _extract_json(text: str):
    """Robustly pull the first JSON object or array from LLM text."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith('```'):
        text = '\n'.join(text.split('\n')[1:])
        text = text.rstrip('`').strip()
    # Try object first, then array
    for open_c, close_c in [('{', '}'), ('[', ']')]:
        s = text.find(open_c)
        e = text.rfind(close_c)
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(text[s:e+1])
            except json.JSONDecodeError as je:
                continue
    raise ValueError(f"LLM returned non-JSON. First 300 chars: {text[:300]}")


# ── Smart DB Filter (Phase 3) ─────────────────────────────────────────────────
def filter_components(components: list, category: str = None, min_current: float = 0) -> list:
    """
    Filter component list before sending to LLM to reduce token usage.
    category: 'Buck Converter' or 'LDO'
    min_current: minimum current from summary (heuristic match)
    """
    filtered = []
    for c in components:
        cat = (c.get("category") or "").lower()
        if category and category.lower() not in cat:
            continue
        filtered.append({
            "part_name": c["part_name"],
            "category":  c["category"],
            "price":     c["price"],
            "summary":   c["summary"]
        })
    return filtered if filtered else [{"part_name": c["part_name"], "category": c["category"],
                                       "price": c["price"], "summary": c["summary"]} for c in components]


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — Component Selector
# ─────────────────────────────────────────────────────────────────────────────
async def agent_component_selector(requirements: str, components: list, api_key: str) -> dict:
    """Returns 3 schemes, each with component_selections per rail."""
    bucks = filter_components(components, category="Buck")
    ldos  = filter_components(components, category="LDO")
    comp_summary = json.dumps(bucks + ldos, indent=2)

    prompt = f"""
You are a power electronics component selection expert.

USER REQUIREMENTS:
{requirements}

AVAILABLE COMPONENTS (Bucks first, then LDOs):
{comp_summary}

SELECTION RULES:
1. Apply 1.5-1.75x current derating — selected component I_max must be >= 1.5 * I_load.
2. Buck converters are SINGLE-OUTPUT. One Buck per voltage level.
3. LDO input must come from an existing Buck output rail. Choose LDO with lowest dropout voltage.
4. Provide EXACTLY 3 different scheme options. Vary topology: more Bucks vs more LDOs, high-efficiency vs low-cost vs best thermal.
5. Include indirect load currents: if a Buck feeds LDOs, add all LDO load currents to the Buck's required current.

Return ONLY valid JSON:
{{
  "schemes": [
    {{
      "scheme_name": "Scheme 1: <descriptive name>",
      "rationale": "Why this topology was chosen",
      "total_price": 0.0,
      "component_selections": [
        {{
          "rail": "V1 (3.3V @ 6A)",
          "v_out": 3.3,
          "i_out_load": 6.0,
          "i_out_total": 6.0,
          "comp_type": "buck",
          "component": "LTM4638",
          "price": 0.0,
          "reasoning": "Handles 6A with 1.75x derating (spec 10A). Best efficiency."
        }}
      ]
    }}
  ]
}}
"""
    client = _make_client(api_key)
    raw = await _llm(client, prompt)
    return _extract_json(raw)


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — Topology Designer
# ─────────────────────────────────────────────────────────────────────────────
async def agent_topology_designer(requirements: str, agent1_result: dict, api_key: str) -> dict:
    """Returns rail_assignments with v_in, upstream_component, switching_frequency."""
    schemes_summary = json.dumps(agent1_result["schemes"], indent=2)

    prompt = f"""
You are a power distribution topology expert.

USER REQUIREMENTS:
{requirements}

COMPONENT SELECTIONS (from previous analysis):
{schemes_summary}

TOPOLOGY RULES:
1. Each Buck takes its input directly from the main supply (Vin from requirements).
2. Each LDO must take its input from one of the Buck output rails — choose the closest higher voltage rail that satisfies the dropout voltage.
3. The "upstream_component" for an LDO = the part_name of the Buck feeding it.
4. Assign switching_frequency from datasheet: LTM4638=1MHz, LTM4622=1.5MHz, LTM4630=800kHz, LTM4650=600kHz, LTM4655=1MHz, LTM4671=1MHz, LTM4675=800kHz, LTM4680=500kHz, TPSM82866A=2.2MHz. Default=1MHz.
5. LDOs have no switching frequency — use the upstream Buck's frequency.
6. Generate a concise "final_summary" comparing all 3 schemes.

Return ONLY valid JSON:
{{
  "final_summary": "Comprehensive comparison of all 3 schemes: cost, topology, efficiency trade-offs.",
  "schemes": [
    {{
      "scheme_name": "Scheme 1: <name>",
      "switching_frequency": "1MHz",
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
      ]
    }}
  ]
}}
"""
    client = _make_client(api_key)
    raw = await _llm(client, prompt)
    return _extract_json(raw)


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 3 — Schematic Generator
# ─────────────────────────────────────────────────────────────────────────────
async def agent_schematic_generator(schemes: list, api_key: str) -> list:
    """Returns list of mermaid code strings, one per scheme."""
    schemes_summary = json.dumps([
        {"scheme_name": s["scheme_name"], "rail_assignments": s.get("rail_assignments", [])}
        for s in schemes
    ], indent=2)

    prompt = f"""
You are a Mermaid diagram expert for power electronics.

Generate one Mermaid flowchart per power scheme for these designs:
{schemes_summary}

STRICT MERMAID SYNTAX RULES — violating any of these causes a blank diagram:
1. ALWAYS start with exactly: graph TD
2. Node IDs: ONLY letters and numbers, NO spaces, NO hyphens, NO underscores (use VIN, BUCK1, LDO1, RAIL1, etc.)
3. Node labels: ALWAYS wrap in square brackets with quotes if special chars exist: A["LTM4638\\n10A Buck"]
4. Edge labels: Use ---->|label| format, label must NOT contain parentheses
5. NO semicolons at end of lines
6. NO subgraph blocks (causes rendering issues)
7. Every line must be a valid edge definition: NodeA -->|label| NodeB
8. Use \\n inside quoted labels for multi-line, not actual newlines

VALID EXAMPLE (use this exact pattern):
graph TD
    VIN["12V Input"] -->|"12V"| BUCK1["LTM4638\\nBuck 10A"]
    VIN -->|"12V"| BUCK2["LTM4630\\nBuck 15A"]
    BUCK1 -->|"3.3V 6A"| RAIL1["3.3V Rail"]
    BUCK1 -->|"1.8V 2A"| LDO1["ADP1763\\nLDO 1A"]
    BUCK2 -->|"1.0V 4A"| RAIL2["1.0V Rail"]
    LDO1 -->|"1.8V 2A"| RAIL3["1.8V Rail"]

Return ONLY valid JSON (no markdown fences, no comments):
{{
  "schematics": [
    "graph TD\\n    VIN[\\"12V Input\\"] -->|\\"12V\\"| BUCK1[\\"LTM4638\\"]\\n    BUCK1 -->|\\"3.3V 6A\\"| R1[\\"3.3V Rail\\"]",
    "graph TD\\n    ...",
    "graph TD\\n    ..."
  ]
}}
"""
    client = _make_client(api_key)
    raw = await _llm(client, prompt)
    data = _extract_json(raw)
    schematics = data.get("schematics", [])
    while len(schematics) < len(schemes):
        schematics.append("graph TD\n    VIN[\"12V Input\"] -->|\"12V\"| OUT[\"Output Rail\"]")
    return schematics


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1b — Correction Agent  (Phase 3 — Feedback Loop)
# Task: Given specific failed rails, select better replacement components.
# ─────────────────────────────────────────────────────────────────────────────
async def agent_correction(requirements: str, components: list,
                            failures: list, drc_violations: list,
                            original_assignments: list, api_key: str) -> dict:
    """
    Selects replacement components for failed/violated rails only.
    Returns updated_rail_assignments (only the corrected ones).
    """
    issues = failures + drc_violations
    issues_json = json.dumps(issues, indent=2)

    # Only send the FAILED rails (not all assignments) to reduce input tokens
    failed_rail_names = set(i.get("rail", "") for i in issues)
    failed_assignments = [r for r in original_assignments if r.get("rail") in failed_rail_names]
    if not failed_assignments:
        failed_assignments = original_assignments[:3]  # fallback: send first 3
    original_json = json.dumps(failed_assignments, indent=2)

    # Detect types needed and filter components to only relevant category
    needs_buck = any(r.get("comp_type","buck").lower()=="buck" for r in failed_assignments)
    needs_ldo  = any(r.get("comp_type","").lower()=="ldo"  for r in failed_assignments)
    filtered = [c for c in components if
        (needs_buck and c.get("category","").lower()=="buck") or
        (needs_ldo  and c.get("category","").lower()=="ldo")]
    if not filtered:
        filtered = components[:20]

    comp_summary = json.dumps([
        {"part_name": c["part_name"], "category": c["category"],
         "price": c["price"], "summary": c.get("summary","")[:80]}
        for c in filtered[:25]   # hard cap at 25 components
    ], indent=2)

    prompt = f"""You are a power electronics remediation expert.

REQUIREMENTS (brief): {requirements[:300]}

FAILED RAILS ONLY:
{original_json}

FAILURES & DRC VIOLATIONS:
{issues_json}

AVAILABLE REPLACEMENTS (relevant category only):
{comp_summary}

Fix ONLY the failed rails above. For each failed rail pick a better component.
Rules: Thermal Fail→lower Rthja, Ripple Fail→higher freq/cap, PSRR Fail→higher PSRR, Derating→higher I_max, LDO Dropout→lower Vdo.

Return ONLY valid JSON:
{{
  "corrected_rails": [
    {{
      "rail": "V1 (3.3V @ 6A)",
      "v_out": 3.3,
      "i_out": 6.0,
      "v_in": 12.0,
      "component": "LTM4655",
      "comp_type": "buck",
      "upstream_component": "",
      "change_reason": "Replaced due to thermal fail — LTM4655 has lower Rthja"
    }}
  ]
}}"""
    client = _make_client(api_key)
    raw = await _llm(client, prompt, max_tokens=2000)
    return _extract_json(raw)


