"""Fluid and working-pair options (follow-up 2026-10-21).

Lumped steady-state model. Needs CoolProp:
    python fluids.py            # Ta 25 C
    TA=30 python fluids.py      # hot room

Three fluid roles are kept apart:
  1. single-phase pickup at the chip (water, glycol, oil, PFPE, HFO liquid, liquid metal)
  2. two-phase pickup (boiling on the chip; thermosiphon or pumped)
  3. chiller working pair (sorption, absorption, ejector, ORC+VC)
plus 4. compact supplemental heat, and 5. complete-configuration ranking.

Every number not from CoolProp is marked ASSUME or carries a source tag
that is listed in the report section "Fluid and working-pair options".
"""
import math, os
import CoolProp.CoolProp as CP

K = 273.15
TA = float(os.environ.get("TA", 25.0))          # room, C
RH = float(os.environ.get("RH", 0.50))
APP = float(os.environ.get("APP", 4.0))         # K per heat exchanger (3 tight, 4 good, 5 hobby)

# ---------------- chip / block stack (ASSUME, calibrated to prior pass R_blk = 0.055 K/W) -------------
GPU_BOARD = 250.0          # W board power (GTX 480/780, HD 7970 class)
GPU_CAPTURE = 0.85         # fraction of board power into the block
DIE_SHARE = 0.75           # fraction of captured heat that passes through the die (rest: VRAM/VRM pads)
DIE_AREA = 4.0e-4          # m2 (352-561 mm2 across the era; 400 mm2 typical)
FOOTPRINT = 10e-4          # m2 cold-plate fin-field footprint the die heat spreads to
AREA_RATIO = 5.0           # wetted microfin area / footprint
FIN_EFF = 0.8
R2_SI = 6e-6               # m2K/W silicon, 0.75 mm / ~125 W/mK
R2_PASTE = 8e-6            # m2K/W good paste, thin bond line
R2_LM = 2e-6               # m2K/W liquid-metal TIM (Ga-based) incl. contact (ASSUME)
R2_BASE = 5e-6             # m2K/W copper base incl. spreading
R_CONV_WATER = 0.010       # K/W water microfin convection (makes total 0.0575 K/W with paste)
GLIDE_W = 2.0              # K coolant rise across block, water at ~1.5 L/min
DIE_MAX = float(os.environ.get("DIE_MAX", 65.0))
CPU_W = 95.0
R_CPU_BLK = 0.10           # K/W old IHS CPU, case to coolant
R_TS_MID = 0.115           # K/W thermosiphon case-to-ambient (prior pass)
UA_CPU_AMB = 30.0          # W/K hybrid booster: CPU loop's own radiator (prior pass config B)

def dew(T, rh):
    a, b = 17.62, 243.12
    g = math.log(rh) + a * T / (b + T)
    return b * g / (a - g)

DEW_FLOOR = dew(TA, RH) + 3.0

# ---------------- 1. single-phase pickup fluids ----------------
# k W/mK, cp J/kgK, rho kg/m3, mu Pa s at ~50 C; price USD per litre (retail, rounded); notes
def cpq(f, prop, T=50):
    return CP.PropsSI(prop, 'T', T + K, 'P', 3e5, f)

def single_phase_table():
    rows = []
    for name, f in (("Water (distilled + inhibitor)", "Water"), ("MEG 30 % (ethylene glycol)", "INCOMP::MEG-30%"),
                    ("MPG 30 % (propylene glycol)", "INCOMP::MPG-30%")):
        rows.append((name, cpq(f, 'L'), cpq(f, 'C'), cpq(f, 'D'), cpq(f, 'V')))
    # R1336mzz(Z) liquid (Opteon SF33) at 50 C, pressurised to stay liquid
    f = "R1336mzz(Z)"; P = CP.PropsSI('P', 'T', 50 + K, 'Q', 0, f) * 1.5
    # CoolProp 8 has no transport model for R1336mzz(Z): k, mu from literature (ASSUME ~0.073 W/mK, ~0.40 mPa s)
    rows.append(("Opteon SF33 liquid, R1336mzz(Z)", 0.073, CP.PropsSI('C', 'T', 323.15, 'P', P, f),
                 CP.PropsSI('D', 'T', 323.15, 'P', P, f), 0.40e-3))
    # literature / datasheet values (ASSUME where flagged in report)
    rows += [
        ("Mineral oil (white oil, ~15 cSt @40C)", 0.13, 1900, 850, 0.008),
        ("Synthetic PAO / dielectric oil (~6 cSt)", 0.14, 2200, 800, 0.004),
        ("Galden HT55/HT135 PFPE", 0.065, 963, 1680, 0.0012),
        ("Galinstan GaInSn", 16.5, 296, 6440, 0.0024),
        ("Water + 1 vol% Al2O3 nanofluid", 0.66, 4050, 1018, 0.00060),
    ]
    return rows

