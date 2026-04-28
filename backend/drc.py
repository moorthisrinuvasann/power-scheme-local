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
    ta          = float(req_params.get("ta", 85))
    req_ripple_mv = float(req_params.get("ripple_mv", 15))
    req_psrr_db   = float(req_params.get("psrr_db", 35))

    for ra in rail_assignments:
        comp      = ra.get("component", "")
        spec      = resolve_spec(comp)
        v_in      = float(ra.get("v_in",  12.0))
        v_out     = float(ra.get("v_out",  3.3))
        i_out     = float(ra.get("i_out",  1.0))
        rail      = ra.get("rail", "Unknown Rail")
        ctype     = spec.get("type", "buck")
        i_max     = float(spec.get("i_max", 999))

        # ── Rule 1: Voltage ripple check ───────────────────────────────────
        if ctype == "buck":
            f   = spec.get("f_sw_hz", 1e6)
            L   = spec.get("l_uh", 1.5) * 1e-6
            C   = spec.get("c_out_uf", 47) * 1e-6
            eta = spec.get("eta", 0.9)
            esr_mohm = spec.get("esr_mohm", 10)

            D = min(v_out / v_in, 0.99)
            dIL = (v_in - v_out) * D / (f * L)
            dV_cap_mv = (dIL / (8 * f * C)) * 1000
            dV_esr_mv = dIL * (esr_mohm / 1000) * 1000
            dV_mv = (dV_cap_mv**2 + dV_esr_mv**2)**0.5

            if dV_mv > req_ripple_mv:
                violations.append({
                    "rail":      rail,
                    "component": comp,
                    "rule":      "Voltage Ripple",
                    "severity":  "ERROR",
                    "detail":    f"Ripple={dV_mv:.1f}mV exceeds limit {req_ripple_mv}mV. f={f/1e6}MHz, L={spec.get('l_uh')}µH, C={spec.get('c_out_uf')}µF.",
                    "fix":       f"Select component with higher frequency or larger output capacitance"
                })

        # ── Rule 2: Thermal check ──────────────────────────────────────────
        pdiss = (1 - spec.get("eta", 0.9)) * v_out * i_out
        tj    = ta + pdiss * spec.get("rth_ja", 10)
        if tj > 125:
            violations.append({
                "rail":      rail,
                "component": comp,
                "rule":      "Thermal",
                "severity":  "ERROR",
                "detail":    f"Tj={tj:.1f}°C exceeds 125°C limit. P_diss={pdiss:.2f}W, Rθja={spec.get('rth_ja')}°C/W, Ta={ta}°C.",
                "fix":       f"Select component with lower Rθja or improve cooling"
            })

        # ── Rule 3: Current derating (must be ≥ 1.5×) ──────────────────────
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

        # ── Rule 4: LDO dropout voltage ─────────────────────────────────────
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

            # ── Rule 4b: LDO PSRR check ───────────────────────────────────────
            psrr_db = max(spec.get("psrr", [0, 0, 0]))  # Best PSRR across frequencies
            if psrr_db < req_psrr_db:
                violations.append({
                    "rail":      rail,
                    "component": comp,
                    "rule":      "LDO PSRR",
                    "severity":  "ERROR",
                    "detail":    f"PSRR={psrr_db}dB below requirement {req_psrr_db}dB.",
                    "fix":       f"Select LDO with PSRR > {req_psrr_db}dB"
                })

        # ── Rule 5: Buck input voltage range ────────────────────────────────
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

        # ── Rule 6: Output voltage sanity check ───────────────────────────────
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


# ── Check calculator results for PSRR failures only ───────────────────────────
# (Other checks like ripple, thermal, derating are now in run_drc())
def check_calc_failures(rail_analysis: list) -> list:
    """
    Inspects Python calculator results for PSRR failures only.
    Returns list of failed rail dicts with severity field for frontend display.
    """
    failures = []
    for r in rail_analysis:
        # Only check PSRR - other checks are in run_drc()
        data = r.get("psrr", {})
        if str(data.get("status", "")).lower() == "fail":
            failures.append({
                "rail":          r.get("rail", ""),
                "component":     r.get("component", ""),
                "analysis_type": "psrr",
                "severity":      "ERROR",
                "value":         data.get("value", ""),
                "calculation":   data.get("calculation", ""),
                "rule":          "PSRR Check",
                "detail":        data.get("calculation", ""),
                "fix":           "Use LDO with higher PSRR or add additional filtering"
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
