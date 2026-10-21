# Heat-driven cooling for old PCs: research pass

Date: 2026-10-21. Method: `research` skill protocol (confidence tiers, two sources per load-bearing claim, single-source claims flagged). Property numbers come from CoolProp 8.0.0. Thermodynamic tables come from a small model script, reproduced in the appendix. Academic search used OpenAlex.

## Summary

**The idea works as physics. It does not work as a way to cool the chip that drives it.** A heat-driven chiller needs a heat source hotter than the load it cools. One CPU cannot be both. Old CPUs make this worse. Their case limits are low (Core 2 Duo E8400 is about 72 °C; Pentium 4 Prescott 115 W parts are 72.8 °C). That caps the drive temperature at about 55–65 °C, and sorption cycles are weakest there.

**Colder is not always better.** Most of the lifetime gain comes from bringing an old chip from about 70 °C down to about 40 °C. That one step is worth roughly 8–10x on Arrhenius-type wear (electromigration, and electrolytic capacitors if they run cooler too). Going below the room's dew point adds condensation risk, insulation work, and high wall power. It buys little extra life on a chip with no turbo. **Recommended target: CPU case at 35–50 °C, with every cold surface at least 3 K above the dew point.** In a 25 °C, 50 % RH room the dew point is 13.9 °C, so keep the coolant at or above about 17 °C.

**Ranked recommendations** (by watts per degree gained, then by how easy it is to build):

1. **Passive two-phase thermosiphon or loop thermosiphon to a large condenser.** Uses 0–2 W of wall power. Gets a 100 W chip to about 35–50 °C. Best watts per degree, and buildable. Use R1233zd(E) (low pressure, A1, GWP 1) or a sealed water or ethanol heat-pipe style loop. Keep some airflow over the VRMs and capacitors.
2. **Good air tower or an AIO.** Uses about 2–8 W. Gets close to option 1. This is the easiest option, but there is nothing novel in it.
3. **Mild sub-ambient chilled water with vapor compression** (a small water chiller, coolant at about 15–18 °C). The model gives about 25–35 W of wall power for 100 W of cooling, and part of that comes back as lower CPU leakage. Use it only if you want to experiment. It needs a dew-point interlock.
4. **Sorption (adsorption/absorption) chiller run on free external heat** (solar, or a separate hot source), feeding the same chilled loop. Aux power is about 10–20 W, an estimate for hobby-scale pumps and fans. The machine is large: about 8–15 kg of silica gel for 8 h of 100 W in an intermittent cycle, or about 0.5–2 kg in a continuous two-bed cycle. It is a great physics project, but a poor way to extend a computer's life.
5. **Self-driven sorption** (CPU or VRM heat drives cold for the same machine). Net CPU gain is about zero. VRM waste heat (about 11–18 W) yields only about 3–9 W of cold. Worth building only as a demo, for example a CPU-heated loop that chills a drink.
6. **Peltier (TEC) and deep phase change.** These cost 30–200 W of wall power. Both run into cold-plate condensation, and deep phase change also brings cold-bug risk on old boards. Last in watts per degree.

**What to measure first:** your real CPU package power (wall meter, idle vs. load), case temperature vs. coolant temperature (this gives your actual thermal resistance), room dew point, and VRM and capacitor temperatures near the socket. These four numbers decide whether anything past option 1 is worth doing.

---

## 1. The viral builds

| Build | Working pair | Heat source | Cycle | What is documented |
|---|---|---|---|---|
| **Crosley Icyball** (1928/29) | NH3 refrigerant, water absorbent | Kerosene stove, about 90 min | Intermittent, cycled by hand, no moving parts | About a cup of kerosene gave about 24 h of cooling. Overheating boils water into the ammonia side. Builders report about 240–250 psi. |
| **DIY Icyball replicas** (Make: / Larry Hall pipe-fitting build; GreenPowerScience solar parabolic version) | NH3-H2O | Fire, or solar concentrator | Intermittent | Pressure-vessel hazard noted in several write-ups |
| **Greenhill Forge "fire and salt" fridge** (Hackaday, 2026-10-18) | Water refrigerant, road-salt (CaCl2) brine absorbent | Wood fire | Absorption, with small electric pumps and fans | Reached about 5 °C at 16 °C ambient in first tests |
| **Activated-carbon/methanol solar ice makers** (Pons & Guilleminot, Boubakri et al.) | AC-methanol | Flat-plate solar collector | Intermittent, daily | More than 4 kg ice per m² per day for 60 % of the year (Agadir). Solar COP about 0.1–0.12. |
| **Zeolite-water self-cooling keg** (Cool-System KEG "CoolKeg") | Zeolite-water under vacuum | Factory oven regeneration | Single-shot | Held lager at about 6 °C for 12 h or more. Regenerated off site. |