PRICE = {  # USD/L, rough 2026 retail (ASSUME except where sourced)
    "Water (distilled + inhibitor)": 0.5, "MEG 30 % (ethylene glycol)": 2, "MPG 30 % (propylene glycol)": 3,
    "Opteon SF33 liquid, R1336mzz(Z)": "quote only", "Mineral oil (white oil, ~15 cSt @40C)": 5,
    "Synthetic PAO / dielectric oil (~6 cSt)": 15, "Galden HT55/HT135 PFPE": 600,
    "Galinstan GaInSn": 12000, "Water + 1 vol% Al2O3 nanofluid": 50}

def single_phase():
    print(f"## 1. Single-phase pickup, GPU {GPU_BOARD:.0f} W board, die <= {DIE_MAX:.0f} C, paste TIM")
    print("fluid | k W/mK | cp kJ/kgK | rho | mu mPa s | flow L/min @2K | rel pump W | R_conv K/W | glide K | max harvest C | price $/L")
    kw = cpq("Water", 'L'); muw = cpq("Water", 'V')
    Q = GPU_BOARD * GPU_CAPTURE
    out = {}
    for name, k, cp, rho, mu in single_phase_table():
        # fix flow so that glide = 2 K (or as low as a 5x water-pump budget allows)
        V = Q / (rho * cp * GLIDE_W)                     # m3/s
        Vw = Q / (cpq("Water", 'D') * cpq("Water", 'C') * GLIDE_W)
        rel_pump = (mu / muw) * (V / Vw) ** 2            # laminar microchannel: dp ~ mu V, P ~ mu V^2
        glide = GLIDE_W
        if rel_pump > 5:                                 # cap pump at 5x water, let glide rise
            V = Vw * math.sqrt(5 / (mu / muw)); rel_pump = 5; glide = Q / (rho * cp * V)
        # laminar fully developed: Nu const -> h ~ k. Liquid metal: same scaling.
        r_conv = R_CONV_WATER * kw / k
        r_cond = (R2_SI + R2_PASTE) / DIE_AREA * 1.0 + R2_BASE / DIE_AREA
        # die sees coolant near outlet temperature (worst case of counter-flow)
        harvest = DIE_MAX - Q * DIE_SHARE * r_cond - Q * r_conv
        out[name] = (harvest, glide, rel_pump)
        print(f"{name} | {k:.3f} | {cp/1e3:.2f} | {rho:.0f} | {mu*1e3:.2f} | {V*6e4:.2f} | {rel_pump:.2f} | {r_conv:.4f} | {glide:.1f} | {harvest:.1f} | {PRICE.get(name)}")
    r_lm = (R2_SI + R2_LM + R2_BASE) / DIE_AREA
    print(f"Same, water but liquid-metal TIM: max harvest {DIE_MAX - Q*DIE_SHARE*r_lm - Q*R_CONV_WATER:.1f} C")
    print()
    return out

# ---------------- 2. two-phase pickup ----------------
def cooper(f, Tsat, q):
    Pr = CP.PropsSI('P', 'T', Tsat + K, 'Q', 0, f) / CP.PropsSI('Pcrit', f)
    M = CP.PropsSI('molemass', f) * 1000
    return 55 * Pr ** 0.12 * (-math.log10(Pr)) ** -0.55 * M ** -0.5 * q ** 0.67

