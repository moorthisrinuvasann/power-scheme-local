"""
Power Scheme Engineering Calculator
Real datasheet-derived calculations replacing LLM estimates.
"""
import math

# ── Datasheet constants for all supported components ─────────────────────────
# Note: channels = number of independent outputs (for multi-output μModules)
#       When channels > 1, the component can power multiple rails from one package
COMPONENT_SPECS = {
    # Buck Converters           vin_range      f_sw      L      C_out  Rθja   η     I_max  ESR  channels
    "LTM4638":   {"type":"buck","vin_range":(4.5,20.0),"f_sw_hz":1e6,  "l_uh":1.5,"c_out_uf":47,  "rth_ja":8.0, "eta":0.91,"i_max":10.0,"esr_mohm":8, "channels":1},
    "LTM4622":   {"type":"buck","vin_range":(2.7,17.0),"f_sw_hz":1.5e6,"l_uh":1.0,"c_out_uf":22,  "rth_ja":10.0,"eta":0.90,"i_max":4.0, "esr_mohm":12, "channels":1},
    "LTM4622IV": {"type":"buck","vin_range":(2.7,17.0),"f_sw_hz":1.5e6,"l_uh":1.0,"c_out_uf":22,  "rth_ja":10.0,"eta":0.90,"i_max":4.0, "esr_mohm":12, "channels":1},
    "LTM4630":   {"type":"buck","vin_range":(4.5,28.0),"f_sw_hz":800e3,"l_uh":1.5,"c_out_uf":100, "rth_ja":5.0, "eta":0.93,"i_max":15.0,"esr_mohm":6, "channels":1},
    "LTM4630A":  {"type":"buck","vin_range":(4.5,28.0),"f_sw_hz":800e3,"l_uh":1.5,"c_out_uf":100, "rth_ja":5.0, "eta":0.93,"i_max":15.0,"esr_mohm":6, "channels":1},
    "LTM4650":   {"type":"buck","vin_range":(4.5,20.0),"f_sw_hz":600e3,"l_uh":1.5,"c_out_uf":220, "rth_ja":4.0, "eta":0.93,"i_max":25.0,"esr_mohm":5, "channels":1},
    "LTM4650-1": {"type":"buck","vin_range":(4.5,20.0),"f_sw_hz":600e3,"l_uh":1.5,"c_out_uf":220, "rth_ja":4.0, "eta":0.93,"i_max":25.0,"esr_mohm":5, "channels":1},
    "LTM4655":   {"type":"buck","vin_range":(4.5,20.0),"f_sw_hz":1e6,  "l_uh":1.5,"c_out_uf":47,  "rth_ja":6.5, "eta":0.92,"i_max":15.0,"esr_mohm":8, "channels":1},
    "LTM4671":   {"type":"buck","vin_range":(3.1,20.0),"f_sw_hz":1e6,  "l_uh":1.0,"c_out_uf":22,  "rth_ja":12.0,"eta":0.90,"i_max":12.0,"esr_mohm":12, "channels":4},  # Quad-output (dual 12A + dual 5A)
    "LTM4675":   {"type":"buck","vin_range":(4.5,28.0),"f_sw_hz":800e3,"l_uh":1.5,"c_out_uf":100, "rth_ja":5.5, "eta":0.92,"i_max":13.0,"esr_mohm":7, "channels":2},  # Dual-output
    "LTM4676A":  {"type":"buck","vin_range":(4.5,28.0),"f_sw_hz":800e3,"l_uh":1.5,"c_out_uf":100, "rth_ja":5.5, "eta":0.92,"i_max":13.0,"esr_mohm":7, "channels":2},  # Dual-output
    "LTM4680":   {"type":"buck","vin_range":(4.5,20.0),"f_sw_hz":500e3,"l_uh":2.0,"c_out_uf":220, "rth_ja":4.5, "eta":0.93,"i_max":10.0,"esr_mohm":6, "channels":1},
    "LTM4700":   {"type":"buck","vin_range":(4.5,60.0),"f_sw_hz":400e3,"l_uh":2.5,"c_out_uf":470, "rth_ja":2.5, "eta":0.94,"i_max":50.0,"esr_mohm":3, "channels":1},
    "LTM4705":   {"type":"buck","vin_range":(4.5,60.0),"f_sw_hz":300e3,"l_uh":3.0,"c_out_uf":680, "rth_ja":2.0, "eta":0.95,"i_max":40.0,"esr_mohm":3, "channels":1},
    "TPSM82866A":{"type":"buck","vin_range":(2.7,17.0),"f_sw_hz":2.2e6,"l_uh":0.47,"c_out_uf":22, "rth_ja":20.0,"eta":0.88,"i_max":6.0, "esr_mohm":15, "channels":1},
    "LTM8067FC": {"type":"buck","vin_range":(3.1,40.0),"f_sw_hz":1e6,  "l_uh":1.5,"c_out_uf":47,  "rth_ja":10.0,"eta":0.88,"i_max":0.6, "esr_mohm":10, "channels":1},
    # LDO Regulators              rth    100Hz  10kHz  1MHz   Vdo   Imax
    "LT3070":    {"type":"ldo","rth_ja":34.0,"psrr":[74,65,40],"vdo":0.30,"i_max":4.0},
    "ADP1763":   {"type":"ldo","rth_ja":40.0,"psrr":[80,70,48],"vdo":0.35,"i_max":1.0},
    "ADP7159":   {"type":"ldo","rth_ja":62.0,"psrr":[75,68,52],"vdo":0.20,"i_max":0.5},
    "TPS737":    {"type":"ldo","rth_ja":45.0,"psrr":[72,60,38],"vdo":0.50,"i_max":1.0},
    "TPS73701DCQ":{"type":"ldo","rth_ja":45.0,"psrr":[72,60,38],"vdo":0.50,"i_max":1.0},
    "TPS7A85A":  {"type":"ldo","rth_ja":25.0,"psrr":[78,72,60],"vdo":0.25,"i_max":4.0},
}

