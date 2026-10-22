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
   **GPU-driven hybrid (follow-up, config B):** GPU heat drives a chiller that boosts the CPU loop. Best case it makes the CPU about 9 K colder than a thermosiphon, only while gaming, in a room at 25 °C or cooler, with excellent heat exchangers. It costs about +19 W (about 2 W/K at best, 5–20 W/K realistic). The GPU must run 15–25 K hotter (die 70–75 °C vs 49 °C on plain water). Under the no-sacrifice rule (GPU die ≤ 65 °C, harvest ≤ 50 °C) the cycle sits at its threshold and does not reliably run. A demo only. See the follow-up section.
6. **Peltier (TEC) and deep phase change.** These cost 30–200 W of wall power. Both run into cold-plate condensation, and deep phase change also brings cold-bug risk on old boards. Last in watts per degree.

**Follow-up (GPU as the hot source): the ranking is unchanged.** Thermosiphon CPU plus plain-water GPU already puts both chips in their best bands (CPU case 35–45 °C, GPU die 45–55 °C) for about 8 W. Every chiller variant pushes past the point where colder stops buying life or clocks. Note: AQSOA FAM-Z02 regenerates at about 80–90 °C. The 55 °C-class sorbents are FAM-Z01/Z05 and Fujitsu's.

**Follow-up (fluids and working pairs beyond water): the ranking is unchanged.** No coolant, refrigerant or working pair escapes the limits. Two limits bind, and neither belongs to a fluid. (1) The die's conduction stack (silicon, TIM, plate base) caps heat delivery from a 65 °C die at about 54–57 °C for *any* pickup fluid. Boiling refrigerants match water within about 1 K. The 58–62 °C harvest needs a 67–74 °C die at 250 W. (2) Every practical chiller pair needs at least 56–62 °C hot fluid in a 25 °C room (step zeolites best) and at least 67 °C in a 30 °C room (Dühring threshold, fluid-independent to first order). The useful levers are a liquid-metal TIM (+2.5 K) and a lower GPU power limit, not the coolant. Compact solar (0.6–0.95 m² evacuated tube) plus silica gel–water gives +8–10 K on the CPU at about 3 W/K. That ties a compressor, but only in daylight. See "Fluid and working-pair options" at the end.

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

---

## Hot-components-drive-CPU configurations (follow-up 2026-10-21)

**Question.** The first pass only tried VRM and PSU heat as the "hot" source. The GPU is the biggest heat source in an old gaming PC. Can GPU heat (plus other hot parts, plus solar top-up) drive a sorption chiller that cools the CPU, and can the system put *both* CPU and GPU in their best bands? Gil's added constraint: **no part is sacrificed for the whole.** The GPU must stay in its own healthy band. Model: `scripts/configs.py` (CoolProp 8.0.0, lumped steady state; assumptions flagged `ASSUME` at the top of the file).

### Short answer

- **Under the no-sacrifice rule the GPU can only give heat at about 45–55 °C.** At that temperature a sorption chiller is on the edge of working. It works with tight heat exchangers in a 22–25 °C room. It does not work at 30 °C.
- **Best case: the CPU gets about 5–10 K colder than on a thermosiphon** (case about 24–32 °C vs 32–39 °C), only while both chips are loaded (gaming). Cost: about 19 W more wall power than "thermosiphon CPU + plain water GPU". That is **about 2 W per kelvin at best, 5–20 W/K in realistic cases.** The thermosiphon is at or below 0 W/K. A small compressor chiller costs about 2–3 W/K against the same thermosiphon baseline. It matches the GPU-driven best case and beats every realistic case, at any workload.
- **To harvest the heat, the GPU must run 15–25 K hotter than it would on a plain water loop.** A plain loop already holds a 250 W GPU at about 49 °C, which is in its best band. So harvesting trades GPU temperature for CPU temperature. Under Gil's rule that is a sacrifice, even if a small one.
- **Verdict: no change to the ranking.** The GPU-driven chiller is a working physics demo. It is not a better cooler. Solar-only drive (no GPU harvest) is the cleaner version, at roof scale.

### 1. Heat-source inventory (about 2008–2016 hardware)

| Source | Heat under load | Rated / designed max | Healthy harvest temp (coolant out) | Worth plumbing? |
|---|---|---|---|---|
| **GPU** (GTX 480 250 W, GTX 580 244 W, GTX 780 250 W, GTX 980 165 W, HD 5870 188 W, HD 7970 250 W, R9 290X about 290 W) | 165–290 W board power; about 85 % reaches a full-cover block (ASSUME) | GTX 480: 105 °C limit, ran about 95–97 °C on the stock cooler. R9 290X: holds 95 °C by design (PowerTune). Kepler/Maxwell Boost 2.0 targets 80 °C. | **41–56 °C** for a die at 60–65 °C (table below) | **Yes, the only one.** High power, liquid-cooled anyway. |
| CPU VRM (motherboard) | about 11–18 W for a 100 W CPU (prior pass, estimate) | MOSFETs often 100–125 °C. Nearby electrolytic capacitors are the weak part. | Running them hotter shortens capacitor life (2x per 10 K) | No. Small, and it fails the no-sacrifice rule. |
| GPU VRM + VRAM | Included in board power; already on a full-cover block | GDDR5 max operating about 95 °C (Micron Tj 100 °C, via IgorsLab, **single source**) | Same loop as the GPU | Already counted |
| Northbridge / IOH (X38/X48/X58 class) | About 20–30 W (Intel datasheet class, **not re-verified**) | About 100 °C class | Hard to block; low watts | No |
| PSU | 75–90 W of loss at 500 W output and 85 % efficiency | Internals about 50–70 °C; air-cooled, sealed box | Not reachable without opening a mains device | **No** (safety) |
| HDDs | 5–10 W each | About 55–60 °C operating max; failure rates rise past about 45 °C (Pinheiro et al., FAST 2007) | Must stay cool | No |

**Maximum coolant-out temperature that keeps the die at a target** (die-to-coolant R = 0.055 K/W for a full-cover block; derived from about 19 K over coolant at 350 W, **single user report, ASSUME**):

| GPU | Board W | Die 55 °C | Die 60 °C | Die 65 °C | Die 75 °C |
|---|---|---|---|---|---|
| GTX 980 | 165 | 46 | 51 | 56 | 66 |
| HD 5870 | 188 | 45 | 50 | 55 | 65 |
| GTX 580 | 244 | 42 | 47 | 52 | 62 |
| GTX 480 / 780, HD 7970 | 250 | 41 | 46 | 51 | 61 |
| R9 290X | 290 | 39 | 44 | 49 | 59 |

Pre-2019 GPUs report no hotspot sensor. Modern cards show hotspot 10–20 K above the edge reading, so keep a margin.

**Plumbing limit.** The water-cooling D5 pump variants are listed at **60 °C maximum liquid temperature**. The brass-housed industrial D5 is rated 95 °C, while plastic-housed versions are rated 60 °C (Goulds/Xylem catalog). Thermaltake's acrylic reservoirs are rated **55 °C**. A GPU loop running 55–60 °C to drive a chiller sits at or past the limit of normal PC parts. Use metal or POM tops, brass pumps and EPDM tubing (my recommendation; PETG and PVC soften at these temperatures, **not verified this pass**).

### 2. The GPU as a load: its best band

The rule from section 7a applies to GPUs too: colder helps up to a point, then flattens.