TWO_PHASE = [  # (CoolProp name, label, ASHRAE class / hazard, US civilian route)
    ("R1233zd(E)", "R1233zd(E)", "A1", "refrigerant: 608 sales restriction (non-exempt substitute); solvent grade sold as Solstice PF (verify)"),
    ("R1336mzz(Z)", "Opteon SF33", "A1", "specialty fluid, distributor quote; not sold as refrigerant"),
    ("R1234ze(E)", "R1234ze(E)", "A2L", "608 restricted; no small-can route"),
    ("R134a", "R134a", "A1, GWP 1430", "12 oz MVAC cans, no cert (self-sealing valve)"),
    ("Isobutane", "R600a isobutane", "A3", "butane/isobutane fuel refill cans (purity varies)"),
    ("n-Butane", "n-butane", "A3", "lighter/camp fuel cans"),
    ("n-Pentane", "n-pentane", "A3", "lab-chemical suppliers, 1-4 L"),
    ("Ethanol", "ethanol", "flammable", "denatured/lab ethanol, hardware store"),
    ("Methanol", "methanol", "flammable, toxic", "hardware store (fuel/solvent)"),
    ("Water", "water", "none", "any"),
    ("CO2", "CO2", "A1, high pressure", "Tcrit 31 C: cannot boil at 50-60 C (supercritical)"),
]
F_FLOW = float(os.environ.get("F_FLOW", 2.0))   # flow-boiling / microchannel enhancement over Cooper pool (ASSUME; EPFL 8 K at 107 W/cm2 check)

def two_phase_harvest(f, F=F_FLOW, tim=R2_PASTE):
    """Highest T_sat with die <= DIE_MAX. Solve iteratively (h depends on T_sat)."""
    Q = GPU_BOARD * GPU_CAPTURE
    r_cond = (R2_SI + tim + R2_BASE) / DIE_AREA
    q_wet = Q / (FOOTPRINT * AREA_RATIO)
    Ts = DIE_MAX - 10
    for _ in range(30):
        try:
            h = F * cooper(f, Ts, q_wet)
        except Exception:
            return None
        r_boil = 1 / (h * FOOTPRINT * AREA_RATIO * FIN_EFF)
        Ts = DIE_MAX - Q * DIE_SHARE * r_cond - Q * r_boil
    return Ts, h, r_boil

def two_phase():
    print(f"## 2. Two-phase pickup on the GPU die (Cooper x F={F_FLOW}, wetted flux {GPU_BOARD*GPU_CAPTURE/(FOOTPRINT*AREA_RATIO)/1e3:.0f} kW/m2)")
    print("fluid | T_sat max C | h kW/m2K | R_boil K/W | Psat@T_sat bar | Psat@25C bar | vapour vol flow L/s | charge note | hazard | US civilian route")
    Q = GPU_BOARD * GPU_CAPTURE
    res = {}
    for f, lab, haz, route in TWO_PHASE:
        if CP.PropsSI('Tcrit', f) - K < DIE_MAX:
            print(f"{lab} | n/a (supercritical above {CP.PropsSI('Tcrit', f)-K:.0f} C) | | | | | | | {haz} | {route}")
            continue
        r = two_phase_harvest(f)
        Ts, h, rb = r
        P = CP.PropsSI('P', 'T', Ts + K, 'Q', 0, f) / 1e5
        P25 = CP.PropsSI('P', 'T', TA + K, 'Q', 0, f) / 1e5
        hfg = CP.PropsSI('H', 'T', Ts + K, 'Q', 1, f) - CP.PropsSI('H', 'T', Ts + K, 'Q', 0, f)
        rv = CP.PropsSI('D', 'T', Ts + K, 'Q', 1, f)
        vol = Q / hfg / rv * 1000
        note = "sub-atm (air leaks in)" if P25 < 1.0 else ("high P" if P > 10 else "ok")
        res[lab] = Ts
        print(f"{lab} | {Ts:.1f} | {h/1e3:.1f} | {rb:.4f} | {P:.2f} | {P25:.2f} | {vol:.2f} | {note} | {haz} | {route}")
    lm = two_phase_harvest("R1234ze(E)", tim=R2_LM)[0]
    lm2 = two_phase_harvest("R1233zd(E)", tim=R2_LM)[0]
    print(f"With liquid-metal TIM: R1234ze(E) {lm:.1f} C, R1233zd(E) {lm2:.1f} C")
    best = two_phase_harvest("R1234ze(E)", F=4.0, tim=R2_LM)[0]
    print(f"Optimistic ceiling (F=4, LM TIM, R1234ze): {best:.1f} C")
    for W in (165, 120):
        Qd = W * GPU_CAPTURE
        r_cond = (R2_SI + R2_LM + R2_BASE) / DIE_AREA
        print(f"  Power-limited GPU at {W} W board, LM TIM, boiling dT~3 K: T_sat ~ {DIE_MAX - Qd*DIE_SHARE*r_cond - 3:.1f} C")
    # what die temperature a 58-62 C harvest needs at 250 W
    for tgt in (58, 62):
        r_cond = (R2_SI + R2_PASTE + R2_BASE) / DIE_AREA
        print(f"  Harvest {tgt} C at 250 W needs die ~ {tgt + Q*DIE_SHARE*r_cond + 4:.0f} C (paste) / "
              f"{tgt + Q*DIE_SHARE*(R2_SI+R2_LM+R2_BASE)/DIE_AREA + 4:.0f} C (LM)")
    print()
    return res