**My cross-check:** CoolProp gives ammonia's saturation pressure at a 35–45 °C condenser as 13.5–17.8 bar abs (about 196–258 psia). That matches the "about 240 psi" builder reports, because the condensing pressure, not the generator temperature, sets the pressure.

**Confidence: Established** for Icyball history and operation (Wikipedia, AOGHS, Ingenium museum record). **Speculative** for which video Gil saw. I found several recent YouTube builds, but I could not identify the exact one.

## 2. Working pairs: minimum drive temperature and COP

Rule of thumb for single-effect sorption (my inference from ideal Dühring-line symmetry; standard in absorption texts but not re-verified in this pass): **T_gen,min ≈ T_cond + T_abs − T_evap**. With rejection at 35 °C and a 10 °C evaporator this gives about 60 °C. For ice (−10 °C) it gives about 80 °C. Real machines need another 10–20 K on top.

| Pair | Typical drive | Realistic COP | Runs on 50–90 °C? | Notes / sources |
|---|---|---|---|---|
| **LiBr-H2O** (single effect) | 70–95 °C (catalogue points 88–90 °C) | 0.57–0.7 | Yes, from about 75 °C | Yazaki/Thermax about 0.66–0.70 at 88–90 °C. Measured field COP about 0.57–0.64. Field capacity often 10–25 % below catalogue. Cannot go below about 5 °C (water freezes). Crystallization risk. |
| **NH3-H2O** | about 90–170 °C; higher for ice | about 0.4–0.5 best case | Marginal | Best reported about 0.45 for −10 to 15 °C evaporator (diffusion-absorption pilot). Thesis optimum 170 °C at a 50 °C condenser. Needs a rectifier. High pressure. **Contested/thin** at the low end. |
| **Silica gel-water** | 55–90 °C; multi-stage down to 40–60 °C | 0.3–0.6 (more than 0.6 below 65 °C in a 90 kW three-bed unit) | **Yes, the best fit** | Vendor (Fahrenheit) claims operation from 50 °C. InvenSor near full capacity at 65 °C, COP max 0.72 (vendor). Three-stage mode works at 40–60 °C but COP drops. |
| **Zeolite-water** | full regeneration needs more than 150 °C; partial from about 90 °C | about 0.3–0.5 (ideal 13X about 0.54) | Poorly | Preferred when the source is above 150 °C. Poor bed conductivity means slow cycles. |
| **AC-methanol** | about 80–120 °C (solar collector) | solar COP 0.08–0.12; thermal about 0.3–0.5 | Upper end only | Good for ice because methanol does not freeze. Sub-atmospheric (methanol is 41 mbar at 0 °C). Flammable and toxic. Literature cautions about methanol decomposition at high bed temperatures (not verified this pass). |
| **AC-ammonia** | about 100–200 °C | about 0.2–0.4 | No | High pressure. Faster cycles. Not hobby-friendly. **Single-source / not deeply checked.** |
| **MOFs** (Al-fumarate, MIL-100(Fe), CAU-10, MIP-200) | lowest demonstrated about 65–70 °C (CAU-10, MIP-200); modeled for 50 °C rack water | modeled +59 % capacity over silica gel at 50 °C drive | Yes, at lab or model level | Fraunhofer ISE/TUHH names CPU heat as the target use case. Not available off the shelf for hobbyists. |
| **Ejector** (R245fa and similar) | about 80–100 °C | 0.15–0.45 | Yes, but with a pump | Lower efficiency than absorption in practice (Florence 40 kW prototype). Unstable off design. Needs a feed pump. |

**Confidence:** Established that silica gel-water and LiBr-water are the only mature pairs that run on 60–90 °C water. Established that MOFs are lab-stage. Contested on exact NH3-H2O low-temperature limits. Single-source on vendor claims (Fahrenheit 50 °C, InvenSor 0.72).

## 3. Waste-heat cooling in data centers: what was achieved

