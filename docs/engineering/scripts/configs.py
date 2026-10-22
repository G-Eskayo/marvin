"""Hot-components-drive-CPU configurations (follow-up 2026-10-21).

Lumped steady-state model. Run with a Python that has CoolProp:
    python configs.py

Sections:
  1. GPU harvest temperature: max coolant-out temperature that keeps the die in band.
  2. Ideal step-sorbent feasibility (Polanyi potential window) -> minimum drive temperature.
  3. Equilibrium cycle COP for silica gel RD (Chua 2002 Toth isotherm) and a step sorbent.
  4. Config energy balances (A chiller-only, B hybrid booster) vs thermosiphon/AIO baselines,
     with CPU temperature, GPU temperature and wall-power ledger.
  5. Storage sizing (hot tank, cold tank, PCM, dry-bed thermochemical).
  6. Solar top-up collector sizing (flat plate vs evacuated tube).
All assumptions are marked ASSUME; change them at the top.
"""
import math
from CoolProp.CoolProp import PropsSI

K = 273.15
R_W = 461.5  # J/kg/K water vapour

def psat(Tc):
    return PropsSI('P', 'T', Tc + K, 'Q', 0, 'Water')

def hfg(Tc):
    return PropsSI('H', 'T', Tc + K, 'Q', 1, 'Water') - PropsSI('H', 'T', Tc + K, 'Q', 0, 'Water')

# ---------------- ASSUMPTIONS ----------------
R_GPU_BLK = 0.055   # K/W die-to-coolant, full-cover block (ASSUME; ~19 K at 350 W user report)
GPU_CAPTURE = 0.85  # fraction of board power into the coolant (ASSUME)
R_CPU_BLK = 0.10    # K/W case-to-coolant for an old IHS CPU on a water block (ASSUME)
R_TS = (0.08, 0.15) # K/W thermosiphon case-to-ambient (prior pass, sourced)
UA_SECTION = 10.0   # W/K per 120 mm radiator section, moderate fans (~100 W at 10 K, planning figure)
import os
APP_BED = float(os.environ.get("APP_BED", 3.0))       # K, coolant-to-bed / evaporator / condenser approaches (ASSUME)
CP_SORB = 920.0     # J/kg/K silica gel / zeolite
HX_RATIO = 1.0      # kg Al heat-exchanger metal per kg sorbent (ASSUME; good modern beds 0.5-2)
CP_AL = 900.0
REAL_FACTOR = float(os.environ.get("REAL_FACTOR", 0.75))  # real cycle COP / equilibrium COP (ASSUME; finite cycle time, valves, losses)

# ---------------- 1. GPU harvest temperature ----------------
def gpu_harvest():
    print("## 1. Max coolant-out temperature for a die target (R_blk=%.3f K/W)" % R_GPU_BLK)
    print("GPU | board W | die 55 | die 60 | die 65 | die 75 | die 85")
    for name, w in (("GTX 980", 165), ("HD 5870", 188), ("GTX 580", 244), ("GTX 480/780, HD 7970", 250), ("R9 290X", 290)):
        row = [f"{t - R_GPU_BLK * w:5.1f}" for t in (55, 60, 65, 75, 85)]
        print(f"{name} | {w} | " + " | ".join(row))
    print()

# ---------------- 2. Ideal step sorbent window ----------------
def polanyi(T_bed, T_sat):
    """adsorption potential F = R T ln(Ps(T_bed)/P), with P = Ps(T_sat); J/kg"""
    return R_W * (T_bed + K) * math.log(psat(T_bed) / psat(T_sat))

def min_drive_ideal(Ta, Tch):
    """Lowest coolant drive temp at which an ideal step sorbent can cycle.
    Adsorb at bed=Ta+2*APP (radiator+bed approach), P=Ps(Tch-APP).
    Desorb at bed=Tg-APP, P=Ps(Tcond), Tcond=Ta+2*APP."""
    T_ads = Ta + 2 * APP_BED
    T_cond = Ta + 2 * APP_BED
    F_ads = polanyi(T_ads, Tch - APP_BED)
    for Tg10 in range(300, 1200):
        Tg = Tg10 / 10
        if polanyi(Tg - APP_BED, T_cond) >= F_ads * 1.10:  # 10 % margin for step width
            return Tg
    return float('nan')