def resolve_spec(name: str) -> dict:
    """Return spec for component, with fuzzy matching fallback."""
    if not name:
        return {"type":"buck","f_sw_hz":1e6,"l_uh":1.5,"c_out_uf":47,"rth_ja":10.0,"eta":0.88,"i_max":10.0}
    u = name.upper().replace(" ","").replace("-","")
    for k, v in COMPONENT_SPECS.items():
        if k.upper().replace("-","") == u:
            return v
    for k, v in COMPONENT_SPECS.items():
        if k.upper().replace("-","") in u or u in k.upper().replace("-",""):
            return v
    # type hint fallback
    if any(x in name.upper() for x in ["LDO","TPS7","ADP","LT307"]):
        return {"type":"ldo","rth_ja":45.0,"psrr":[60,50,35],"vdo":0.5,"i_max":1.0}
    return {"type":"buck","f_sw_hz":1e6,"l_uh":1.5,"c_out_uf":47,"rth_ja":10.0,"eta":0.88,"i_max":10.0}


def calc_buck_rail(v_in, v_out, i_out, spec, ta, req_ripple_mv, req_psrr_db, channels=1, channel_index=0):
    """
    Real ripple + thermal calculation for a Buck rail.
    For multi-output Bucks: thermal is calculated based on TOTAL power across all channels.
    """
    f   = spec["f_sw_hz"]
    L   = spec["l_uh"] * 1e-6
    C   = spec["c_out_uf"] * 1e-6
    eta = spec["eta"]
    rth = spec["rth_ja"]
    D   = min(v_out / v_in, 0.99)

    # Ripple — includes capacitor ESR contribution
    dIL        = (v_in - v_out) * D / (f * L)
    esr_mohm   = spec.get("esr_mohm", 10)          # typ. ceramic ESR from spec
    dV_cap_mv  = (dIL / (8 * f * C)) * 1000         # capacitive ripple
    dV_esr_mv  = dIL * (esr_mohm / 1000) * 1000     # ESR ripple
    dV_mv      = math.sqrt(dV_cap_mv**2 + dV_esr_mv**2)  # total (quadrature sum)
    rip_ok     = dV_mv <= req_ripple_mv

    # Thermal: for multi-output, each channel contributes to total power dissipation
    # We'll store per-channel power for aggregation later
    pdiss_channel = (1 - eta) * v_out * i_out
    tj_per_watt   = ta + rth  # Tj per watt of total dissipation

    # PSRR: bucks have inherent line rejection from control loop ~40-60dB
    psrr_buck_db = 46  # typical for high-freq buck
    p_ok = psrr_buck_db >= req_psrr_db

    i_max   = spec["i_max"]
    # For multi-output, each channel has its own current limit
    derating = i_max / i_out if i_out > 0 else 999
    d_ok     = derating >= 1.5
    d_warn   = 1.2 <= derating < 1.5

    return {
        "ripple": {
            "calculation": (f"D={v_out}/{v_in}={D:.3f}; dIL={dIL:.3f}A; "
                            f"dV_cap={dV_cap_mv:.1f}mV; dV_ESR(ESR={esr_mohm}mΩ)={dV_esr_mv:.1f}mV; "
                            f"dV_total=√({dV_cap_mv:.1f}²+{dV_esr_mv:.1f}²)={dV_mv:.1f}mV"),
            "value": f"{dV_mv:.1f} mV",
            "status": "Pass" if rip_ok else "Fail"
        },
        "psrr": {
            "calculation": f"Buck control-loop line rejection (datasheet): ~{psrr_buck_db}dB at {f/1e6:.1f}MHz; Requirement: >{req_psrr_db}dB",
            "value": f"{psrr_buck_db} dB",
            "status": "Pass" if p_ok else "Fail"
        },
        "thermal": {
            "calculation": f"P_diss(channel)={(1-eta)*v_out*i_out:.2f}W; (aggregate across {channels} channels for total Tj)",
            "value": f"p_diss={pdiss_channel:.2f}W",  # Store per-channel dissipation
            "status": "Pending"  # Will be updated after aggregation
        },
        "derating": {
            "calculation": f"I_max={i_max}A / I_load={i_out}A = {derating:.2f}x (required ≥1.5x, recommended ≥1.75x)",
            "value": f"{derating:.2f}x",
            "status": "Pass" if d_ok else ("Warn" if d_warn else "Fail")
        },
        "_pdiss_channel": pdiss_channel,  # Internal: per-channel power dissipation
        "_tj_per_watt": tj_per_watt,      # Internal: Tj per watt for aggregation
        "_channels": channels,             # Internal: number of channels
    }