- **LRZ CoolMUC-2** (Munich, SorTech/Fahrenheit chillers). 2016 average: about 120 kW of waste heat at 45 °C produced about 50 kW of cold at 21 °C. Electrical COP was about 12. Peer-reviewed numbers: just over 6 kW of electricity removed 95 kW from the machine and produced more than 50 kW of cold water. That implies a thermal COP of about 0.4–0.5. The paper says the system is "at least two times more efficient than a mechanical chiller" for the cold water it needs. **Established** (LRZ docs + SEMI-THERM 2017 paper, DOI 10.1109/SEMI-THERM.2017.7896917).
- **LRZ SuperMUC-NG.** Adsorption plant above 600 kW, driven by warm water up to about 55 °C, 4 MW of warm-water heat removal. **Single source** (trade article, MGT 2021).
- **IBM/ETH Aquasar** (2010). Water at 60 °C in, up to about 65 °C out. Heat recovery efficiency 80 %, exergetic efficiency 34 %. About 9 kW went into **building heating, not chillers**. The group studied adsorption cooling and concluded that space heating gives the highest economic value. **Established** (Zimmermann et al., *Energy* 43 (2012) 237–245, DOI 10.1016/j.energy.2012.04.037; trade press).
- **2024 modeling** (Energy Conversion and Management 118500, DOI 10.1016/j.enconman.2024.118500). Rack outlet 50 °C, rejection 26 °C, cold-aisle 18 °C. A commercial silica gel chiller gave 5.3 kW. MIL-100(Fe) on a flat-tube heat exchanger raises that to 8.5 kW, at a partial electrical EER above 20.
- **TU Darmstadt Lichtenberg II.** 45 °C hot-water cooling used for heating (DOI 10.1002/ese3.633).

**The pattern.** Every real installation uses the chip's heat to cool *something else*: air-cooled IT gear, storage, cold aisles, or buildings. None of them cools the same chip below its own passive temperature. The data-center gains come from replacing mechanical chillers for the remaining cold loads.

## 4. Thermodynamics, worked

Heat-driven Carnot COP = (1 − T_reject/T_gen) · T_cold/(T_reject − T_cold), in kelvin. In a 25 °C room a real rejecter needs about a 10 K approach, so I use T_reject = 35 °C below. With T_reject = 25 °C (the ideal case) the numbers are about 1.5–2x higher; those are in the appendix.

### 4a. Cold produced from a fixed 100 W of drive heat (the trade-off made explicit)

Tg = 80 °C, T_reject = 35 °C:

| Cold side Tc | Carnot COP | Cold @ Carnot | @ 50 % Carnot | @ 30 % Carnot | Heat to reject @ 30 % |
|---|---|---|---|---|---|
| 30 °C | 7.73 | 773 W | 386 W | 232 W | 332 W |
| 20 °C | 2.49 | 249 W | 125 W | 75 W | 175 W |
| 10 °C | 1.44 | 144 W | 72 W | 43 W | 143 W |
| 0 °C | 0.99 | 99 W | 50 W | 30 W | 130 W |
| −10 °C | 0.75 | 75 W | 37 W | 22 W | 122 W |

Tg = 60 °C (about the ceiling an old CPU can supply):

| Tc | Carnot COP | @ Carnot | @ 50 % | @ 30 % |
|---|---|---|---|---|
| 30 °C | 4.55 | 455 W | 227 W | 136 W |
| 20 °C | 1.47 | 147 W | 73 W | 44 W |
| 10 °C | 0.85 | 85 W | 42 W | 25 W |
| 0 °C | 0.59 | 59 W | 29 W | 18 W |
| −10 °C | 0.44 | 44 W | 22 W | 13 W |

Real single-stage sorption machines also have a practical ceiling of about COP 0.6, whatever Carnot allows. **Read the tables this way:** each 10 K colder costs a big share of capacity. Below about 10 °C a 60 °C drive gives tens of watts, not 100.

### 4b. Is net benefit possible vs a good thermosiphon?