# ---------------- 3. chiller working pairs ----------------
# r = sorption enthalpy / refrigerant vaporisation enthalpy (Duhring slope ratio).
# excess = extra K above the ideal-step Duhring threshold (isotherm width, rectification, crystallisation margin),
# calibrated so Tg_min at Ta-cooling 30 C / chilled 15 C matches the literature value in the report.
# cop_cap = best realistic single-effect thermal COP reported. tau = K above Tg_min to reach ~63 % of cop_cap (ASSUME 8).
PAIRS = [
    # name, refrigerant, r, excess, cop_cap, maturity(0-1), civilian(0-1), safety(0-1), note
    ("Silica gel RD - water", "Water", 1.10, 5, 0.60, 1.0, 1.0, 1.0, "commercial (Fahrenheit, InvenSor); kg-scale gel is cheap"),
    ("Step zeolite FAM-Z01/Z05 - water", "Water", 1.10, 2, 0.62, 0.8, 0.4, 1.0, "Mitsubishi AQSOA; sold to OEMs, small lots hard"),
    ("MOF CAU-23 / Al-fumarate - water", "Water", 1.10, 4, 0.57, 0.4, 0.2, 1.0, "lab/pilot; Al-fum sold by BASF as Basolite A520 (research qty)"),
    ("CaCl2-in-silica (SWS-1L) - water", "Water", 1.30, 14, 0.60, 0.6, 0.9, 1.0, "DIY-able: CaCl2 + silica gel; drive 80-95 C reported"),
    ("LiBr - water (single effect)", "Water", 1.15, 15, 0.70, 1.0, 0.6, 0.8, "kW-scale only; vacuum, crystallisation, corrosion"),
    ("NH3 - LiNO3", "Ammonia", 1.20, 16, 0.65, 0.5, 0.3, 0.3, "COP 0.6-0.68 at 90 C (exp); NH3 toxic, steel only"),
    ("NH3 - H2O", "Ammonia", 1.25, 30, 0.50, 1.0, 0.4, 0.3, "needs rectifier; 13-18 bar; Icyball class"),
    ("BaCl2-vermiculite - NH3", "Ammonia", 1.80, 14, 0.54, 0.5, 0.4, 0.3, "COP 0.54 at 80-90 C (lab); desorption tested to 65 C"),
    ("AC (Maxsorb III) - methanol", "Methanol", 1.40, 16, 0.55, 0.7, 0.8, 0.6, "COP 0.73 claim at 85 C (sim); solar ice makers 0.1 solar COP"),
    ("AC (Maxsorb III) - ethanol", "Ethanol", 1.35, 18, 0.45, 0.5, 0.9, 0.7, "real prototype COP 0.05-0.18 at 80 C"),
    ("AC - R134a / R1234ze", "R134a", 1.30, 15, 0.20, 0.3, 0.5, 0.8, "low uptake, high pressure; R1234ze 608-restricted"),
    ("Ionic liquid ([EMIM][Ac]-class) - water", "Water", 1.20, 15, 0.55, 0.2, 0.3, 0.9, "simulation-stage"),
    ("Ejector, R1233zd(E) / R600a", "R1233zd(E)", 1.00, 25, 0.28, 0.6, 0.4, 0.7, "exp COP ~0.25 at 16/19 C glycol, <70 C source (200 kW plant)"),
    ("ORC + vapour compression (pentane/R1233zd)", "n-Pentane", 1.00, 5, 0.20, 0.2, 0.6, 0.5, "no 100 W-class expander exists"),
]
TAU = 8.0