| Effect | What changes going colder | Where it flattens |
|---|---|---|
| **Boost clocks** | Fermi (GTX 480/580) has no boost; temperature does not change clocks. Kepler/Maxwell (GPU Boost 2.0, GTX 780/980) hold full boost below the 80 °C target. Pascal (Boost 3.0, 2016) drops one 13 MHz bin about every 5 °C past about 55 °C (**forum source**). AMD Hawaii holds full clocks until 95 °C. | Below about 55 °C, no era gains clocks from more cooling. |
| **Leakage power** | R9 290X: about 25 W less at 65 °C than at 95 °C (forum estimate, **single source**; direction backed by water-cooling reviews). | Most of the saving is gone by 50–60 °C. |
| **VRAM, VRM, capacitors** | GDDR5 limit about 95 °C. Board capacitors double their life per 10 K. | A full-cover block keeps these within 10–25 K of the coolant. |

**Recommended GPU band: die 45–65 °C.** That gives full clocks on every era, most of the leakage saving, and VRAM far from its limit. **A plain water loop to ambient already does this:** a 250 W GPU on two 120 mm radiator sections gives about 36 °C coolant and 49 °C die, at about 8 W of pump and fan power. A GPU heat-pipe or thermosiphon cooler does about the same at 0–3 W.

**The conflict.** To drive a chiller, GPU coolant must leave at 50–60 °C. That puts the die at 65–75 °C. It is within the band's upper edge or just past it. On Pascal it costs about 2–4 boost bins (26–52 MHz, about 2–3 %). On Hawaii it costs perhaps 10–15 W of extra leakage. On Fermi, Kepler and Maxwell clocks do not change. **It always runs the GPU 15–25 K hotter than the same loop could hold it.** That is the price of harvest.

### 3. Low-temperature sorbents: what really drives at 50–60 °C

| Sorbent | Lowest drive reported | Source / confidence |
|---|---|---|
| Fujitsu adsorbent (2011, unnamed) | **55 °C** waste water (CPU water cooling), chilled water 15–18 °C, cold up to 60 % of heat input | Fujitsu via phys.org (**vendor claim**) |
| AQSOA FAM-Z01 / FAM-Z05 | Regeneration about 55 °C; FAM-Z05 regenerates lower than Z02 and Z01 | KRISO 2021; J. Chem. Eng. Japan 2007 (two sources, **Established**) |
| **AQSOA FAM-Z02** (= SAPO-34) | Regeneration about 80–90 °C; a "low" temperature only next to classic zeolites | SAPO-34 modelling paper (about 80 °C); UOP patent isotherms (desorbed at 90 °C); ACS Omega 2026. **Correction to the brief:** Z02 is *not* a 55–60 °C sorbent. Z01/Z05 are. |
| EMM-8 (SFO aluminophosphate) | Regenerates at 65 °C; potential COP 0.85 at 63 °C drive | Nature Comms 2022, DOI 10.1038/s41467-021-27883-4 (lab, **single source**) |
| CAU-10, MIP-200, Al-fumarate (MOFs) | About 65–70 °C; modelled for 50 °C rack water | Prior pass, section 2 (lab stage) |
| RD silica gel | Commercial machines quote 50–65 °C | Fahrenheit (vendor), InvenSor LTC 10 at almost full capacity at 65 °C (vendor) |
| LiBr-H2O | About 75 °C and up | Prior pass. **Out:** cannot run on no-sacrifice GPU heat. |

**Material-independent limit.** An ideal step sorbent can cycle only when the desorption-side adsorption potential exceeds the adsorption-side potential. `configs.py` section 2 computes the minimum drive temperature for a perfect sorbent. "Approach" means the temperature drop across each heat exchanger.

| Room | Approach per HX | Chilled 15 °C | 18 °C | 20 °C | 22 °C |
|---|---|---|---|---|---|
| 22 °C | 3 K (excellent) | 50 | 46 | 44 | 41 |
| 25 °C | 3 K | 57 | 53 | 50 | 48 |
| 25 °C | 4 K | 64 | 60 | 57 | 55 |
| 25 °C | 5 K (typical hobby) | 71 | 67 | 64 | 62 |
| 30 °C | 3 K | 68 | 64 | 62 | 59 |

**Read it this way.** With no-sacrifice harvest at 50–55 °C, you need a room at or below 25 °C, very tight heat exchangers, and chilled water at 18–22 °C. One bad heat exchanger or a warm summer room shuts the cycle off. This is the core problem. **Confidence: Established** (physics; Dubinin/Polanyi framework). The approach values are mine.

### 4. Cycle hardware at 100–200 W

- **Two-bed sorbent mass** (`configs.py` 3b; 15 min cycle, 50 % kinetic use): RD silica gel at Tg 60 °C, chilled 18 °C gives about **0.7 kg per bed for 100 W** with tight HX. At Tg 55 °C it is 1.2 kg. At Tg 50 °C it is 2.2 kg, and with 5 K approaches the cycle does not run. Add 0.5–2 kg of aluminium HX per kg of sorbent, plus evaporator, condenser and vacuum shell.
- **Valves.** Each bed needs a vapour valve to the condenser and one to the evaporator (4 passive flap valves work, as in the compact car chiller). Hot and cold water switching needs 4–8 motorised ball valves, which draw power only while switching.
- **Closest real compact unit.** A 40 L automotive adsorption chiller with vapour flap valves gave **about 1.5 kW at 95 °C drive, 90 s cycle** (Appl. Therm. Eng. 2017, DOI 10.1016/j.applthermaleng.2017.07.130). That drive temperature is far above GPU harvest. The smallest commercial units are kW-scale: InvenSor LTC 10 (10 kW), SorTech ACS 08 (8 kW). Neither is a PC part. Coolar (Berlin, silica gel and water, fridge-scale, solar or waste heat) is the nearest 100 W-class product; its product status is **unverified**.
- **Size vs a PC case** (my estimate, **Speculative**): about 10–20 L and 8–15 kg for 100–200 W of cold, including the vacuum vessel. That is a second box about the size of a small PC tower, beside or under the case.
- **Absorption (LiBr):** no unit exists under kW scale. It needs vacuum and has crystallisation risk. Ruled out at this scale.

### 5. Energy balance (Ta 25 °C, dew floor 17 °C, `configs.py` section 4, hybrid config B, 4 K approach unless noted)

Baselines: thermosiphon CPU case = 25 + (0.08…0.15) × Q. That gives 30–35 °C at 65 W, 33–39 °C at 95 W, 35–44 °C at 125 W. GPU on plain water: die 41 °C at 165 W, 49 °C at 250 W.

| GPU harvest (250 W board, 212 W to coolant) | GPU die | CPU 65 W case (gain) | CPU 95 W case (gain) | CPU 125 W case (gain) |
|---|---|---|---|---|
| 50 °C, best low-T sorbent | 65 °C | 34 (none, cycle off) | 38 (none) | 42 (none) |
| 55 °C, FAM-Z01/Z05-class | 70 °C | 27 (+5) | 32 (+4) | 38 (+1) |
| 60 °C, silica gel | 75 °C | 24 (+9) | 29 (+7) | 38 (+2) |
| 65 °C, silica gel | 80 °C | 24 (+9) | 27 (+9) | 38 (+2) |
| Same at 3 K approaches, 55 °C harvest | 70 °C | 24 (+9) | 27 (+9) | 30 (+10) |
| Same at 5 K approaches, 60 °C harvest | 75 °C | 29 (+4) | 35 (+1) | 39 (+1) |