- **Passive baseline.** A loop thermosiphon reaches about 0.08–0.15 K/W. A Lisbon R1234ze/R1233zd loop measured 0.081 K/W. A Nokia Bell Labs R1234ze(E) server loop kept the heater at 46 °C at 200 W. For 100 W in a 25 °C room that means a case temperature of about 33–40 °C at zero wall power.
- **Sub-ambient by sorption.** Holding the coolant at 15 °C under a 100 W load needs about 170–230 W of drive heat at 80 °C. The rejecter must then dump about 270–330 W. If the drive heat comes from an electric heater, this is far worse than any compressor (see section 7).
- **Self-driven (the CPU drives its own chiller).** The CPU must sit above Tg + ΔT. Its cold output can only cool *other* parts. **Net gain for the CPU: none.** This is not a material or design limit. It is the second law: one isothermal body cannot both give heat at T_gen and take heat at T_cold < T_gen. Hot-spot gradients across a die are a few kelvin to tens of kelvin, far too small to exploit.
- **Hot drives cold.** VRM losses for a 100 W CPU at 85–90 % efficiency are about 11–18 W (my estimate, assuming typical buck-converter efficiency). At COP 0.3–0.5 that gives **about 3–9 W of cold**, under 10 % of the CPU load. It also forces the VRMs to run *hotter* (at least 70–90 °C to drive a generator). That shortens the life of the parts you most want to protect. PSU internal heat is too cold (about 50–60 °C) and hard to reach. **Verdict: works in principle, loses in practice.**
- **External free heat.** A candle gives about 77 ± 9 W (NPL measured 15–86 W). At an intermittent COP of 0.1–0.2, continuous 100 W of cold needs about 500–1000 W of flame, roughly 7–13 candles. Solar AC-methanol at about 4–6 kg ice per m² per day stores about 1.3–2 MJ per m². That means about 1.5–2.2 m² of collector for 8 h of 100 W cold. **Feasible, but it is a project the size of a roof.**

**Confidence: Established** on the second-law limit and the Carnot numbers (textbook and computed). **Speculative** on the VRM and PSU yields (my estimate).

## 5. Thermosiphon / loop heat pipe fluid selection

Saturation pressures from CoolProp, in bar absolute:

| Fluid | 20 °C | 40 °C | 60 °C | 80 °C | NBP | Safety | GWP100 | Status |
|---|---|---|---|---|---|---|---|---|
| **R1233zd(E)** | 1.09 | 2.16 | 3.92 | 6.59 | 18.1 °C | A1 | about 1 | Available (chiller fluid). **Best all-round pick:** low pressure, non-flammable. |
| **R1336mzz(Z)** (Opteon SF33 family) | 0.60 | 1.28 | 2.45 | 4.30 | 33.5 °C | A1 (non-flammable) | 2 | Sub-atmospheric at room temperature, so air leaks in. Ok for a carefully sealed build. |
| **R1234ze(E)** | 4.27 | 7.67 | 12.77 | 20.08 | −19 °C | A2L (mildly flammable) | <1 | Best performance in IBM modeling (a high-pressure fluid). Needs refrigeration-grade fittings. |
| **R134a** | 5.72 | 10.17 | 16.82 | 26.33 | −26 °C | A1 | about 1300–1530 | Phase-down (Kigali/AIM). Avoid in a new build. |
| **R245fa** | 1.23 | 2.51 | 4.63 | 7.89 | 15 °C | B1 (toxicity class B) | 858 (AR5) / 1030 (AR4) | Being phased down. R1233zd(E) is its drop-in successor. |
| **n-Pentane** | 0.57 | 1.16 | 2.15 | 3.68 | 36 °C | A3 (highly flammable) | about 5 | Cheap, good merit number, fire risk inside a PC. |
| **Isobutane (R600a)** | 3.02 | 5.31 | 8.69 | 13.44 | −12 °C | A3 | about 3 | Fridge refrigerant. Flammable. |
| **Water** | 0.023 | 0.074 | 0.20 | 0.47 | 100 °C | none | 0 | Best merit number by far (5783 vs about 800 for HFOs at 50 °C). Very low vapor density means wide vapor lines. Fine above about 40 °C. Freezes. Standard in heat pipes. |
| **Ethanol** | 0.059 | 0.18 | 0.47 | 1.08 | 78 °C | flammable | about 0 | Good low-temperature heat-pipe fluid. Wide vapor lines needed. |
| **Methanol** | 0.13 | 0.36 | 0.85 | 1.81 | 64.5 °C | flammable, toxic | about 0 | |
| **Ammonia** | 8.57 | 15.5 | 26.1 | 41.4 | −33 °C | B2L (toxic) | 0 | Excellent thermally (space LHPs). Wrong for a PC. |
| **Novec 7000 / 649** | — | — | — | — | 34 / 49 °C | non-flammable, dielectric | about 530–575 / 1 | 3M finished its PFAS manufacturing exit at end of 2025 (3M 10-K/10-Q). Remaining stock only. Alternatives include FK-649-type fluoroketones, AE-3000 (56 °C), and Galden (57 °C and up). No clean match for 7000. |