def window():
    print("## 2. Minimum drive temperature, ideal step sorbent (best case, any material)")
    print("Ta | chilled 15 | 18 | 20 | 22 | 25")
    for Ta in (22, 25, 30):
        print(f"{Ta} | " + " | ".join(f"{min_drive_ideal(Ta, t):5.1f}" for t in (15, 18, 20, 22, 25)))
    print()

# ---------------- 3. Cycle COP ----------------
def q_rd(T, P):
    """RD silica gel, Toth (Chua et al. 2002): kg/kg"""
    K0, Q, qm, t = 7.3e-13, 2.693e6, 0.45, 12  # K0 in 1/Pa
    a = K0 * math.exp(Q / (R_W * (T + K))) * P
    return a / (1 + (a / qm) ** t) ** (1 / t)

def q_step(T, P, F0, qmax=0.28, width=0.08):
    """generic S-shaped sorbent: logistic in Polanyi potential; F0 in J/kg (ASSUME)."""
    F = R_W * (T + K) * math.log(psat(T) / P)
    return qmax / (1 + math.exp((F - F0) / (width * F0)))

def cycle(Tg, Ta, Tch, qfun):
    """Equilibrium two-bed cycle, no heat recovery. Returns (COP_real, dq, cold J per kg sorbent per cycle)."""
    T_ads = Ta + 2 * APP_BED
    T_cond = Ta + 2 * APP_BED
    T_des = Tg - APP_BED
    Te = Tch - APP_BED
    q_hi = qfun(T_ads, psat(Te))
    q_lo = qfun(T_des, psat(T_cond))
    dq = q_hi - q_lo
    if dq <= 0.005:
        return 0.0, max(dq, 0), 0.0
    Qe = dq * hfg(Te)
    qavg = 0.5 * (q_hi + q_lo)
    sens = (CP_SORB + HX_RATIO * CP_AL + qavg * 4186) * (T_des - T_ads)
    Qg = dq * 2.6e6 + sens  # isosteric heat ~2.6 MJ/kg
    return REAL_FACTOR * Qe / Qg, dq, Qe

STEP_LOW = 0.0  # set below

def sorbents():
    # Step location chosen so the material regenerates near 55 C against a 31 C condenser,
    # standing in for FAM-Z01/Z05 / Fujitsu-type low-temperature sorbents (ASSUME).
    global STEP_LOW
    STEP_LOW = 0.5 * (polanyi(31, 15) + polanyi(52, 31))
    sapo = 0.5 * (polanyi(36, 12) + polanyi(77, 36))  # FAM-Z02/SAPO-34-like, ~80 C regeneration
    return {
        "silica gel RD": q_rd,
        "step sorbent, 55 C class (FAM-Z01/Z05-like)": lambda T, P: q_step(T, P, STEP_LOW, 0.20),
        "step sorbent, 80 C class (FAM-Z02/SAPO-34-like)": lambda T, P: q_step(T, P, sapo, 0.28),
    }

def cop_table():
    print("## 3. Real COP (equilibrium x %.2f), Ta=25 C" % REAL_FACTOR)
    for name, f in sorbents().items():
        print(f"### {name}")
        print("Tg | chilled 15 | 18 | 20 | 22")
        for Tg in (45, 50, 55, 60, 65, 70, 80, 90):
            print(f"{Tg} | " + " | ".join(f"{cycle(Tg, 25, t, f)[0]:4.2f}" for t in (15, 18, 20, 22)))
    print()

def capacity():
    print("## 3b. Sorbent per bed for 100 W cold, two-bed, 15 min full cycle, 50 %% kinetic utilisation of equilibrium dq (Ta 25)")
    print("sorbent | Tg | chilled | dq kg/kg | COP | kg per bed")
    for name, f in sorbents().items():
        for Tg, Tch in ((50, 20), (55, 18), (55, 20), (60, 18), (65, 18), (75, 18)):
            cop, dq, Qe = cycle(Tg, 25, Tch, f)
            m = 100 * 900 / (0.5 * Qe) if Qe > 0 else float('inf')
            print(f"{name} | {Tg} | {Tch} | {dq:.3f} | {cop:.2f} | {m:.1f}")
    print()

