"""
Phase 2 Agent Orchestration
Three specialized LLM agents, each with a narrow focused task.
"""
import json
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


async def _llm(client, prompt: str) -> str:
    """Single LLM call, returns raw text."""
    resp = await client.chat.completions.create(
        model="openrouter/auto",
        messages=[
            {"role": "system", "content": SYS_JSON},
            {"role": "user",   "content": prompt},
        ],
        extra_headers=HEADERS,
    )
    return resp.choices[0].message.content


def _extract_json(text: str) -> dict:
    """Robustly pull the first JSON object from LLM text."""
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1:
        raise ValueError(f"No JSON found in response: {text[:200]}")
    return json.loads(text[s:e+1])


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — Component Selector
# Task: For each of 3 scheme options, pick the best Buck/LDO per rail.
# ─────────────────────────────────────────────────────────────────────────────
async def agent_component_selector(requirements: str, components: list, api_key: str) -> dict:
    """
    Returns 3 schemes, each with component_selections per rail.
    """
    comp_summary = json.dumps([
        {"part_name": c["part_name"], "category": c["category"],
         "price": c["price"], "summary": c["summary"]}
        for c in components
    ], indent=2)

    prompt = f"""
You are a power electronics component selection expert.

USER REQUIREMENTS:
{requirements}

AVAILABLE COMPONENTS:
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
# Task: Given the selected components, design the power distribution tree.
#        Assign v_in for each rail and identify upstream components for LDOs.
# ─────────────────────────────────────────────────────────────────────────────
async def agent_topology_designer(requirements: str, agent1_result: dict, api_key: str) -> dict:
    """
    Returns rail_assignments with v_in, upstream_component, and switching_frequency.
    """
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
# Task: ONLY generate Mermaid diagram code — nothing else.
# ─────────────────────────────────────────────────────────────────────────────
async def agent_schematic_generator(schemes: list, api_key: str) -> list:
    """
    Returns list of mermaid code strings, one per scheme.
    Generates all 3 schematics in a single focused LLM call.
    """
    schemes_summary = json.dumps([
        {"scheme_name": s["scheme_name"], "rail_assignments": s.get("rail_assignments", [])}
        for s in schemes
    ], indent=2)

    prompt = f"""
You are a power electronics schematic expert specializing in Mermaid diagrams.

Generate Mermaid flow diagrams for these power schemes:
{schemes_summary}

DIAGRAM RULES:
1. Use exact IC part numbers as node labels, e.g.: A[LTM4638]
2. Show voltage levels on edges, e.g.: -->|3.3V 6A|
3. Start from Vin input node, flow through Bucks, then to LDOs, then to load labels.
4. Use "graph TD" (top-down) layout.
5. Use short unique node IDs (A, B, C, D...).
6. Escape special characters — no parentheses in node labels.
7. Each scheme must be a separate, complete, valid Mermaid string.

Return ONLY valid JSON (no markdown):
{{
  "schematics": [
    "graph TD\\n A[12V Input] --> B[LTM4638]\\n B -->|3.3V 6A| C[3.3V Rail]",
    "graph TD\\n ...",
    "graph TD\\n ..."
  ]
}}
"""
    client = _make_client(api_key)
    raw = await _llm(client, prompt)
    data = _extract_json(raw)
    schematics = data.get("schematics", [])
    # Pad with empty strings if LLM returned fewer than 3
    while len(schematics) < len(schemes):
        schematics.append("graph TD\n A[Input] --> B[Output]")
    return schematics