Figure of merit for condensation, (k³ρ²h_fg/μ)^¼ at 50 °C: water 5783, ammonia 3902, methanol 1884, ethanol 1319, pentane 989, R245fa 872, R134a 821, R1234ze(E) 769.

**Pick:** R1233zd(E) for a refrigerant loop you can see and service. Choose a water or ethanol sealed loop or heat pipe if you want zero-cost fluids and can tolerate wider vapor lines and above-40 °C operation.

**Confidence: Established** for the property values (CoolProp; GWP and safety classes from ASHRAE/UNEP factsheets plus vendor data). **Contested** for R245fa GWP (AR4 vs AR5 values both in circulation). **Single-source** for Novec 7000 GWP 575.

## 6. Practical concerns

- **Condensation.** Dew point at 25 °C is 6.2 °C at 30 % RH, 13.9 °C at 50 %, and 19.1 °C at 70 %. Any coolant below that wets the board. A sub-ambient design needs closed-cell insulation, a dew-point sensor, and an interlock that raises Tc or stops the chiller.
- **Ammonia pressure.** 13.5–17.8 bar at the condenser, and much higher if a generator boils dry or the condenser warms up. NH3 is toxic (B2L). It attacks copper and brass, so it needs steel. A home build is a real pressure vessel, which is why the builder write-ups stress relief valves.
- **Sorption bed size.** For 100 W over 8 h (2.88 MJ), intermittent: about 1.2 kg of water or 7.8–14.6 kg of silica gel, about 2.5 kg of methanol or 14–25 kg of AC, or about 2.3 kg of NH3. These rely on my assumed working swings: silica gel 0.08–0.15 kg/kg, AC-methanol 0.10–0.18. For a continuous two-bed design: SCP is 44–176 W/kg (lab silica gel), so 0.6–2.3 kg of sorbent plus the heat exchanger metal.
- **Cyclic vs continuous.** One bed is intermittent (charge, then cool, like the Icyball). Two or more beds with valve switching give quasi-continuous cold, with 10–40 min cycles. Each switch causes a temperature ripple, so add buffer thermal mass on the cold loop. CoolMUC-2 needed optimization of its operating parameters to reach its numbers.
- **Thermal cycling.** Solder fatigue follows Coffin-Manson. Life scales with the temperature swing ΔT to roughly the −1.9 power (Norris-Landzberg form). A design that swings the chip between cold and warm each cycle can wear joints faster than steady warm running. Steady temperature beats low temperature.
- **Cold bugs.** These matter only far below the band recommended here. Reported cold-boot and cold-bug thresholds run from about −40 °C to −160 °C and vary chip to chip. Old platforms also show PCI, VRM, and board-level cold failures. None of this applies above 0 °C.

## 7. Cold-side target as the variable, and the wall-power ledger

### 7a. Is colder better? Where the returns flatten