# ---------------- 4. Configurations ----------------
def solve_chill(Q_cpu, Qg, Tg, Ta, f, UA_amb=0.0, floor=17.0):
    """Chilled-loop temperature T such that Q_cpu = Qcold(T) + UA_amb*(T-Ta)+ (radiator only if T>Ta).
    Chiller throttles to hold the dew-point floor. Returns (T, Qcold)."""
    lo, hi = floor, 90.0
    def net(T):
        cop = cycle(Tg, Ta, T, f)[0]
        Qc = cop * Qg
        rad = UA_amb * (T - Ta) if T > Ta else 0.0
        return Qc + rad - Q_cpu, Qc
    if net(lo)[0] >= 0:  # more cold than needed at the floor -> throttle
        return lo, Q_cpu
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if net(mid)[0] >= 0: hi = mid
        else: lo = mid
    return hi, net(hi)[1]

def configs():
    print("## 4. Configurations, Ta=25 C, dew-point floor 17 C")
    S = sorbents()
    f_low = S["step sorbent, 55 C class (FAM-Z01/Z05-like)"]
    f_sg = S["silica gel RD"]
    Ta = 25
    print("Baselines: thermosiphon case = Ta + %.2f..%.2f*Q; GPU plain water 2x120 rad (UA 20 W/K)" % R_TS)
    for Q in (65, 95, 125):
        print(f"  CPU {Q} W thermosiphon: {Ta + R_TS[0]*Q:.0f}-{Ta + R_TS[1]*Q:.0f} C")
    for P in (165, 250):
        Tc = Ta + GPU_CAPTURE * P / 20
        print(f"  GPU {P} W plain water: coolant {Tc:.0f} C, die {Tc + R_GPU_BLK*P:.0f} C")
    print()
    print("scenario | sorbent | Tg | GPU die | Qgen | CPU W | config | chill T | Qcold | CPU case | gain vs TS mid")
    for P in (165, 250):
        for Tg, f, fn in ((50, f_low, "low-step"), (55, f_low, "low-step"), (60, f_sg, "silica"), (65, f_sg, "silica"), (75, f_sg, "silica")):
            die = Tg + 1 + R_GPU_BLK * P  # coolant out ~= Tg + 1 K pipe loss
            Qg = GPU_CAPTURE * P
            for Q in (65, 95, 125):
                ts_mid = Ta + 0.115 * Q
                for cfg, UA in (("A", 0.0), ("B", 30.0)):
                    T, Qc = solve_chill(Q, Qg, Tg, Ta, f, UA)
                    case = T + R_CPU_BLK * Q
                    if T > 80:
                        print(f"GPU {P} | {fn} | {Tg} | {die:.0f} | {Qg:.0f} | {Q} | {cfg} | runaway | <{Q} | no steady state | FAIL")
                        continue
                    print(f"GPU {P} | {fn} | {Tg} | {die:.0f} | {Qg:.0f} | {Q} | {cfg} | {T:.1f} | {Qc:.0f} | {case:.1f} | {ts_mid - case:+.1f}")
    print()

def power_ledger():
    print("## 4b. Wall-power ledger (ASSUME; PWM pumps at low duty, 120 mm fans ~1.5 W at mid speed)")
    rows = [
        ("Thermosiphon CPU + air GPU (stock)", 0 + 0, "stock GPU blower ~3-6 W counted in both"),
        ("Thermosiphon CPU + GPU plain water (1 pump 5 W, 2 fans 3 W)", 8, ""),
        ("Config A/B chiller: 3 pumps (hot, reject, chilled) 3x5 W, 6 rad fans 9 W, controls+valves 3 W", 27, ""),
        ("Config C adds solar loop pump 5 W + controller 1 W", 33, ""),
    ]
    for r in rows: print(f"  {r[0]}: {r[1]} W {r[2]}")
    print()

