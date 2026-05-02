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
        base_url="https://llmapi05.datapatterns.co.in",
        api_key=api_key,
    )

HEADERS = {
    "HTTP-Referer": "http://localhost:8001",
    "X-Title": "Power Scheme Generator",
}

SYS_JSON = "You output strictly valid JSON only. No markdown fences, no comments, no trailing commas."


async def _llm(client, prompt: str, max_tokens: int = 48000) -> str:
    """Single LLM call with 180s timeout, returns raw text."""
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="claude-sonnet-4-6",
                messages=[
                    {"role": "system", "content": SYS_JSON},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=max_tokens,
            ),
            timeout=180.0,
        )
        return resp.choices[0].message.content
    except asyncio.TimeoutError:
        raise RuntimeError("LLM call timed out after 180s.")


def _extract_json(text: str):
    """Robustly pull the first JSON object or array from LLM text."""
    import re
    original = text
    text = text.strip()

    # Strategy 1: strip ALL markdown fences (```json ... ``` or ``` ... ```)
    text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
    text = re.sub(r'\s*```$', '', text).strip()

    # Strategy 2: try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 3: find first { } or [ ] block by scanning
    for open_c, close_c in [('{', '}'), ('[', ']')]:
        s = text.find(open_c)
        if s == -1:
            continue
        # Walk forward to find matching close bracket
        depth = 0
        for i, ch in enumerate(text[s:], start=s):
            if ch == open_c:
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0:
                    candidate = text[s:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # malformed — try next strategy

    # Strategy 4: regex scan for json-like block
    m = re.search(r'(\{[\s\S]+\}|\[[\s\S]+\])', text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 5: Try to fix truncated JSON by closing unclosed braces
    # Find the start of JSON
    start = text.find('{')
    if start == -1:
        start = text.find('[')
    if start == -1:
        print(f"[WARN] _extract_json failed. No JSON found. Response preview: {original[:200]}")
        raise ValueError(f"LLM returned non-JSON. Response preview: {original[:200]}")

    # Try closing with increasing number of braces
    for close_str in ['}]', ']}', ']}', '}', ']']:
        candidate = text[start:] + close_str
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # Try finding the last valid JSON object by progressively truncating
    # Start from the end and work backwards to find a valid parse point
    # First, try larger steps to quickly find a valid closing point
    end = len(text)
    while end > start + 100:
        end -= 100  # Large steps first
        candidate = text[start:end]
        # Close any open braces
        open_braces = candidate.count('{') - candidate.count('}')
        open_brackets = candidate.count('[') - candidate.count(']')
        if open_braces >= 0 and open_brackets >= 0:
            candidate += '}' * open_braces + ']' * open_brackets
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # If large steps failed, try smaller steps for precision
    end = len(text)
    while end > start + 10:
        end -= 10  # Small steps for precision
        candidate = text[start:end]
        # Close any open braces
        open_braces = candidate.count('{') - candidate.count('}')
        open_brackets = candidate.count('[') - candidate.count(']')
        if open_braces >= 0 and open_brackets >= 0:
            candidate += '}' * open_braces + ']' * open_brackets
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Final fallback: find the last complete } or ] by scanning backwards
    # Look for pattern like "}}" or "]]" or "}," or "]," which indicate complete objects/arrays
    for i in range(len(text) - 2, start, -1):
        if text[i:i+2] in ['}]', ']}', '},', '],']:
            candidate = text[start:i+1]
            # Try to parse with minimal closing
            open_braces = candidate.count('{') - candidate.count('}')
            open_brackets = candidate.count('[') - candidate.count(']')
            if open_braces >= 0 and open_brackets >= 0:
                candidate += '}' * open_braces + ']' * open_brackets
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

    print(f"[WARN] _extract_json failed. Raw response (first 500 chars):\n{original[:500]}")
    print(f"[WARN] Response length: {len(original)} chars")
    raise ValueError(f"LLM returned non-JSON. Response preview: {original[:200]}")


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
        # Include channels info for Buck converters
        summary = c.get("summary", "")
        channels = c.get("channels", 1)
        if channels > 1:
            summary = f"MULTI-OUTPUT ({channels} channels). " + summary
        filtered.append({
            "part_name": c["part_name"],
            "category":  c["category"],
            "price":     c["price"],
            "summary":   summary,
            "channels":  channels
        })
    return filtered if filtered else [{"part_name": c["part_name"], "category": c["category"],
                                       "price": c["price"], "summary": c.get("summary",""), "channels": c.get("channels",1)} for c in components]


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
1. Apply 1.5-1.75x current derating — selected component I_max must be >= 1.5 * I_load per channel.
2. Most Buck converters are SINGLE-OUTPUT (one Buck per rail).
3. MULTI-OUTPUT BUCKS available: LTM4671 has 4 channels (quad-output), LTM4675, LTM4676A have 2 channels each.
   - CRITICAL: When using a multi-output Buck with N channels, assign ONE component to N rails.
   - Example (2-channel): If V1 (3.3V) and V2 (1.8V) both need Bucks, use ONE LTM4671 for BOTH rails.
   - Example (4-channel): If V1, V2, V3, V4 all need Bucks, use ONE LTM4671 for ALL FOUR rails.
   - The component_selections should have ONE entry with "rails": ["V1", "V2", ...] for multi-output.
   - Each channel can independently regulate different voltages.
   - This reduces BOM cost and PCB area.
   - Check the "channels" field in each component's summary for its output count.