| Effect | What changes going colder | Evidence | Where it flattens or reverses |
|---|---|---|---|
| **Leakage power** | At 65 nm leakage doubles per about 45 K; at 32 nm per about 22 K (secondary source). A 45 nm mobile CPU showed about 5 % more total power from 36 to 46 °C. | Electronics Cooling; arXiv 1404.3381 | Assuming 15–35 W of leakage at 70 °C (my assumption; old 90–65 nm desktop parts were leaky), going 70 → 40 °C saves about 6–13 W at 65 nm and 9–21 W at 32 nm. Going on to 20 °C adds only about 2–7 W more. **Most of the saving is gone by 40 °C.** |
| **Electromigration** (Black's eq., Ea about 0.7 eV) | 70 → 60 °C: 2.0x. → 40 °C: 9.7x. → 20 °C: 57x. | TI SNOA994; DoITPoMS; my calculation | Old CPUs rarely die from EM at stock settings. Their failures are mostly capacitors, fans, PSUs, and solder. Huge multipliers on a mode that is not limiting add little. |
| **Electrolytic capacitors** | 2x life per 10 K (Würth SN008, Cornell Dubilier, ROHM, ADI) | Established | Only applies if the *capacitors* get colder. A CPU cold plate does not cool the board caps. Removing a tower fan can make VRM-area caps hotter. |
| **Boost / overclock headroom** | Pre-2008 chips (Pentium 4, Core 2, Athlon 64) have no thermal turbo, so colder gives zero automatic speed gain. Extra overclock headroom needs more voltage, which cuts lifetime. | LN2 overclocking reports | Conflicts with the life-extension goal. |
| **Dew point** | Below about 14–19 °C in a typical room you need insulation and an interlock. | Magnus formula | **This is the hard knee.** |
| **Cold bugs** | Not relevant above 0 °C | Bit-tech, PC Gamer, HWBOT | — |

**Recommended band: CPU case 35–50 °C, coolant at 17–25 °C (always at least 3 K above dew point).** This band captures most of the leakage savings and an 8–10x Arrhenius gain over 70 °C. It needs no insulation, and it is reachable with zero or near-zero wall power. **Confidence: Speculative-to-moderate.** The ingredients are each sourced. The band is my synthesis.

### 7b. Wall power for a 100 W CPU load

Baseline: a stock-type cooler at about 0.40 K/W (assumed), so case about 65 °C in a 25 °C room. "Degrees gained" is case temperature vs. that baseline. Net wall power subtracts leakage savings (mid assumption, 65 nm, 25 W leakage at 70 °C).

| Option | Case temp | Δ vs baseline | Cooler wall power | Leakage saved | **Net W per K gained** | Buildability |
|---|---|---|---|---|---|---|
| Passive loop thermosiphon, large fanless condenser | about 45–50 °C | 15–20 K | 0 W | about 5 W | **≤ 0 (net saving)** | Moderate (charging and sealing) |
| Thermosiphon + 1 slow fan | about 35–40 °C | 25–30 K | about 1.7 W (Noctua NF-A12x25 max 1.68 W) | about 9 W | **≤ 0** | Moderate |
| Good air tower | about 45 °C | 20 K | 1–3 W | about 6 W | **≤ 0** | Easy |
| AIO / custom water to ambient | about 35–40 °C | 25–30 K | about 5–8 W (pump unsourced, fans sourced) | about 9 W | **about 0** | Easy |
| Vapor-compression chilled water, Tc 15 °C | about 25 °C | 40 K | about 30 W model (35 % of Carnot) + fans | about 12 W | **about 0.5** | Hard (dew interlock) |
| Sorption chiller, *free* drive heat, Tc 15 °C | about 25 °C | 40 K | about 10–20 W aux (estimate) | about 12 W | **about 0–0.2** | Very hard, bulky |
| Sorption chiller, *electric* drive heat | about 25 °C | 40 K | about 170–230 W heat + aux | about 12 W | **about 5** | Very hard |
| Peltier/TEC, modest ΔT 12–20 K | about 35–45 °C | 20–30 K | about 30–50 W (COP 2–3.5) | about 8 W | **about 1–2** | Easy, wasteful |
| Peltier, deep sub-ambient (e.g. ML360 Sub-Zero) | near 0 °C at limited load | — | up to about 200 W | — | **more than 2** | Easy, condensation |
| Deep phase change (−25 °C evaporator) | about −15 °C | 80 K | about 80 W model; old Vapochill-era whole PCs drew about 500 W | about 16 W | **about 1** | Hard, cold-bug and condensation |

Sources and assumptions: TEC COP from Electronics Cooling (COP 2–3.5 at ΔT 12–20 K; 120 W CPU → 40 W input). Vapochill ratings 130–240 W at −25.5 °C (HotHardware); Guru3D measured about 500 W whole-PC draw. Vapor-compression wall power is modeled with a 45 °C condenser, which is an inference. AIO pump power is not sourced in this pass.

## 8. Bottom line, ranked

1. **Loop thermosiphon on R1233zd(E), or a sealed water or ethanol loop, to a large passive condenser.** Lowest watts per degree. No moving parts. In the right band. Add a small fan for board airflow over the VRM and capacitors.
2. **Recap and improve airflow before anything exotic.** Capacitors are the usual cause of death in old PCs, and their life doubles per 10 K.
3. **Mild chilled water (≥17 °C) from a small compressor chiller.** Only if you want sub-ambient as a hobby. The dew-point interlock is mandatory.
4. **Sorption demonstrator run on solar or a separate hot source**, cooling a drink or a sensor rather than the CPU. This is the faithful "viral build" route. Start with silica gel-water (low pressure, benign, runs on 60–80 °C water). Avoid ammonia.
5. **Self-driven CPU or VRM sorption.** Only to see the second law in action.

**What to measure first:**
1. Wall power at idle and under load (a kill-a-watt meter). Load minus idle approximates CPU plus VRM heat.
2. Case and core temperature vs. coolant or heatsink temperature at a known load. This gives the real thermal resistance R.
3. Room temperature and RH, for the dew point.
4. Thermocouples on VRM heatsinks and on the capacitors near the socket.
5. For a thermosiphon prototype: evaporator wall temperature vs. power from 20 to 150 W, to find dry-out.

## Where this could be wrong

- The leakage fractions for 90–65 nm desktop parts are assumed (15–35 W at 70 °C), not measured. Measure idle power at two temperatures to calibrate.
- The doubling interval for leakage (45 K at 65 nm) comes from one secondary article.
- Hobby-scale sorption aux power and real COP at 100 W scale are unknown. Every published number is for kW-scale machines. Small machines usually do worse.
- I could not identify the specific viral video Gil saw.

## Sources

- Icyball: https://en.wikipedia.org/wiki/Icyball ; https://aoghs.org/products/icy-ball-kerosene-ice-maker/ ; https://collection.ingenium.ca/item/2007.0223.001 ; https://makezine.com/article/science/how-to-build-your-own-icyball/ ; https://www.youtube.com/watch?v=V3abp-Tw6sI
- Greenhill Forge salt fridge: https://hackaday.com/2026/10/18/off-grid-refrigeration-using-fire-and-salt/ (video https://www.youtube.com/watch?v=3sv7TBtHcgo)
- AC-methanol solar ice makers: https://iifiir.org/en/fridoc/experimental-study-of-adsorptive-solar-powered-ice-makers-in-agadir-95142 ; Li & Sumathy review, DOI 10.1016/S1364-0321(01)00004-1
- CoolKeg: https://www.morningadvertiser.co.uk/Article/2003/05/29/self-cooling-keg-is-a-chilling-reminder ; https://iifiir.org/en/fridoc/application-of-the-zeolite-water-adsorption-technology-for-beer-cooling-119122
- Absorption review: Srikhirin et al. 2001, DOI 10.1016/S1364-0321(01)00003-X
- LiBr chillers: https://task48.iea-shc.org/Data/Sites/6/documents/events/meeting-08/2015_03_24_helm_a4-pump-efficiency-and-adaptability.pdf ; https://iifiir.org/en/fridoc/experimental-evaluation-of-a-direct-air-cooled-lithium-bromide-water-135260 ; https://www.ki-portal.de/wp-content/uploads/2014/02/KI_2014_01-02_Wissenschaft_Lohmann.pdf
- NH3-H2O: https://iifiir.org/en/fridoc/absorption-cooling-by-sun-and-waste-energy-126762 ; https://repository.nirmauni.ac.in/jspui/bitstream/123456789/8383/1/TT000078.pdf
- Silica gel: https://iifiir.org/en/fridoc/waste-heat-driven-dual-mode-multi-stage-multi-bed-regenerative-122236 ; https://inis.iaea.org/records/rjc4b-mss98 ; https://www.green-cooling-initiative.org/network/best-practice/product-the-ltc-30e-plus-one-of-the-most-efficient-chillers-on-the-market ; https://fahrenheit.cool/en/?p=2619 ; https://erjm.journals.ekb.eg/article_66901_9fb5377841315bdb91f38713aff0af4b.pdf
- Zeolite: https://iifiir.org/en/fridoc/thermodynamic-limits-to-thermal-regeneration-in-adsorption-cooling-128979 ; https://iifiir.org/en/fridoc/the-effect-of-operating-conditions-on-the-performance-of-zeolite-water-124598
- MOFs: https://publica.fraunhofer.de/handle/publica/263192 (Energies 2020, DOI 10.3390/en13113003) ; https://pmc.ncbi.nlm.nih.gov/articles/PMC6616384 ; DOI 10.1016/j.applthermaleng.2016.01.129 ; DOI 10.1016/j.enconman.2024.118500
- Ejector: Besagni et al. 2016 review, DOI 10.1016/j.rser.2015.08.059 ; https://flore.unifi.it/handle/2158/1170364 ; https://acikerisim.sdu.edu.tr/handle/123456789/64222
- LRZ: https://doku.lrz.de/coolmuc-2-11484376.html ; DOI 10.1109/SEMI-THERM.2017.7896917 ; https://www.tga-praxis.de/sites/default/files/public/data-fachartikel/MGT_2021_06_Warmwasserkuehlung-fuer-Hoechstleistungsrechner_36-37.pdf
- Aquasar: DOI 10.1016/j.energy.2012.04.037 ; https://www.datacenterknowledge.com/supercomputers/ibm-s-hot-water-supercomputer-goes-live
- Darmstadt: DOI 10.1002/ese3.633
- Thermosiphons: https://fenix.tecnico.ulisboa.pt/downloadFile/1126295043838640/Resumo%20alargado.pdf ; https://advancedmaterials.honeywell.com/content/dam/sustainability/en/documents/document-lists/technical/experimental-characterization-of-a-server-level-thermosyphon-for-high-heat-flux-dissipations-amalfi-et-al-nokia-paper-2020.pdf ; https://research.ibm.com/publications/two-phase-cooling-system-performance-under-different-operating-scenario ; DOI 10.1016/j.applthermaleng.2017.02.073
- Refrigerant data: https://www.ashrae.org/file%20library/technical%20resources/bookstore/factsheet_ashrae_english_november2022.pdf ; https://drawdown.org/explorer/deploy-alternative-refrigerants/figure-a1 ; https://www.honeywell-refrigerants.com/india/product/genetron-245fa/ ; https://www.energy.kth.se/applied-thermodynamics/news/low-gwp-news/r1336mzz-z-ett-nytt-hogtemperaturkoldmedium-med-bra-egenskaper-1.501202
- Novec / 3M PFAS exit: https://www.sec.gov/Archives/edgar/data/66740/000006674026000014/mmm-20251231.htm ; https://alliancechemical.com/blogs/articles/post-novec-immersion-fluid-alternatives-2026 ; https://d-central.tech/immersion-cooling-fluids/
- CPU specs: https://techpowerup.com/cpudb/467/core-2-duo-e8400 ; https://www.tomshardware.com/reviews/intel-stakes-vision-pc-future-775-launch%2C830-13.html
- Capacitor life: https://www.we-online.com/components/media/o173043v410%20SN008a%20EN.pdf ; https://www.analog.com/en/technical-articles/ensure-long-lifetimes-from-electrolytic-capacitors-a-case-study-in-led-light-bulbs.html ; https://micro.rohm.com/en/techweb/knowledge/acdc/acdc_sr/acdc_sr01/3177
- Electromigration: https://ti.com/lit/pdf/snoa994 ; https://doitpoms.ac.uk/tlplib/electromigration/summary.php
- Solder fatigue: https://en.wikipedia.org/wiki/Solder_fatigue ; https://metricgate.com/calculator/norris-landzberg-thermal-cycling
- Leakage vs temperature: https://www.electronics-cooling.com/?p=9174 ; https://arxiv.org/pdf/1404.3381
- Cold bugs: https://www.pcgamer.com/uk/overclocking-a-cpu-to-7-ghz-with-the-science-of-liquid-nitrogen ; https://bit-tech.net/reviews/tech/aocc-2008/4/ ; https://community.hwbot.org/topic/171525-godavari-7870k-and-cold-bug
- TEC: https://www.electronics-cooling.com/2005/08/latest-developments-in-thermoelectrically-enhanced-heat-sinks/ ; https://www.kitguru.net/components/cooling/luke-hill/cooler-master-ml360-sub-zero-core-i9-at-0c-200w-cooler/
- Phase change: https://hothardware.com/reviews/vapochill-lightspeed-ac ; https://www.guru3d.com/articles-pages/asetek-vapochill-ls-review-(sub-zero-cooling),17.html
- Fan power: https://pokde.net/review/noctua-nf-a12x25-fan-review-to-be-seen-and-not-heard
- Candle heat: https://www.npl.co.uk/skills-learning/measurement-at-home/candle-power ; https://www.thenakedscientists.com/articles/questions/how-many-watts-burning-candle

## Appendix: reproduction

The scripts live in the session scratchpad: `calc.py` (CoolProp pressures, merit numbers, dew points, Carnot grid) and `model.py` (fixed-drive tables, leakage, Arrhenius, bed sizing). Carnot grid at T_reject = 25 °C, for Tc = 10/15/20 °C: Tg 70 °C gives 2.48/3.78/7.69; Tg 80 °C gives 2.94/4.49/9.13; Tg 90 °C gives 3.38/5.16/10.49.