# ---------------- 5. Storage ----------------
def storage():
    print("## 5. Storage to bridge 1 h")
    for Qg in (200,):
        E = Qg * 3600
        print(f"  Hot tank for Qgen={Qg} W, 1 h, 10 K swing: {E/4186/10:.0f} kg water; 20 K swing: {E/4186/20:.0f} kg")
    for Qc in (65, 95, 125):
        E = Qc * 3600
        print(f"  CPU {Qc} W 1 h: cold water tank 8 K swing {E/4186/8:.1f} kg; PCM ~18 C at 180 kJ/kg {E/180e3:.1f} kg (+container);"
              f" dry-bed silica gel (dq 0.08) {E/hfg(15)/0.08:.1f} kg; step sorbent (dq 0.18) {E/hfg(15)/0.18:.1f} kg")
    print()

# ---------------- 6. Solar ----------------
def collector(G, Ta, Tm, eta0, a1, a2):
    dT = Tm - Ta
    return max(0.0, eta0 * G - a1 * dT - a2 * dT * dT)

def solar():
    print("## 6. Solar collector output, W/m2 (FP: eta0 .74 a1 3.6 a2 .012 Keymark-type; ETC: Ritter OEM gross .42/.80/.004)")
    cases = (("summer noon", 850, 30), ("spring/autumn", 600, 15), ("winter clear", 400, 0), ("overcast", 150, 10))
    print("case | Tm 60 FP | ETC | Tm 75 FP | ETC | Tm 90 FP | ETC")
    for name, G, Ta in cases:
        out = []
        for Tm in (60, 75, 90):
            out += [f"{collector(G, Ta, Tm, .74, 3.6, .012):4.0f}", f"{collector(G, Ta, Tm, .42, .80, .004):4.0f}"]
        print(f"{name} | " + " | ".join(out))
    print("Area for top-up (Tm 75 C, pipes/HX lose ~15 %):")
    for name, G, Ta in cases:
        fp = collector(G, Ta, 75, .74, 3.6, .012) * 0.85
        et = collector(G, Ta, 75, .42, .80, .004) * 0.85
        s = lambda q, x: f"{q/x:4.1f} m2" if x > 1 else "  n/a"
        print(f"  {name}: 100 W FP {s(100, fp)} ETC {s(100, et)} | 300 W FP {s(300, fp)} ETC {s(300, et)}")
    print()

def topup():
    """Config C. Bed heating runs from T_ads up to T_des. The low part of that ramp
    (bed below GPU coolant - approach) can take GPU heat; the rest must come from solar.
    Integrate sensible + desorption heat along the ramp at condenser pressure (isosteric
    part at evaporator-side uptake first). Silica gel, Ta 25, chilled 18."""
    print("## 6b. Top-up split: share of generator heat the GPU (coolant <= Tgpu) can supply, rest solar")
    f = sorbents()["silica gel RD"]
    Ta, Tch = 25, 18
    T_ads = Ta + 2 * APP_BED; T_cond = T_ads; Te = Tch - APP_BED
    for Tg in (65, 75, 85):
        T_des = Tg - APP_BED
        q0 = f(T_ads, psat(Te))
        tot = 0.0; low = {50: 0.0, 55: 0.0}
        q_prev = q0; T = T_ads; dT = 0.1
        while T < T_des:
            q_now = min(q0, f(T + dT, psat(T_cond)))
            dQ = (CP_SORB + HX_RATIO * CP_AL + q_prev * 4186) * dT + max(0.0, q_prev - q_now) * 2.6e6
            tot += dQ
            for g in low:
                if T + dT <= g - APP_BED: low[g] += dQ
            q_prev = q_now; T += dT
        cop = cycle(Tg, Ta, Tch, f)[0]
        print(f"  Tg {Tg}: COP {cop:.2f}; GPU at 50 C covers {100*low[50]/tot:.0f} %, at 55 C {100*low[55]/tot:.0f} % of Qgen;"
              f" for 100 W cold need Qgen {100/cop if cop else float('nan'):.0f} W -> solar {100/cop*(1-low[55]/tot) if cop else float('nan'):.0f} W (GPU 55 C)")
    print()

if __name__ == "__main__":
    gpu_harvest(); window(); cop_table(); capacity(); configs(); power_ledger(); storage(); solar(); topup()