def carnot(Tg, Tr, Tc):
    return (1 - (Tr + K) / (Tg + K)) * (Tc + K) / (Tr - Tc)

def tg_min(r, excess, Ta, Tch, app=None):
    app = APP if app is None else app
    Tads = Ta + 2 * app; Tcond = Ta + 2 * app; Te = Tch - app
    inv = 1 / (Tads + K) - (1 / (Te + K) - 1 / (Tcond + K)) / r
    return 1 / inv - K + excess + app       # + app: hot fluid to bed

def cop(pair, Tg, Ta, Tch):
    name, ref, r, ex, cap = pair[:5]
    tm = tg_min(r, ex, Ta, Tch)
    if Tg <= tm:
        return 0.0, tm
    c = cap * (1 - math.exp(-(Tg - tm) / TAU))
    c = min(c, 0.5 * carnot(Tg, Ta + APP, Tch - APP))   # never above 50 % of Carnot
    return c, tm

def pairs_table():
    print(f"## 3. Chiller pairs: minimum drive and COP (room {TA:.0f} C, approach {APP:.0f} K/HX)")
    print("pair | refrigerant P_evap/P_cond bar | Tg_min chilled 15 | 18 | 20 | COP@55 ch18 | @65 | @80 | best Carnot frac @80 | note")
    for p in PAIRS:
        ref = p[1]
        try:
            pe = CP.PropsSI('P', 'T', 18 - APP + K, 'Q', 0, ref) / 1e5
            pc = CP.PropsSI('P', 'T', TA + 2 * APP + K, 'Q', 0, ref) / 1e5
            ps = f"{pe:.3f}/{pc:.3f}"
        except Exception:
            ps = "-"
        tms = [tg_min(p[2], p[3], TA, t) for t in (15, 18, 20)]
        cs = [cop(p, Tg, TA, 18)[0] for Tg in (55, 65, 80)]
        frac = cs[2] / carnot(80, TA + APP, 18 - APP) if cs[2] else 0
        print(f"{p[0]} | {ps} | " + " | ".join(f"{t:.0f}" for t in tms) + " | " + " | ".join(f"{c:.2f}" for c in cs) + f" | {frac:.2f} | {p[8]}")
    print("Carnot COP (fluid-independent) at chilled 18, reject Ta+APP:",
          ", ".join(f"Tg {Tg}: {carnot(Tg, TA+APP, 18-APP):.2f}" for Tg in (50, 55, 60, 65, 80, 150)))
    print("Double-effect LiBr-water: drive 140-175 C, COP 1.0-1.3 (lit); needs a burner or concentrator, not chip heat.")
    print()

# ---------------- 4. supplemental heat ----------------
def collector_eta(Tm, Ta, G, kind):
    dT = Tm - Ta
    if kind == "ETC":   # evacuated tube, gross area (Ritter OEM-class, prior pass)
        return max(0.0, 0.42 - 0.80 * dT / G - 0.004 * dT * dT / G)
    if kind == "CPC-ETC":  # medium-temp CPC evacuated tube ~0.5 at 125 C (lit, single source)
        return max(0.0, 0.62 - 0.85 * dT / G - 0.0015 * dT * dT / G)
    return 0.0