4. LDO input must come from an existing Buck output rail. Choose LDO with lowest dropout voltage.
5. Provide EXACTLY 3 different scheme options. Vary topology: more Bucks vs more LDOs, high-efficiency vs low-cost vs best thermal.
6. Include indirect load currents: if a Buck feeds LDOs, add all LDO load currents to the Buck's required current.
7. RESPECT ANY USER-SPECIFIED CONSTRAINTS (e.g., "V7 must use LDO", "Use only ADI components", etc.) — these override default selection preferences.

Return ONLY valid JSON:
{{
  "schemes": [
    {{
      "scheme_name": "Scheme 1: <descriptive name>",
      "rationale": "Why this topology was chosen",
      "total_price": 0.0,
      "component_selections": [
        {{
          "rails": ["V1 (3.3V @ 6A)", "V2 (1.8V @ 4A)"],  // For multi-output: array of 2 rails
          "v_out": [3.3, 1.8],  // Array of voltages for multi-output
          "i_out_load": [6.0, 4.0],  // Array of loads for multi-output
          "i_out_total": [6.0, 4.0],  // Array of total currents (include LDO loads)
          "comp_type": "buck",
          "component": "LTM4671",  // Multi-output Buck (2 channels)
          "channels": 2,  // Number of channels used
          "price": 0.0,
          "reasoning": "LTM4671 dual-output Buck powers V1 and V2, reducing BOM cost."
        }},
        {{
          "rail": "V3 (5V @ 2A)",  // For single-output: single rail string
          "v_out": 5.0,
          "i_out_load": 2.0,
          "i_out_total": 2.0,
          "comp_type": "buck",
          "component": "LTM4638",
          "channels": 1,
          "price": 0.0,
          "reasoning": "Handles 2A with derating. Best efficiency."
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
    schemes_data = agent1_result.get("schemes", [])
    if not schemes_data:
        raise ValueError("Agent 1 did not return any schemes. Please retry.")
    schemes_summary = json.dumps(schemes_data, indent=2)

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
4. LDOs NEVER connect directly to VIN — always find a Buck output rail that provides the required input voltage.
4. Assign switching_frequency from datasheet: LTM4638=1MHz, LTM4622=1.5MHz, LTM4630=800kHz, LTM4650=600kHz, LTM4655=1MHz, LTM4671=1MHz, LTM4675=800kHz, LTM4680=500kHz, TPSM82866A=2.2MHz. Default=1MHz.
5. LDOs have no switching frequency — use the upstream Buck's frequency.
6. For MULTI-OUTPUT Buck converters (channels > 1):
   - Create ONE rail_assignment per OUTPUT channel, not per component.
   - Each channel gets its own rail with v_in from the same source.
   - The "component" field is the same for all channels of a multi-output Buck.
7. Generate a concise "final_summary" comparing all 3 schemes.
8. RESPECT USER CONSTRAINTS from requirements (e.g., "V7 must use LDO") — do not override component choices made by Agent 1 based on constraints.

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
          "component": "LTM4671",
          "comp_type": "buck",
          "channels": 2,
          "channel_index": 0,
          "upstream_component": ""
        }},
        {{
          "rail": "V2 (1.8V @ 0.5A)",
          "v_out": 1.8,
          "i_out": 0.5,
          "v_in": 12.0,
          "component": "LTM4671",
          "comp_type": "buck",
          "channels": 2,
          "channel_index": 1,
          "upstream_component": ""
        }},
        {{
          "rail": "V3 (5V @ 2A)",
          "v_out": 5.0,
          "i_out": 2.0,
          "v_in": 12.0,
          "component": "LTM4638",
          "comp_type": "buck",
          "channels": 1,
          "channel_index": 0,
          "upstream_component": ""
        }},
        {{
          "rail": "V4 (1.2V @ 1A)",
          "v_out": 1.2,
          "i_out": 1.0,
          "v_in": 3.3,
          "component": "TPS7A85A",
          "comp_type": "ldo",
          "channels": 1,
          "channel_index": 0,
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
    if not schemes:
        return []
    schemes_summary = json.dumps([
        {"scheme_name": s.get("scheme_name", "Scheme"), "rail_assignments": s.get("rail_assignments", [])}
        for s in schemes
    ], indent=2)

    prompt = f"""
You are a Mermaid diagram expert for power electronics.

Generate one Mermaid flowchart per power scheme for these designs:
{schemes_summary}

STRICT MERMAID SYNTAX RULES — violating any of these causes a blank diagram:
1. ALWAYS start with exactly: graph TD
2. Node IDs: ONLY letters and numbers, NO spaces, NO hyphens, NO underscores (use VIN, BUCK1, BUCK2, LDO1, LDO2, V1, V2, etc.)
3. Node labels: ALWAYS wrap in square brackets with quotes if special chars exist
4. Edge labels: Use ---->|label| format, label must NOT contain parentheses
5. NO semicolons at end of lines
6. NO subgraph blocks (causes rendering issues)
7. Every line must be a valid edge definition: NodeA -->|label| NodeB
8. Use \\n inside quoted labels for multi-line, not actual newlines
9. **COMPONENT NUMBERING**: Each component instance gets its own numbered node:
   - If LTM4638 is used for V3 and V4: show as "LTM4638-1" and "LTM4638-2" (separate nodes)
   - If LTM4622 is used for V1: show as "LTM4622-1"
   - **MULTI-OUTPUT BUCKS**: If LTM4671 (2 channels) powers V1 and V2:
     - Show as ONE node: "LTM4671-1\\n2-Channel Buck" with both outputs branching from it
     - The node shows all channel voltages: "3.3V/6A + 1.8V/0.5A"
   - Format: "PartName-1", "PartName-2", etc. for each instance

VALID EXAMPLE (single-output Bucks):
graph TD
    VIN["VIN: 12V Input"] -->|"12V"| BUCK1["LTM4622-1\\nBuck 5V"]
    VIN -->|"12V"| BUCK2["LTM4638-1\\nBuck 3.3V"]
    VIN -->|"12V"| BUCK3["LTM4638-2\\nBuck 1.8V"]
    BUCK1 -->|"5V 4A"| V1["V1: 5V @ 4A"]
    BUCK2 -->|"3.3V 6A"| V2["V2: 3.3V @ 6A"]
    BUCK3 -->|"1.8V 2A"| LDO1["TPS7A85A-1\\nLDO 1.2V"]
    LDO1 -->|"1.2V 1A"| V3["V3: 1.2V @ 1A"]

VALID EXAMPLE (multi-output Buck):
graph TD
    VIN["VIN: 12V Input"] -->|"12V"| BUCK1["LTM4671-1\\n2-Channel Buck"]
    VIN -->|"12V"| BUCK2["LTM4638-1\\nBuck 5V"]
    BUCK1 -->|"3.3V 6A"| V1["V1: 3.3V @ 6A"]
    BUCK1 -->|"1.8V 0.5A"| V2["V2: 1.8V @ 0.5A"]
    BUCK2 -->|"5V 4A"| V3["V3: 5V @ 4A"]

Return ONLY valid JSON (no markdown fences, no comments):
{{
  "schematics": [
    "graph TD\\n    VIN[\\"VIN: 12V Input\\"] -->|\\"12V\\"| BUCK1[\\"LTM4622-1\\"]\\n    BUCK1 -->|\\"5V 4A\\"| V1[\\"V1: 5V\\"]",
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
    raw = await _llm(client, prompt, max_tokens=8000)
    try:
        return _extract_json(raw)
    except ValueError:
        # Graceful fallback: return empty correction so pipeline continues
        print(f"[WARN] Correction agent returned non-JSON. Skipping correction.\nRaw: {raw[:300]}")
        return {"corrected_rails": []}