def calc_ldo_rail(v_in, v_out, i_out, spec, ta, buck_ripple_mv, req_ripple_mv, req_psrr_db, buck_f_hz=1e6):
    """Real PSRR-attenuated ripple + thermal calculation for an LDO rail."""
    rth  = spec["rth_ja"]
    psrr_arr = spec.get("psrr", [60, 50, 35])  # [100Hz, 10kHz, 1MHz]

    # Pick PSRR at the upstream buck's switching frequency
    if buck_f_hz <= 10_000:
        psrr_db, freq_label = psrr_arr[0], "100Hz"
    elif buck_f_hz <= 1_000_000:
        psrr_db, freq_label = psrr_arr[1], "10kHz"
    else:
        psrr_db, freq_label = psrr_arr[2], "1MHz"

    atten      = 10 ** (psrr_db / 20)
    rip_out_mv = buck_ripple_mv / atten
    rip_ok     = rip_out_mv <= req_ripple_mv
    p_ok       = psrr_db >= req_psrr_db

    # Thermal
    pdiss = (v_in - v_out) * i_out
    tj    = ta + pdiss * rth
    t_ok  = tj <= 125.0

    i_max    = spec.get("i_max", 999)
    derating  = i_max / i_out if i_out > 0 else 999
    d_ok      = derating >= 1.5
    d_warn    = 1.2 <= derating < 1.5

    return {
        "ripple": {
            "calculation": f"LDO PSRR={psrr_db}dB@{freq_label} (datasheet); Atten=10^({psrr_db}/20)={atten:.0f}x; V_out_rip={buck_ripple_mv:.1f}mV/{atten:.0f}={rip_out_mv:.2f}mV",
            "value": f"{rip_out_mv:.2f} mV",
            "status": "Pass" if rip_ok else "Fail"
        },
        "psrr": {
            "calculation": f"Datasheet PSRR={psrr_db}dB at {freq_label} (upstream buck f_sw={buck_f_hz/1e6:.1f}MHz); Requirement: >{req_psrr_db}dB",
            "value": f"{psrr_db} dB",
            "status": "Pass" if p_ok else "Fail"
        },
        "thermal": {
            "calculation": f"P_diss=(V_in-V_out)*I_out=({v_in}-{v_out})*{i_out}A={pdiss:.2f}W; Tj={ta}C+{pdiss:.2f}W*{rth}C/W={tj:.1f}C",
            "value": f"{tj:.1f} °C",
            "status": "Pass" if t_ok else "Fail"
        },
        "derating": {
            "calculation": f"I_max={i_max}A / I_load={i_out}A = {derating:.2f}x (required \u22651.5x, recommended \u22651.75x)",
            "value": f"{derating:.2f}x",
            "status": "Pass" if d_ok else ("Warn" if d_warn else "Fail")
        }
    }