def supplemental():
    print("## 4. Compact supplemental heat for Q_drive")
    G = 1000.0
    print("Physics floor: area >= Q/G. 100 W -> 0.10 m2, 300 W -> 0.30 m2 at 1 kW/m2 (perfect absorber, no losses).")
    for Tm, kind in ((75, "ETC"), (90, "ETC"), (125, "CPC-ETC"), (160, "CPC-ETC")):
        e = collector_eta(Tm, TA, G, kind)
        print(f"  {kind} at Tm {Tm} C, G 1000: eta {e:.2f}; area for 100 W {100/(G*e) if e else float('inf'):.2f} m2, 300 W {300/(G*e) if e else float('inf'):.2f} m2")
    print("  Propane burner: 46 MJ/kg -> 300 W heat = 23 g/h; indoor combustion needs a flue (CO, NOx, H2O).")
    print("  Candle ~77 W (NPL). Domestic hot-water tank 50-60 C: same grade as GPU harvest, and it is paid energy.")
    print("  Electric heater as drive: 1 W heat costs 1 W wall; a compressor needs ~0.3 W wall per W cold.")
    for name, cop_, T in (("single-effect silica gel @75 C", 0.49, 75), ("double-effect LiBr @150 C", 1.1, 150)):
        q = 100 / cop_
        print(f"  100 W cold via {name}: {q:.0f} W heat = {q*3600/46e6*1000:.1f} g/h propane, or {q:.0f} W wall if electric "
              f"(-> {q/8.4:.0f} W/K at the +8.4 K CPU gain); collector area {q/(1000*collector_eta(T+5, TA, 1000, 'CPC-ETC' if T>100 else 'ETC')*0.85):.2f} m2")
    print()

# ---------------- 5. configurations ----------------
def cpu_case(Qcold, Tch):
    """Hybrid booster: CPU loop has its own radiator (UA_CPU_AMB) + chiller trim at Tch floor.
    Solve loop T: CPU_W = UA*(T-Ta) + min(Qcold, CPU_W) if T>Tch."""
    lo, hi = Tch, 90.0
    for _ in range(60):
        T = 0.5 * (lo + hi)
        q = UA_CPU_AMB * max(0.0, T - TA) + (Qcold if T > Tch else 0)   # radiator bypassed below room temp
        if q >= CPU_W: hi = T
        else: lo = T
    return hi + R_CPU_BLK * CPU_W

