"""
Scheme Comparison Metrics Calculator
Computes PCB area, BOM count, thermal extremes, DRC status from scheme data.
All Python — no LLM involvement.
"""
from backend.calculator import resolve_spec

# ── Package footprint areas from datasheets (mm²) ────────────────────────────
PKG_AREA = {
    "LTM4638":    225,   # 15×15 BGA
    "LTM4622":    144,   # 12×12 BGA
    "LTM4622IV":  144,
    "LTM4630":    256,   # 16×16 BGA
    "LTM4630A":   256,
    "LTM4650":    400,   # 20×20 BGA
    "LTM4650-1":  400,
    "LTM4655":    256,
    "LTM4671":    144,
    "LTM4675":    256,
    "LTM4676A":   256,
    "LTM4680":    324,   # 18×18 BGA
    "LTM4700":    625,   # 25×25 BGA
    "LTM4705":    625,
    "TPSM82866A": 35,    # 5×7 QFN
    "LTM8067FC":  100,   # 10×10 BGA
    "LT3070":     25,    # 4×4 QFN
    "ADP1763":    9,     # 3×3 LFCSP
    "ADP7159":    9,     # 3×3 LFCSP
    "TPS737":     6.5,   # SOT-23-5
    "TPS73701DCQ":25,    # TO-252
    "TPS7A85A":   16,    # 4×4 QFN
}


def _pkg_area(comp: str, ctype: str) -> float:
    u = comp.upper().replace("-", "")
    for k, v in PKG_AREA.items():
        if k.upper().replace("-", "") == u:
            return v
    for k, v in PKG_AREA.items():
        if k.upper().replace("-", "") in u:
            return v
    return 225 if ctype == "buck" else 16


def compute_metrics(scheme: dict) -> dict:
    """
    Derives all comparison metrics from a fully-computed scheme dict.
    Returns a flat metrics dict ready for the comparison table.
    """
    assignments = scheme.get("rail_assignments", [])
    analysis    = scheme.get("rail_analysis", [])

    # ── Component counts ──────────────────────────────────────────────────────
    # Count physical components by unique (component, instance_num) pairs
    buck_instances = set()  # (component, instance_num) for Bucks
    ldo_instances = set()   # (component, instance_num) for LDOs

    for r in assignments:
        comp = r.get("component", "")
        ctype = r.get("comp_type", "buck")
        instance_num = r.get("instance_num", 1)

        if ctype == "buck":
            buck_instances.add((comp, instance_num))
        else:
            ldo_instances.add((comp, instance_num))

    num_bucks = len(buck_instances)
    num_ldos = len(ldo_instances)
    num_rails = len(assignments)

    # ── PCB area estimate ─────────────────────────────────────────────────────
    # IC footprints + 40% routing / decoupling margin + 5×5mm guard ring
    # Count per physical component instance
    ic_area = 0
    for (comp, instance_num) in buck_instances:
        ic_area += _pkg_area(comp, "buck")
    for (comp, instance_num) in ldo_instances:
        ic_area += _pkg_area(comp, "ldo")
    pcb_area = round(ic_area * 1.4 + 25)   # mm²

    # ── Passive BOM count ─────────────────────────────────────────────────────
    total_caps       = 0
    total_inductors  = 0

    # Count caps per physical instance
    for (comp, inst) in buck_instances:
        spec = resolve_spec(comp)
        c_out_uf        = spec.get("c_out_uf", 47)
        # Output caps: assume 22µF ceramic units per package
        n_out_caps      = max(2, round(c_out_uf / 22))
        # Input caps: 2 bulk ceramics per buck package
        n_in_caps       = 2
        total_caps      += (n_out_caps + n_in_caps)
        # LTM µModules have integrated inductors — 0 external
        total_inductors += 0

    for (comp, inst) in ldo_instances:
        # LDO: 1 input + 1 output ceramic cap each
        total_caps += 2

    # Feedback resistors: 2 per rail
    total_resistors = num_rails * 2

    # Bootstrap / enable / SS resistors: ~1 per buck package
    total_resistors += num_bucks

    # ── Thermal extremes from calculator output ───────────────────────────────
    tj_values = []
    for r in analysis:
        val_str = r.get("thermal", {}).get("value", "")
        try:
            tj_values.append(float(val_str.replace("°C","").replace("C","").strip()))
        except Exception:
            pass

    tj_min = round(min(tj_values), 1) if tj_values else None
    tj_max = round(max(tj_values), 1) if tj_values else None

    # ── DRC status ────────────────────────────────────────────────────────────
    drc = scheme.get("drc_violations", [])
    drc_errors   = sum(1 for v in drc if v.get("severity") == "ERROR")
    drc_warnings = sum(1 for v in drc if v.get("severity") == "WARNING")

    # ── Efficiency estimate (weighted average from calculator specs) ──────────
    eff_values = []
    for r in assignments:
        spec = resolve_spec(r.get("component",""))
        if spec.get("type") == "buck":
            eff_values.append(spec.get("eta", 0.88) * 100)
    avg_eff = round(sum(eff_values) / len(eff_values), 1) if eff_values else None

    # ── Correction log ────────────────────────────────────────────────────────
    corrections = len(scheme.get("correction_log", []))

    return {
        "scheme_name":     scheme.get("scheme_name", ""),
        "total_price":     scheme.get("total_price", 0),
        "num_bucks":       num_bucks,
        "num_ldos":        num_ldos,
        "num_rails":       num_rails,
        "pcb_area_mm2":    pcb_area,
        "total_caps":      total_caps,
        "total_resistors": total_resistors,
        "total_inductors": total_inductors,
        "total_passives":  total_caps + total_resistors + total_inductors,
        "tj_min_c":        tj_min,
        "tj_max_c":        tj_max,
        "avg_efficiency":  avg_eff,
        "drc_errors":      drc_errors,
        "drc_warnings":    drc_warnings,
        "corrections":     corrections,
        "switching_freq":  scheme.get("switching_frequency", "N/A"),
    }


def compare_schemes(schemes: list) -> list:
    """Returns list of metric dicts, one per scheme, for the comparison table."""
    return [compute_metrics(s) for s in schemes]