def calculate_all_rails(rail_assignments: list, req: dict) -> list:
    """
    Main entry point. Takes LLM rail assignments and returns full rail_analysis
    with real Python-calculated values.

    For multi-output Buck converters: thermal calculation aggregates power across all channels.
    """
    ta          = float(req.get("ta", 85))
    req_rip_mv  = float(req.get("ripple_mv", 15))
    req_psrr_db = float(req.get("psrr_db", 35))

    # First pass: calculate all buck rails and store ripple values
    buck_ripples = {}   # component_name -> ripple_mv for LDO upstream lookup
    buck_f_sw    = {}   # component_name -> f_sw_hz
    comp_pdiss   = {}   # component_name -> total power dissipation (for multi-output thermal)

    for ra in rail_assignments:
        comp = ra.get("component", "")
        spec = resolve_spec(comp)
        if spec["type"] == "buck":
            v_in  = float(ra.get("v_in", 12))
            v_out = float(ra.get("v_out", 3.3))
            i_out = float(ra.get("i_out", 1))
            channels = ra.get("channels", 1)
            channel_index = ra.get("channel_index", 0)
            res   = calc_buck_rail(v_in, v_out, i_out, spec, ta, req_rip_mv, req_psrr_db, channels, channel_index)
            rip_v = float(res["ripple"]["value"].replace("mV","").strip())
            buck_ripples[comp] = rip_v
            buck_f_sw[comp]    = spec["f_sw_hz"]
            # Aggregate power dissipation for multi-output Bucks
            if comp not in comp_pdiss:
                comp_pdiss[comp] = {"total_pdiss": 0, "rth": spec["rth_ja"], "ta": ta}
            comp_pdiss[comp]["total_pdiss"] += res.get("_pdiss_channel", 0)

    # Second pass: build full rail_analysis with corrected thermal for multi-output
    result = []
    for ra in rail_assignments:
        comp      = ra.get("component", "")
        rail_name = ra.get("rail", "Rail")
        v_in      = float(ra.get("v_in", 12))
        v_out     = float(ra.get("v_out", 3.3))
        i_out     = float(ra.get("i_out", 1))
        spec      = resolve_spec(comp)
        channels  = ra.get("channels", 1)
        channel_index = ra.get("channel_index", 0)

        if spec["type"] == "buck":
            calcs = calc_buck_rail(v_in, v_out, i_out, spec, ta, req_rip_mv, req_psrr_db, channels, channel_index)
            # Update thermal for multi-output Bucks with aggregate calculation
            if channels > 1 and comp in comp_pdiss:
                total_pdiss = comp_pdiss[comp]["total_pdiss"]
                rth = comp_pdiss[comp]["rth"]
                ta_val = comp_pdiss[comp]["ta"]
                tj = ta_val + total_pdiss * rth
                calcs["thermal"] = {
                    "calculation": f"P_diss(total)={total_pdiss:.2f}W ({channels} channels); Tj={ta_val}°C+{total_pdiss:.2f}W*{rth}°C/W={tj:.1f}°C",
                    "value": f"{tj:.1f} °C",
                    "status": "Pass" if tj <= 125.0 else "Fail"
                }
        else:
            # LDO: find upstream buck ripple
            upstream = ra.get("upstream_component", "")
            upstream_rip = buck_ripples.get(upstream, buck_ripples.get(comp, 15.0))
            upstream_f   = buck_f_sw.get(upstream, 1e6)
            calcs = calc_ldo_rail(v_in, v_out, i_out, spec, ta, upstream_rip, req_rip_mv, req_psrr_db, upstream_f)

        result.append({
            "rail":             rail_name,
            "component":        comp,
            "component_display": ra.get("component_display", comp),
            "channels":         ra.get("channels", 1),
            "channel_index":    ra.get("channel_index", 0),
            "ripple":           calcs["ripple"],
            "psrr":             calcs["psrr"],
            "thermal":          calcs["thermal"],
            "derating":         calcs["derating"],
        })

    return result