With a 165 W GPU (GTX 980 class, 140 W to coolant) the cold covers only about 60–90 W. Gains drop to about +1 K at 95–125 W of CPU load.

- **Gains cap at about 9–10 K.** The dew-point floor (coolant at 17 °C or above) plus the CPU block's own resistance limit them. Real chips then sit at about 24–30 °C case. The prior pass already showed little life or speed return below about 35–40 °C on old CPUs.
- **Rejection.** The total heat to ambient is unchanged: Q_GPU + Q_CPU + pumps and fans. The chiller moves heat. It does not destroy it. But the rejection must happen at about Ta + 5 K, not at the GPU loop's comfortable Ta + 10–15 K. UA ≈ (212 + 95) / 5 ≈ **60 W/K, about six 120 mm radiator sections** (two 360 mm radiators). Plain water needs about two. Planning figure: about 100 W per 120 mm section at 10 K, moderate fans (radiator calculator; forum tests give up to about 200 W at high RPM).
- **Wall power** (`configs.py` 4b, ASSUME): thermosiphon CPU + plain-water GPU is about 8 W. The chiller adds hot, reject and chilled pumps (3 × about 5 W), 6 radiator fans (about 9 W) and controls (about 3 W), for **about 27 W total, about +19 W.**

| Case (95 W CPU, gaming) | Gain vs thermosiphon | Extra wall W | **W per K** |
|---|---|---|---|
| Thermosiphon (baseline) | 0 | 0 | ≤ 0 |
| Small compressor chiller, 17 °C coolant (prior pass) | about 10–12 K | about 30 W, minus about 3 W of leakage savings | about 2–3 (the prior pass's 0.5 was measured against a stock cooler, not a thermosiphon) |
| GPU-driven, optimistic (3 K HX, 55–60 °C harvest) | about 9 K | about 19 W | **about 2** |
| GPU-driven, middle (4 K HX, 55 °C harvest) | about 4 K | about 19 W | **about 5** |
| GPU-driven, no-sacrifice strict (die ≤ 65 °C, 50 °C harvest) | 0 | about 19 W | **∞ (cycle off)** |

### 6. The load-correlation problem

| Workload | GPU heat | CPU cold demand | What happens |
|---|---|---|---|
| **Gaming** (both loaded) | 150–290 W | 65–125 W | The only matched case. Table above applies. |
| **GPU compute** (Gil's plan: GPU full, CPU light 20–40 W) | Plenty | Small | Most of the cold has no useful load. It cannot usefully cool the GPU itself: that is the self-driven second-law case from 4b. Surplus cold goes to the room or to a drink. |
| **CPU-only** (GPU idle 10–50 W, card-dependent estimate) | Too cold, too little | Full | The chiller stops. **Config A (chiller as the CPU's only path) runs away and overheats the CPU.** It needs an ambient path. This alone rules out config A. |

**Bridging storage** (1 h, `configs.py` 5):

| Store | For CPU 95 W, 1 h | Notes |
|---|---|---|
| Cold water tank, 8 K swing | about 10 kg | Simple, bulky, must be insulated |
| PCM at about 18 °C (assume about 180 kJ/kg; RT18-class melts at 18 °C, latent heat **not verified**) | about 2 kg + container | Low conductivity (about 0.27 W/m/K liquid) needs fins |
| **Dry sorbent bed** (charged during gaming) | about 1.7 kg silica gel, 0.8 kg step sorbent | **Best:** stores "cold potential" with no standby loss, and it is the chiller's own hardware run as an intermittent cycle |
| Hot tank for Q_gen 200 W, 10–20 K swing | 9–17 kg water | Pointless here: GPU heat is low grade, and a hot tank loses its useful top degrees first |

**Deliberate GPU heat dump.** Run the GPU only to make heat: 250 W of electricity gives about 212 W of heat and about 100–125 W of cold (COP 0.5–0.6, optimistic). That is about 2–2.5 W of electricity per W of cold. A small compressor uses about 0.3. **It is roughly 7–8x worse than a compressor.** Do it only if the GPU compute is wanted anyway.

**Fallback mode.** The CPU must always have an ambient path (thermosiphon or radiator). The chiller can only be a booster on top (config B).

### 7. Solar or external top-up

**Collector output** (W/m², `configs.py` 6). Flat plate: η0 0.74, a1 3.6, a2 0.012 (Solar Keymark annexes give η0 0.69–0.77, a1 3.5–3.8). Evacuated tube: Ritter OEM 21 datasheet, gross area, η0 0.42, a1 0.80, a2 0.004 (**single datasheet**).

| Sky | Flat plate at Tm 75 °C | Evac. tube at Tm 75 °C | Area for 100 W top-up | Area for 300 W |
|---|---|---|---|---|
| Summer noon (850 W/m², 30 °C) | 443 | 313 | FP 0.3 m², ETC 0.4 m² | FP 0.8, ETC 1.1 m² |
| Spring/autumn (600, 15 °C) | 185 | 190 | 0.6 m² | 1.9 m² |
| Winter clear (400, 0 °C) | 0 | 86 | ETC 1.4 m² | ETC 4.1 m² |
| Overcast (150) | 0 | 0 | none | none |

(Area includes about 15 % pipe and HX loss, ASSUME.)

**"GPU pre-heats, solar tops up" works less well than it sounds.** A bed heats from about 31 °C up to the drive temperature. GPU coolant at 50 °C can only supply the low part of that ramp, mostly sensible heat: **about 7–10 % of the generator heat for silica gel.** At 55 °C it supplies 31–47 % (`configs.py` 6b). So for 100 W of cold at 75 °C drive (Q_gen about 170 W), the sun must still supply about 90–120 W, and the GPU is again forced to 55 °C coolant. **Cleaner: leave the GPU on its own ambient loop and drive the chiller from solar alone.** Then the cold can serve both CPU and GPU. For about 300 W of cold (95 W CPU + 212 W GPU) you need about 500 W at 75 °C: about 1.3 m² of flat plate at summer noon, more than 2.5 m² in spring, with storage for evening use (about 86 kg of water for 4 h on an 85→65 °C swing). This is a roof project.

**Practicalities (honest):** the collector is outdoors and the PC is indoors. That means a glycol loop through a wall, a plate heat exchanger (glycol never enters the PC loop), and freeze protection (glycol or drain-back). It also needs **stagnation protection**: a flat plate with no flow goes well above 100 °C, which would wreck 60 °C-rated PC parts. So you need a dump or bypass valve and a high-limit cutoff. PC gaming happens mostly in the evening, when the sun is down, so the storage is not optional.

### 8. Configuration sketches

```
(A) Chiller-only CPU path                           FAILS: no ambient fallback
  GPU blk ==hot 55C==> [GEN beds] --cond/abs--> [RADIATOR ~6x120]
  CPU blk <==chilled 17-22C== [EVAP] ; GPU idle => CPU loop runs away

(B) Hybrid booster (recommended form of the idea)
  GPU blk ==hot 55-60C==> [GEN beds] ==> [RAD ~6x120 shared, Ta+5K]
  CPU blk --> [CPU radiator / thermosiphon to ambient] --> [EVAP trim HX] --> CPU blk
  Bypass valve: GPU loop -> RAD directly when GPU is idle or cold; chiller off.
  Dry-bed storage: charge beds while gaming; discharge for ~1 h after.

(C) Solar-driven, GPU and CPU both on chilled booster
  Roof collector (glycol) --[stagnation dump]--> plate HX --> hot tank 80C --> [GEN beds]
  GPU blk and CPU blk --> own ambient radiators --> [EVAP trim HX] (both chips cooled)
  Optional: GPU preheats tank return via a 45-55C HX only when GPU is loaded (~30 % of Q_gen at best)
```

| Config | CPU (95 W) | GPU (250 W) | Clocks | Extra wall W | W/K (CPU) | Buildability |
|---|---|---|---|---|---|---|
| **Baseline:** thermosiphon CPU + plain water GPU | 33–39 °C | 49 °C | Full on all eras | 0 (8 W total) | ≤ 0 | Moderate |
| A chiller-only | 27 °C *when gaming*; runaway when not | 70–75 °C | Pascal −2 to −4 bins | +19 | — | Unsafe |
| **B hybrid, GPU-driven** | 27–35 °C (gaming), baseline otherwise | 70–75 °C (15–25 K worse) | Pascal −2 to −4 bins; Hawaii +10–15 W leakage | +19 | 2–20 | Hard |
| C solar-only drive, cold to both | 27–30 °C (sun or storage) | about 35–40 °C (gain about 10 K) | No gain below 55 °C | +25 + roof | about 1–3 (heat is free) | Very hard |
| Small compressor chiller (prior pass) | about 27 °C | about 35–40 °C | Same | about +30 | about 2–3 | Moderate (dew interlock) |

### 9. Verdict

- **On CPU temperature:** config B beats the thermosiphon by up to about 9 K, but only in gaming, only in a 25 °C or cooler room, and only with excellent heat exchangers. Realistic hobby hardware gives about 1–5 K.
- **On watts per degree:** nothing beats the thermosiphon. Config B is 2–20 W/K. At best it ties a small compressor chiller (2–3 W/K). The compressor works at every workload and in every room, so B loses in practice.
- **Under the no-sacrifice rule** (GPU die ≤ 65 °C, so harvest ≤ 50 °C at 250 W), the cycle sits at or below its threshold. **The GPU-driven chiller does not reliably run.** Relaxing the rule to a 70–75 °C die makes it run, at the GPU's expense.
- **Both chips in their best bands:** thermosiphon CPU (35–45 °C) plus plain-water or heat-pipe GPU (45–55 °C) already achieves this at about 8 W. Every chiller variant goes past the knee where colder stops buying life or clocks.
- **Ranking: unchanged.** The GPU-driven hybrid joins item 5 as a demonstrator. Solar-only (config C) stays at item 4.

**Minimum viable experiment** (cheap, decisive, in this order):

1. **GPU harvest curve. Cost about $0 if a loop exists.** Put the GPU on a full-cover block. Hold the coolant at 35, 45, 50, 55 and 60 °C with a thermostat aquarium heater in the reservoir. Run a fixed load. Log the die temperature, board power (wall meter delta), and clocks. This gives the real R_blk, leakage vs temperature, and the boost bins lost. If a die of 65 °C or less needs coolant below 50 °C, stop here: no-sacrifice harvest cannot drive any known sorbent.
2. **Bench sorbent swing.** Put 100–200 g of RD silica gel (or FAM-Z01 if obtainable) in a vacuum jar, connected to an evaporator vial and a condenser vial, with a pressure gauge. Cycle the bed with a 50/55/60 °C water bath against a 30 °C condenser. Weigh the uptake swing. Below about 0.05 kg/kg at 55 °C, the hobby-scale chiller will not run on GPU heat.
3. Only if both pass: a single-bed intermittent demo that chills a 1–2 L CPU-loop tank after a gaming session (the dry-bed storage idea). Measure the CPU temperature against the thermosiphon run.

**Confidence.** **Established:** the thermodynamic window, the GPU spec temperatures, and the D5 and acrylic limits. **Moderate:** COP and mass numbers, which follow from the model with flagged assumptions; real 100 W-scale machines usually do worse. **Speculative:** box size and weight, PCM latent heat, GPU leakage watts, and Pascal bin thresholds (forum sources).

### Sources (this follow-up)

- GPU temps/power: https://pcper.com/2010/03/nvidia-geforce-gtx-480-and-gtx-470-review-gf100-and-fermi-tackle-gaming/2/ ; https://www.tomshardware.com/reviews/geforce-gtx-480,2585-3.html ; https://bit-tech.net/reviews/tech/graphics/is-the-amd-radeon-r9-290x-too-hot/1/ ; https://www.legitreviews.com/amd-radeon-r9-290x-video-card-review_126806/15 ; https://www.techspot.com/review/727-radeon-r9-290x/page10.html
- GPU Boost 2.0 (80 °C target): https://gfxspeak.com/archives/nvidias-new-gtx-780-and-770-graphics-boards/ ; https://www.guru3d.com/review/geforce-gtx-titan-overclock-guide/page-2/ ; https://pcper.com/2013/02/nvidia-geforce-gtx-titan-preview-gk110-gpu-boost-2-0-overclocking-and-gpgpu/3/
- GPU Boost 3.0 bins (forum): https://www.techpowerup.com/forums/goto/post?id=3721311 ; https://www.techpowerup.com/forums/goto/post?id=3601832
- 290X leakage vs temp (forum): https://m.sweclockers.com/forum/trad/1251001-radeon-r9-290-290x-owners-club?p=13 ; https://www.legitreviews.com/nzxt-kraken-g10-gpu-water-cooler-review-on-an-amd-radeon-r9-290x_130344/4
- GDDR5 temperature: https://www.igorslab.de/en/gddr6-memory-temperatures-comprehensibly-explained-and-remeasured-is-amd-doing-everything-right-basics/
- Block delta over coolant (user report): https://www.titanrig.com/alphacool-core-geforce-rtx-5080-epic-x-gpu-water-block-with-backplate.html ; https://techpowerup.com/forums/threads/312282
- Pump/reservoir limits: https://hvacquick.com/catalog_files/Goulds_Laing_D5_Vario_Catalog.pdf ; https://www.aquatuning.com/en/watercooling/custom-watercooling/pumps/d5-series/d5-pumps/pum-laing-d5-pump-12/24v-d5-vario-1/2-ig ; https://es.thermaltake.com/pacific-pr22-d5.html
- Radiator sizing: https://west-games.com/pc-watercooling-radiator-size-calculator/ ; https://www.overclock.net/posts/9364988
- Fujitsu 55 °C adsorption: https://phys.org/news/2011-11-fujitsu-cooling-technology-cpu.html ; https://www.datacenterdynamics.com/en/news/fujitsu-uses-waste-heat-to-cool-data-centers/
- AQSOA family: https://kriso.re.kr/sciwatch/handle/2021.sw.kriso/9346 ; https://www.jstage.jst.go.jp/article/jcej/40/13/40_07WE193/_article ; DOI 10.1016/j.energy.2016.03.036 ; DOI 10.1021/acsomega.5c11973 ; https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7497089
- EMM-8: DOI 10.1038/s41467-021-27883-4
- Compact chiller: DOI 10.1016/j.applthermaleng.2017.07.130 ; InvenSor: https://www.esmagazine.com/articles/96174-chillers-invensor ; SorTech ACS 08: https://journals.vilniustech.lt/index.php/MLA/article/view/3584 ; Coolar: https://www.climate-kic.org/?p=20822
- Silica gel isotherm: Chua, Ng, Chakraborty, Oo, Othman, J. Chem. Eng. Data 47 (2002) 1177 (Toth parameters used in `configs.py`)
- Solar collectors: https://www.dincertco.de/logos/011-7S140%20F.pdf ; https://adria.giacomini.com/sites/giacomini.adria/files/accordion/files/GIACOMINI%20GSUN%20200_CE078KEYMAR000181_IN_2018-04-10.pdf ; https://ritter-energie.de/wp-content/uploads/2023/03/KollUebers_OEM_EN.pdf ; https://opus4.kobv.de/opus4-haw/frontdoor/index/index/year/2024/docId/4398
- PCM: https://yorkspace.library.yorku.ca/items/80861fde-8c28-4c29-95ad-1a9e99412940 ; https://dspace.vut.cz/items/12775239-6dfe-4f2b-9618-1858e471d3fd
- HDD temperature: Pinheiro, Weber, Barroso, "Failure Trends in a Large Disk Drive Population", FAST 2007

**Reproduce:** `~/.agents/venv`-style Python with CoolProp, then `python ~/.agents/docs/engineering/scripts/configs.py`. Sensitivity: `APP_BED=5 REAL_FACTOR=0.6 python configs.py`.

---

## Fluid and working-pair options (follow-up 2026-10-21)

**Question.** The earlier passes kept defaulting to water. Does any other fluid, refrigerant or working pair break the limits, inside a compact build? Constraints stay: CPU case 35–50 °C, GPU die 45–65 °C, wall power counted, room 25–30 °C, dew point respected. Model: `scripts/fluids.py` (CoolProp 8.0.0; every non-CoolProp number is flagged ASSUME or sourced below). Run `python fluids.py`, `TA=30 python fluids.py`, `APP=3 python fluids.py`.

### Short answer

- **No fluid escapes the limits.** Two limits bind, and neither belongs to a fluid.
- **Limit 1: the die's own conduction stack.** Silicon, thermal paste and the cold-plate base sit between the die and *any* coolant. At 250 W that stack costs about 9–10 K with paste and about 6–7 K with a liquid-metal TIM. So a 65 °C die can hand heat over at about 54–57 °C at best, whatever the coolant does.
- **Limit 2: the chiller's minimum drive temperature.** For 15–20 °C cold against a 25 °C room, every practical working pair needs about 56–74 °C hot fluid (best: step zeolites, 56–62 °C; NH3–H2O and ejectors 81–88 °C). In a 30 °C room the best is about 67 °C. This threshold comes from the Dühring relation. To first order it depends only on temperatures and on the pair's binding-to-boiling enthalpy ratio, not on the refrigerant's identity.
- **Two-phase pickup does not raise the harvest temperature in a useful way.** Boiling on the die gives the same delivery temperature as a well-flowed water block, within ±1 K at equal TIM. The 58–62 °C harvest Gil asked about needs a 67–74 °C die at 250 W. That breaks the GPU band. It is reachable without breaking it only if the GPU is power-limited to about 120–165 W.
- **The fluid lever that does matter is the TIM, not the coolant.** Liquid metal between die and block buys about 2.5 K. Galinstan as the *coolant* buys about 2 K, at about $2,000+/kg of gallium and with aluminium attack.
- **Verdict: the ranking does not change.** Compact solar (about 0.6–0.95 m² of evacuated tube) driving silica gel–water is the only heat-driven config that gives a real CPU gain (+8–10 K) inside the bands. It costs about 25 W of aux power, about 2.5–3 W/K. That ties a small compressor, which works at night and needs no roof.

### 1. Single-phase pickup at the chip

`fluids.py` §1. GPU 250 W board, 212 W into the block, die held at 65 °C, paste TIM, 2 K coolant rise unless pump power caps it at 5x water. Laminar microchannel scaling: convection resistance ∝ 1/k, pump power ∝ μV².

| Fluid | k (W/m·K) | Pump power vs water | Max outlet (harvest) °C | Price | Hazards / notes |
|---|---|---|---|---|---|
| Water + inhibitor | 0.64 | 1.0x | **55.3** | about $0.5/L | Galvanic corrosion with Al; biocide needed |
| 30 % ethylene glycol | 0.49 | 2.2x | 54.7 | about $2/L | Toxic. Only for freeze protection (solar loops). |
| 30 % propylene glycol | 0.47 | 2.4x | 54.5 | about $3/L | Low toxicity. Same role. |
| White mineral oil | 0.13 | 5x (capped), 8.8 K rise | 47.0 | about $5/L | Dielectric; fire load; seeps through fittings |
| PAO / synthetic dielectric oil | 0.14 | 5x, 5.7 K rise | 47.7 | about $15/L | Dielectric |
| Opteon SF33 liquid (R1336mzz(Z)) | about 0.073 | 4.6x | 38.8 | distributor quote only | Boils at 33 °C, so it is a two-phase fluid, not a single-phase one |
| Galden HT55/HT135 (PFPE) | 0.065 | 5x | 36.5 | about €360–410/kg (HT135, one distributor) | Inert, dielectric, PFAS |
| **Galinstan (GaInSn)** | 16.5 (27–35 in one datasheet) | 5x | **57.3** | gallium $2,100–2,350/kg (2026 spot); old retail figure about $36/mL | **Embrittles aluminium** (liquid-metal embrittlement). Slowly alloys with copper (LM-TIM practice, not re-verified). Electrically conductive: a leak shorts the board. Needs an EM or sealed pump. |
| Water + 1 vol % Al2O3 nanofluid | about 0.66 | 1.1x | 55.4 | about $50/L | Settling, clogging. No anomalous gain. |
| *Water, liquid-metal TIM* | — | 1.0x | **57.7** | about $15 a tube of LM TIM | Same LM hazards, grams instead of litres |

Note: this model sends 75 % of the captured heat through the die and the rest through VRAM/VRM pads. That makes its harvest about 4 K warmer than the prior follow-up's single 0.055 K/W lump (51 °C at a 65 °C die). The conclusions do not depend on which split is right.

**What the table says.**
- Water is already near the ceiling. The die stack, not the coolant, sets most of the 10 K drop. Galinstan's huge conductivity removes only the convection part (about 2 K). Moving liquid metal into the TIM gets the same gain with grams, not litres.
- Dielectric fluids (oils, PFPE, SF33 liquid) are 8–19 K *worse*. They are for leak safety and immersion, not for temperature.
- Nanofluids: the International Nanofluid Property Benchmark Exercise (30+ labs, identical samples) found conductivity follows classical effective-medium theory, with no anomalous enhancement. Convective gain tracks the conductivity gain. **Established.**
- A 2017 study of a CPU block with gallium vs CuO nanofluid vs water found gallium coolest, but with a "considerable penalty" in pressure drop and pump power. An A*STAR study found GaInSn gave lower chip temperature but a slightly lower COP (cooling per pump watt) than water. **Two sources, consistent.**

### 2. Two-phase pickup (boiling on the die)

`fluids.py` §2. Cooper pool-boiling correlation (h ∝ q^0.67, rises with reduced pressure), times 2 for flow boiling in microchannels (ASSUME; sanity check: EPFL measured a heater only 8 K above a 45 °C R1234ze saturation at 107 W/cm², in line with the model). Same 10 cm² fin field and die stack as §1. Cooper is reported valid below about 250 kW/m²; here the wetted flux is about 42 kW/m².

| Fluid | Max T_sat, paste TIM (°C) | P at T_sat (bar abs) | P at 25 °C | Class | US civilian route (2026) |
|---|---|---|---|---|---|
| R134a | **54.7** | 14.8 | 6.7 | A1, GWP about 1430 | 12 oz MVAC cans, no certification (self-sealing valve). AIM Act phase-down. |
| R600a isobutane | 54.6 | 7.7 | 3.5 | A3 | Butane/isobutane refill cans; purity varies |
| R1234ze(E) | 54.2 | 11.1 | 5.0 | A2L | **Sales-restricted** (non-exempt substitute; 608 cert) |
| n-butane | 54.1 | 5.5 | 2.4 | A3 | Lighter/camp fuel |
| n-pentane | 52.1 | 1.7 | 0.68 (sub-atm) | A3 | Lab suppliers, 1–4 L |
| methanol | 51.5 | 0.59 | 0.17 | flammable, toxic | Hardware store |
| R1233zd(E) | 51.3 | 3.1 | 1.3 | A1, GWP about 1 | **Sales-restricted** as a refrigerant; also sold as a solvent (unverified route) |
| Opteon SF33 (R1336mzz(Z)) | 49.8 | 1.8 | 0.74 (sub-atm) | A1 | Specialty fluid, distributor quote; not a "refrigerant" sale |
| water | 49.8 | 0.12 | 0.03 | none | Anywhere |
| ethanol | 49.5 | 0.29 | 0.08 | flammable | Hardware store |
| CO2 | **cannot** | — | — | A1 | Critical point 31 °C: supercritical at 50–60 °C, so no boiling |
| Opteon 2P50 | not modelled (no CoolProp entry) | — | — | non-flammable, GWP 10 | **Developmental, pending approval** (Chemours). Boils at 49 °C. |

With a liquid-metal TIM: R1234ze(E) 56.7 °C, R1233zd(E) 53.9 °C. Optimistic ceiling (double the flow-boiling enhancement, LM TIM, R1234ze): **58.3 °C.**

**The key question, answered.** *Can boiling let the die stay at 65 °C while delivering heat at 58–62 °C?* **No, not at 250 W.**
- Water already delivers at about 54–57 °C (paste / LM). Boiling delivers at 50–55 / 54–57 °C. At equal TIM the best boiling fluids match water to within about 1 K; the low-pressure ones are 2–5 K worse.
- Why: boiling's tiny temperature drop only replaces water's convection step (about 2 K) and its glide (about 1 K at good flow). The 6–10 K conduction stack stays. Also, the low-pressure fluids that are easy to handle (R1233zd(E), SF33, pentane, water, ethanol) boil poorly at moderate flux: low reduced pressure gives low h.
- To deliver at 58 °C the die must run at about 67 °C (LM) to 70 °C (paste). At 62 °C it must run at 71–74 °C. **That violates the 65 °C band.**
- The one escape inside the band: **lower the GPU power.** At 165 W board (GTX 980 class, or a power-limited big card) T_sat reaches about 58.6 °C; at 120 W, 59.5 °C. But there is then less heat to harvest. That is a trade, not a free gain.

**What two-phase does buy (Established, two sources):** about 10x less pump power at equal junction temperature (Honeywell ITherm 2020, R1233zd(E)/R1234ze(E) cold plates); a near-isothermal plate; and the option of a pumpless thermosiphon. It also lets the sorption bed *be* the loop's condenser, which removes one pump and one heat exchanger. That cuts aux power by about 3–5 W. It does not change the temperature verdict.

**Legal note (US).** Under 40 CFR 82.154(c), refrigerant that is a class I/II substance or a *non-exempt substitute* may only be sold to certified technicians (or for resale, or pre-charged in a sealed appliance). HFOs (R1234yf, R1234ze(E), R1233zd(E)) are non-exempt substitutes. The only uncertified HFC route is the **two-pound-or-less MVAC can with a unique fitting and self-sealing valve** (R134a, and R1234yf cans sold for car DIY). Exempt from the venting prohibition, and so outside the restriction: CO2, nitrogen and water in any use; ammonia in commercial/industrial and absorption units; hydrocarbons only in listed end-uses. The 2020 rule rescinded the HFC *leak-repair* extension, not the sales restriction. **Established** (eCFR text + EPA page). Whether a solvent-grade HFO sold "not as a refrigerant" falls outside the restriction is **unverified**; treat it as a grey area.

### 3. Chiller working pairs

`fluids.py` §3. Minimum drive temperature from the Dühring relation for an ideal step sorbent, `1/Tg = 1/Ta' − (1/Te − 1/Tc')/r` (kelvin, with heat-exchanger approaches), plus a pair-specific excess for isotherm width, rectification or crystallisation margin, calibrated to the literature anchors below. `r` is the sorption (or reaction) enthalpy over the refrigerant's vaporisation enthalpy. A larger r lowers the threshold but caps COP near 1/r. Room 25 °C, 4 K per heat exchanger.

| Pair | Pressures (evap/cond, bar) | Min drive, chilled 15 / 18 / 20 °C | COP @ 65 / 80 °C (chilled 18) | % of Carnot @ 80 | Literature anchor | Civilian availability |
|---|---|---|---|---|---|---|
| **Step zeolite (AQSOA FAM-Z01/Z05)–water** | 0.016 / 0.05 (vacuum) | **62 / 59 / 56** | 0.34 / 0.58 | 21 % | Regenerates about 55 °C (prior pass) | Sold to OEMs; small lots hard |
| MOF (CAU-23, Al-fumarate)–water | vacuum | 64 / 61 / 58 | 0.24 / 0.52 | 19 % | CAU-23 drives "down to 60 °C"; MIL-160 and Al-fum about 90 °C; Al-fum coated HX projected COP 0.47–0.57 | Research quantities |
| **Silica gel RD–water** | vacuum | 65 / 62 / 59 | 0.21 / 0.54 | 20 % | LRZ 45 °C drive → 21 °C cold; multi-stage down to 40 °C at low COP | **Cheap, kg-scale, benign** |
| BaCl2-vermiculite–NH3 | 7 / 13 | 65 / 63 / 61 | 0.14 / 0.48 | 17 % | COP 0.54 at 80–90 °C; desorption tested at 65–90 °C | Salt easy; NH3 is the problem |
| CaCl2-in-silica (SWS-1L)–water | vacuum | 70 / 67 / 66 | 0 / 0.48 | 17 % | COP 0.6 at 90–95 °C drive, 5–10 °C cold; coated HX 150–200 W/kg | **DIY-able** (CaCl2 + silica gel) |
| AC (Maxsorb III)–methanol | 0.09 / 0.25 | 71 / 68 / 66 | 0 / 0.42 | 15 % | Model COP 0.73 at 85 °C; real solar ice makers about 0.1 solar COP | Carbon yes; methanol toxic, flammable |
| AC–ethanol | 0.04 / 0.12 | 74 / 71 / 69 | 0 / 0.31 | 11 % | Prototype intrinsic COP 0.05 → 0.18 at 80 °C after redesign | Easy, low hazard, weak |
| AC–R134a / R1234ze | 4.7 / 8.4 | 71 / 68 / 67 | 0 / 0.15 | 6 % | Low uptake | R1234ze restricted |
| LiBr–water | vacuum | 74 / 71 / 68 | 0 / 0.48 | 17 % | 70–95 °C, COP 0.57–0.7 (prior pass) | kW-scale only; corrosive |
| NH3–LiNO3 | 7 / 13 | 74 / 71 / 69 | 0 / 0.44 | 16 % | COP 0.68 at 90/35/15 °C (11 kW lab); booster cycle 67 °C (simulated) | NH3, steel only |
| Ionic liquid–water | vacuum | 73 / 70 / 68 | 0 / 0.40 | 14 % | Simulation-stage | No |
| NH3–H2O | 7 / 13 | 87 / 84 / 82 | 0 / 0 | — | 90–170 °C (prior pass) | Icyball class |
| Ejector, R1233zd(E) / R600a | 0.9 / 1.7 | 88 / 84 / 81 | 0 / 0 | — | 200 kW plant: COP about 0.25 at <70 °C source for 16/19 °C glycol (single source) | Needs a 100 W ejector, which does not exist |
| ORC + vapour compression | — | 68 / 64 / 61 | 0.03 / 0.17 | 6 % | No 100 W-class expander exists | No |
| Resorption (NH4Cl–CaCl2 etc.) | high | ≥ 100 | ≤ 0.43 theoretical | — | Thermodynamic study | No |
| Double-effect LiBr–water | vacuum | 140–175 °C | 1.0–1.3 | — | Nominal about 1.3 at about 175 °C steam; field 0.7–1.2; small air-cooled prototype about 1.05 | Burner-fired, kW-scale |

**Second-law check (fluid-independent).** At chilled 18 °C and a 29 °C rejection: Carnot COP is 1.52 at 55 °C drive, 2.04 at 65 °C and 2.76 at 80 °C. The best pairs reach about 20 % of Carnot at 80 °C in this model. No pair can beat the Carnot line. Below its threshold every pair makes zero cold, and every threshold sits at or above 56 °C in a 25 °C room with 4 K approaches. That is where GPU harvest lives.

**In a 30 °C room** the dew floor at 50 % RH rises to 21.4 °C. The thresholds at chilled 20 °C rise to 67 °C (step zeolite), 69–70 °C (MOF, silica gel, BaCl2) and 73 °C or more for the rest.

**Where the fluid matters.** Only in the second-order terms: isotherm sharpness (step zeolites, MOFs), r (salts and AC pairs), pressure level (vacuum for water pairs, 7–13 bar for NH3), and hazard. The threshold's main terms are temperatures. **Confidence: Established** for the Dühring/Carnot structure. **Moderate** for the pair excesses, which are calibrated to single anchors.

### 4. Compact supplemental heat

`fluids.py` §4. Physics floor: collector area ≥ Q / G. At 1 kW/m², 100 W of heat needs at least 0.10 m² and 300 W needs 0.30 m², with a perfect absorber.

| Source | Temperature | Real area or rate for 100 W of heat | Notes |
|---|---|---|---|
| Evacuated tube (ETC), Ritter-class | 75–90 °C | 0.27–0.28 m² (η about 0.36) | Prior pass coefficients |
| CPC evacuated tube | 125–160 °C | 0.19–0.21 m² (η about 0.5) | η 0.5 at 125 °C (single source); ICPC built for 165 °C double-effect |
| Propane burner | any | 7.8 g/h | Needs a flue: CO, NOx, water vapour indoors |
| Candle | flame | about 1.3 candles | 77 W each (NPL) |
| Domestic hot-water tank | 50–60 °C | — | Same grade as GPU harvest, too cold. And it is paid energy. |
| Electric heater | any | 100 W of wall power | A compressor needs about 0.3 W of wall power per W of cold |

**Does a hotter compact source help?** Yes for area, no for the verdict. For 100 W of cold: single-effect silica gel at 75 °C needs 204 W of heat (0.66 m² ETC, or 16 g/h propane). Double-effect LiBr at 150 °C needs about 91 W (0.22 m² CPC, or 7 g/h propane). That is a 3x smaller collector. But no double-effect machine exists below kW scale. It runs at 150 °C or more in a vacuum vessel with corrosive brine. It is not a hobby build. If the heat is *electric*, both are worse than a compressor (11–24 W/K vs about 3).

### 5. Complete configurations, ranked

`fluids.py` §5. Hybrid booster topology from the prior follow-up (the CPU always keeps its own ambient path). The chiller cold is evaluated at the dew floor, which is conservative for partial cold: letting the evaporator float warmer gives back 1–3 K (the prior `configs.py` does this). Baseline: thermosiphon CPU at 35.9 °C (25 °C room) or 40.9 °C (30 °C), plain-water GPU, about 8 W.

| Rank | Configuration | GPU die | CPU case | Extra wall W | W/K | Footprint | Attainability |
|---|---|---|---|---|---|---|---|
| **1** | **Thermosiphon CPU (R1233zd(E), water or ethanol) + water GPU (or GPU two-phase thermosiphon); LM TIM on the GPU optional** | 45–55 °C | 36–41 °C | 0 (8 W total) | ≤ 0 | In the case | **High.** Unchanged winner. Both chips are already in band. |
| 2 | Small compressor chiller trim at the dew floor | same | about 27–31 °C | about 30 | about 3 | Fridge-sized | High. Any time, any room. Buy pre-charged so no refrigerant purchase is needed. |
| 3 | **Compact solar ETC + silica gel–water**, GPU left on its own loop | 45 °C | **27.5 °C (+8.4 K)** at 25 °C; 30.9 °C (+10 K) at 30 °C | about 25 | **3.0 / 2.5** | **0.66 m²** (25 °C room) / 0.94 m² (30 °C), plus storage for evening use | Moderate. Daytime only without storage. |
| 4 | Compact solar ETC at 85 °C + DIY CaCl2-in-silica gel (SWS-1L type)–water | 45 °C | same as 3 | about 25 | 3.0 / 2.5 | 0.63 / 0.73 m² | Moderate-low. Better in a hot room. Composite must be made and tested. |
| 5 | GPU harvest at 65 °C die, LM TIM, step zeolite or silica gel, **3 K approaches, room ≤ 25 °C** | 65 °C | 36.6–36.9 °C (**worse** than the thermosiphon) | about 16–19 | ∞ | 2nd box | Demo only: 20–30 W of cold. At 4 K approaches, or a 30 °C room, it makes **zero** cold. |
| ref | Same, die 70–75 °C (breaks the GPU band), 3 K approaches | 70–75 °C | 34.6–34.8 °C (+1.2 to +1.3 K) | 16–19 | 12–17 | 2nd box | Excluded by the no-sacrifice rule |

**Swapping fluids in configs 3–5** (NH3–LiNO3, BaCl2–NH3, AC–methanol) needs the same or more collector area (0.62–0.83 m²). It adds toxicity or pressure. It never beats silica gel–water on attainability. The ejector needs 1.9–8 m², which is not compact.

### 6. Verdict

- **Which limit binds:** for GPU-driven cooling, the **die's conduction stack** (it caps delivery at about 54–57 °C) against the **Dühring threshold** of the best pair (56–62 °C at 25 °C; 67 °C or more at 30 °C). They miss by 0–8 K at 25 °C and by about 9–14 K at 30 °C. No fluid closes that gap. A liquid-metal TIM narrows it by about 2.5 K. Only a hotter die or a lower GPU power closes it.
- **For externally driven cooling:** the binding limit is **area** (physics floor 0.1 m² per 100 W of heat; real about 0.3 m² at 75 °C), plus the sun's schedule. Then the CPU gains about 8–10 K at about 3 W/K, the same as a compressor.
- **Ranking unchanged.** Passive two-phase or water first, compressor trim second, compact solar sorption third.
- **Best fluid choices, if Gil builds anyway:** water with liquid-metal TIM for pickup. R1233zd(E) (A1, about 1–4 bar) or water/ethanol for a passive two-phase loop. Silica gel–water for the chiller (cheap, benign, vacuum only). Avoid Galinstan loops (aluminium, cost), dielectric oils and PFPE (8–19 K worse), CO2 (supercritical) and ammonia pairs (toxic, steel only).

**What to measure next (fluid-specific):** (1) GPU die vs coolant temperature with paste, then with LM TIM, at fixed board power: this measures the conduction stack that binds everything. (2) Die temperature vs board-power limit (120/165/250 W) at a fixed 58 °C coolant: this measures the power-for-harvest trade. (3) A 100 g bed of silica gel, then a home-made CaCl2-in-silica-gel composite, cycled at 55/60/65 °C against the real room: this measures the threshold directly.

**Confidence.** **Established:** the second-law and Dühring structure; INPBE nanofluid result; CO2's critical point; the eCFR sales-restriction text; Galinstan's attack on aluminium. **Moderate:** die-stack split (calibrated to one 0.055 K/W data point), Cooper × 2 for flow boiling, pair excesses. **Speculative:** Galinstan and SF33 current retail price; the solvent-grade HFO legal route; ejector behaviour at 100 W scale.

### Sources (this follow-up)

- Sales restriction: https://www.law.cornell.edu/cfr/text/40/82.154 ; https://www.epa.gov/section608/refrigerant-sales-restriction ; 2020 leak-repair rescission: https://www.epa.gov/node/120675 ; small cans: https://open-exam-prep.com/study-guides/epa-609/clean-air-act-regulations/sales-restrictions (secondary)
- Galinstan: https://en.wikipedia.org/wiki/Galinstan ; https://www.goodfellow.com/usa/resources/gallium-indium-tin-ga68-5-in21-5-sn10-material-information/ ; gallium price: https://news.metal.com/newscontent/103927025-high-purity-gallium-prices-surge-in-europe-spot-trading-reaches-2350kg-amid-supply-shortage ; https://www.spglobal.com/content/dam/spglobal/global-assets/en/special-reports/critical-mineral-market-reports/Market%20Report%20-%20Gallium%20-%2008052026.pdf
- Liquid-metal coolant vs water: https://iifiir.org/en/fridoc/on-the-convective-thermal-performance-of-a-cpu-cooler-working-with-140513 ; https://oar.a-star.edu.sg/communities-collections/articles/22033
- Nanofluids (INPBE): https://dspace.mit.edu/handle/1721.1/62707 ; https://arxiv.org/pdf/2104.05403
- Dielectric fluids: Opteon 2P50 https://www.opteon.com/en/products/liquid-cooling/2p50 ; ORNL 2P50 pool boiling https://www.ornl.gov/publication/pool-boiling-heat-transfer-evaluation-next-generation-dielectric-fluid-opteontm-2p50 ; Opteon SF33 https://www.opteon.com/en/products/specialty-fluids/sf33 ; SF33 vs HT55 boiling https://www.mdpi.com/1996-1073/18/21/5719 ; Galden HT135 price https://www.conro.com/zh/lubricants/special-oils-and-lubricants/SOLVAY-GALDEN-HT-135-HEAT-TRANSFER-FLUID-5KG-CONTAINER
- Two-phase cold plates: Honeywell, "Ultra-low GWP heat transfer fluids for pumped two-phase cooling", ITherm 2020 (Honeywell link now redirects; title cited) ; Cataldo & Thome 2017 https://infoscience.epfl.ch/record/232714 ; Lisbon loop https://fenix.tecnico.ulisboa.pt/downloadFile/1126295043838640/Resumo%20alargado.pdf ; R1233zd(E) microchannel boiling https://qmro.qmul.ac.uk/xmlui/handle/123456789/68276 ; Cooper correlation https://ht.readthedocs.io/en/latest/ht.boiling_nucleic.html ; Cooper validity <250 kW/m² https://scholar.xjtu.edu.cn/en/publications/experimental-validation-of-cooper-correlation-at-higher-heat-flux/
- AC pairs: https://api.lib.kyushu-u.ac.jp/opac_download_md/1654933/tj0979_abstract.pdf ; https://www.tj.kyushu-u.ac.jp/evergreen/contents/EG2014-1-1_content/2014-mar-25-31.html ; https://psecommunity.org/wp-content/plugins/wpor/includes/file/2304/LAPSE-2023.27460-1v1.pdf
- Salt composites: SWS-1L https://sciact.catalysis.ru/public/article/5575/en ; https://sciact.catalysis.ru/public/article/20845/en ; BaCl2–NH3 https://sciact.catalysis.ru/public/article/3151/en ; https://mdpi-res.com/d_attachment/processes/processes-13-03708/article_deploy/processes-13-03708.pdf ; resorption https://researcher.manipal.edu/en/publications/assessment-of-different-combinations-of-ammoniated-halide-salt-fo/
- NH3–LiNO3: https://iifiir.org/en/fridoc/ammonia-lithium-nitrate-absorption-chiller-with-an-integrated-133612 ; https://iifiir.org/en/fridoc/a-new-ammonia-lithium-nitrate-absorption-chiller-for-solar-cooling-28222 ; https://ideas.repec.org/a/eee/appene/v97y2012icp297-304.html
- MOFs: https://pmc.ncbi.nlm.nih.gov/articles/PMC6616384 ; https://publica.fraunhofer.de/handle/publica/408358
- Multi-stage silica gel: https://iifiir.org/en/fridoc/multi-bed-multi-stage-adsorption-refrigeration-cycle-reducing-driving-22802 ; https://iifiir.org/en/fridoc/waste-heat-driven-dual-mode-multi-stage-multi-bed-regenerative-122236
- Ejector: https://iifiir.org/en/fridoc/experimental-assessment-of-the-first-industrial-implementation-of-148085 ; https://flore.unifi.it/handle/2158/1217188 ; https://bip.polsl.pl/nadania_dr/mikolaj-mastrowski/streszczenie-w-jezyku-angielskim-21
- Double effect: https://www.techniques-ingenieur.fr/en/resources/article/ti204/liquid-absorption-machines-be9735 ; https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10612821 ; https://agris.fao.org/search/en/records/6748918a7625988a371dbb08
- CPC / concentrating collectors: https://ideas.repec.org/a/eee/renene/v50y2013icp299-306.html ; https://www.osti.gov/biblio/355747 ; https://www.frontiersin.org/journals/energy-research/articles/10.3389/fenrg.2021.754546/pdf

**Reproduce:** a Python with CoolProp, then `python ~/.agents/docs/engineering/scripts/fluids.py`. Sensitivity: `TA=30`, `APP=3` or `APP=5`, `F_FLOW=4`, `DIE_MAX=70`.
