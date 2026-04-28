"""
Design Rule Checker (DRC)
Validates power scheme rail assignments against hard engineering constraints.
No LLM involved — pure Python rule enforcement.
"""
from backend.calculator import resolve_spec


# ── Hard design rules ─────────────────────────────────────────────────────────
def run_drc(rail_assignments: list, req_params: dict) -> list:
    """
    Validates every rail against engineering constraints.
    Returns a list of violation dicts (empty = all pass).
    """
    violations = []

    for ra in rail_assignments:
        comp      = ra.get("component", "")
        spec      = resolve_spec(comp)
        v_in      = float(ra.get("v_in",  12.0))
        v_out     = float(ra.get("v_out",  3.3))
        i_out     = float(ra.get("i_out",  1.0))
        rail      = ra.get("rail", "Unknown Rail")
        ctype     = spec.get("type", "buck")
        i_max     = float(spec.get("i_max", 999))

        # ── Rule 1: Current derating (must be ≥ 1.5×) ──────────────────────
        derating = (i_max / i_out) if i_out > 0 else 999
        if derating < 1.5:
            violations.append({
                "rail":      rail,
                "component": comp,
                "rule":      "Current Derating",
                "severity":  "ERROR",
                "detail":    (f"Derating={derating:.2f}x (min 1.5x). "
                              f"{comp} I_max={i_max}A, I_load={i_out}A."),
                "fix":       f"Select component with I_max ≥ {i_out * 1.5:.1f} A"
            })

        # ── Rule 2: LDO dropout voltage ─────────────────────────────────────
        if ctype == "ldo":
            vdo      = float(spec.get("vdo", 0.5))
            headroom = v_in - v_out
            if headroom < vdo:
                violations.append({
                    "rail":      rail,
                    "component": comp,
                    "rule":      "LDO Dropout Violation",
                    "severity":  "ERROR",
                    "detail":    (f"Headroom={headroom:.3f}V < Vdo={vdo}V. "
                                  f"V_in={v_in}V, V_out={v_out}V."),
                    "fix":       f"Use LDO with Vdo < {headroom:.3f}V or raise input rail"
                })
            elif headroom < vdo * 1.2:
                violations.append({
                    "rail":      rail,
                    "component": comp,
                    "rule":      "LDO Dropout Marginal",
                    "severity":  "WARNING",
                    "detail":    (f"Headroom={headroom:.3f}V is within 20% of Vdo={vdo}V. "
                                  f"Risk of regulation loss over temperature."),
                    "fix":       "Add margin or select lower Vdo LDO"
                })

        # ── Rule 3: Buck input voltage range ─────────────────────────────────
        if ctype == "buck":
            vin_range = spec.get("vin_range", (0.0, 100.0))
            if v_in < vin_range[0]:
                violations.append({
                    "rail":      rail,
                    "component": comp,
                    "rule":      "Buck Vin Too Low",
                    "severity":  "ERROR",
                    "detail":    f"V_in={v_in}V < {comp} Vin_min={vin_range[0]}V",
                    "fix":       f"Raise Vin to ≥ {vin_range[0]}V or select different Buck"
                })
            elif v_in > vin_range[1]:
                violations.append({
                    "rail":      rail,
                    "component": comp,
                    "rule":      "Buck Vin Too High",
                    "severity":  "ERROR",
                    "detail":    f"V_in={v_in}V > {comp} Vin_max={vin_range[1]}V",
                    "fix":       f"Reduce Vin to ≤ {vin_range[1]}V or select different Buck"
                })

        # ── Rule 4: Output voltage sanity check ───────────────────────────────
        if v_out >= v_in:
            violations.append({
                "rail":      rail,
                "component": comp,
                "rule":      "Output Voltage Invalid",
                "severity":  "ERROR",
                "detail":    f"V_out={v_out}V >= V_in={v_in}V. Impossible for Buck/LDO.",
                "fix":       "Check voltage assignments — V_out must be < V_in"
            })

    return violations


# ── Check calculator results for failures ────────────────────────────────────
def check_calc_failures(rail_analysis: list) -> list:
    """
    Inspects Python calculator results for any Fail status.
    Returns list of failed rail dicts with severity field for frontend display.
    """
    failures = []
    for r in rail_analysis:
        for atype in ["ripple", "psrr", "thermal", "derating"]:
            data = r.get(atype, {})
            if str(data.get("status", "")).lower() == "fail":
                # Determine severity: derating/warning -> WARNING, others -> ERROR
                severity = "WARNING" if atype == "derating" else "ERROR"
                failures.append({
                    "rail":          r.get("rail", ""),
                    "component":     r.get("component", ""),
                    "analysis_type": atype,
                    "severity":      severity,
                    "value":         data.get("value", ""),
                    "calculation":   data.get("calculation", ""),
                    "rule":          f"{atype.capitalize()} Check",
                    "detail":        data.get("calculation", ""),
                    "fix":           _get_fix_hint(atype, r, data),
                })
    return failures


def _get_fix_hint(atype: str, rail: dict, data: dict) -> str:
    """Generate a fix hint for calculator failures."""
    comp = rail.get("component", "")
    if atype == "thermal":
        return f"Select component with lower Rθja or reduce power dissipation"
    elif atype == "ripple":
        return f"Increase output capacitance or use lower ESR capacitors"
    elif atype == "psrr":
        return f"Use LDO with higher PSRR or add additional filtering"
    elif atype == "derating":
        return f"Select component with higher I_max (need ≥ {rail.get('i_out', 1) * 1.5:.1f}A)"
    return "Review component selection"


# ── Summarise DRC for SSE progress message ───────────────────────────────────
def drc_summary(violations: list) -> str:
    errors   = [v for v in violations if v.get("severity") == "ERROR"]
    warnings = [v for v in violations if v.get("severity") == "WARNING"]
    if not violations:
        return "DRC: All rules passed ✓"
    parts = []
    if errors:   parts.append(f"{len(errors)} error(s)")
    if warnings: parts.append(f"{len(warnings)} warning(s)")
    return "DRC: " + ", ".join(parts) + " detected"