def configs(sp, tp):
    print(f"## 5. Complete configurations, room {TA:.0f} C, dew floor {DEW_FLOOR:.1f} C, GPU {GPU_BOARD:.0f} W, CPU {CPU_W:.0f} W")
    base_cpu = TA + R_TS_MID * CPU_W
    Tch = max(18.0, DEW_FLOOR)
    pairs = {p[0]: p for p in PAIRS}
    Qg = GPU_BOARD * GPU_CAPTURE
    rows = []
    def add(name, hot_fluid, Qdrive, pair, wall_extra, area, gpu_die, maturity_mult, compact):
        """hot_fluid = hot-fluid temperature entering the bed HX. Tg_min already includes the fluid-to-bed approach."""
        p = pairs[pair]
        c, tm = cop(p, hot_fluid, TA, Tch)
        Qc = c * Qdrive
        case = cpu_case(Qc, Tch)
        gain = base_cpu - case
        wpk = wall_extra / gain if gain > 0.3 else float('inf')
        margin = max(0.0, min(1.0, (hot_fluid - tm) / 10))
        wk_f = min(1.0, 3.0 / wpk) if wpk > 0 else 1.0       # reward watts per kelvin at or below the compressor's ~3 W/K
        score = margin * p[5] * p[6] * p[7] * maturity_mult * compact * wk_f
        rows.append((score, name, pair, hot_fluid, tm, c, Qc, case, gain, gpu_die, wall_extra, wpk, area))
    w = sp["Water (distilled + inhibitor)"][0]
    Q = GPU_BOARD * GPU_CAPTURE
    w_lm = DIE_MAX - Q * DIE_SHARE * (R2_SI + R2_LM + R2_BASE) / DIE_AREA - Q * R_CONV_WATER
    ze_lm = two_phase_harvest("R1234ze(E)", tim=R2_LM)[0]
    zd_lm = two_phase_harvest("R1233zd(E)", tim=R2_LM)[0]
    # water: bed HX sees the mean of the glide. Condensing vapour: T_sat - 1 K line drop + 1 K film credit.
    for pair in ("Silica gel RD - water", "Step zeolite FAM-Z01/Z05 - water", "MOF CAU-23 / Al-fumarate - water"):
        add("GPU water + paste", w - GLIDE_W / 2, Qg, pair, 19, 0, DIE_MAX, 1.0, 0.7)
        add("GPU water + LM TIM", w_lm - GLIDE_W / 2, Qg, pair, 19, 0, DIE_MAX, 0.9, 0.7)
        add("GPU 2-phase R1233zd(E) thermosiphon, LM TIM, bed = condenser", zd_lm, Qg, pair, 14, 0, DIE_MAX, 0.6, 0.8)
        add("GPU 2-phase R1234ze(E) pumped, LM TIM, bed = condenser", ze_lm, Qg, pair, 16, 0, DIE_MAX, 0.5, 0.8)
    # relaxed die (sacrifice) for reference only
    add("REF: GPU water, die 75 C (violates band)", w + 10 - GLIDE_W / 2, Qg, "Silica gel RD - water", 19, 0, 75, 1.0, 0.7)
    add("REF: GPU 2-phase R1234ze, LM TIM, die 70 C (violates band)", ze_lm + 5, Qg, "Step zeolite FAM-Z01/Z05 - water", 16, 0, 70, 0.5, 0.8)
    # external compact heat, GPU left on its own ambient loop
    for pair, Tdrive in (("Silica gel RD - water", 75), ("CaCl2-in-silica (SWS-1L) - water", 85), ("AC (Maxsorb III) - methanol", 85),
                         ("BaCl2-vermiculite - NH3", 85), ("NH3 - LiNO3", 85), ("Ejector, R1233zd(E) / R600a", 85)):
        p = pairs[pair]; c, _ = cop(p, Tdrive, TA, Tch)
        need = (1.05 * CPU_W / c) if c > 0 else float('inf')   # 5 % margin
        e = collector_eta(Tdrive + 5, TA, 1000, "ETC")
        area = need / (1000 * e * 0.85) if e > 0 and need < 1e6 else float('inf')
        add(f"Solar ETC {Tdrive} C, sized for CPU cold", Tdrive, need if need < 1e6 else 0, pair, 25, area, 45, 0.6, 0.3)
    rows.sort(key=lambda r: -r[0])
    print("(T_hot = hot-fluid temperature at the bed HX inlet. Condensing vapour: -1 K line drop, +1 K film credit vs water; ASSUME)")
    print("score | config | pair | T_hot C | Tg_min C | COP | cold W | CPU case C | gain vs TS K | GPU die C | extra wall W | W/K | collector m2")
    for r in rows:
        print(f"{r[0]:.2f} | {r[1]} | {r[2]} | {r[3]:.1f} | {r[4]:.1f} | {r[5]:.2f} | {r[6]:.0f} | {r[7]:.1f} | {r[8]:+.1f} | {r[9]:.0f} | {r[10]} | "
              + ("inf" if r[11] == float('inf') else f"{r[11]:.1f}") + f" | {r[12]:.2f}")
    print(f"Baseline: thermosiphon CPU {base_cpu:.1f} C, plain-water GPU die ~{TA + Qg/20 + 0.0575*Qg*DIE_SHARE:.0f} C, ~8 W wall.")
    print("Compressor reference: ~30 W wall for ~95 W cold at 17-20 C, any workload, any room (prior pass).")
    print()

if __name__ == "__main__":
    print(f"Room {TA} C, RH {RH:.0%}, dew point {dew(TA, RH):.1f} C, coolant floor {DEW_FLOOR:.1f} C, approach {APP} K\n")
    sp = single_phase(); tp = two_phase(); pairs_table(); supplemental(); configs(sp, tp)
