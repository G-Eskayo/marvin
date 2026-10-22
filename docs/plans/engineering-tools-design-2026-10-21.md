# MARVIN engineering tools: design (draft)

**Status:** Decisions taken 2026-10-21; next are a grilling pass on rung 0 and then tickets.
**Why now:** Gil decided (2026-10-21) that MARVIN should build the general engineering tools that let it help scope, model, draw and test real-world projects. The first consumer is [thermal-forge](https://github.com/G-Eskayo/thermal-forge) (ADR 0001 there). Later consumers are on the workshop list: biodiesel equipment, the dream engine, the algae farm, MARVIN Mirror/Surface and overlanding gear.
**Inputs:** `docs/engineering/engineering-toolchain-survey-2026-10-21.md` (tool choices, install paths, rungs 0–6). thermal-forge's `docs/research/household-supercomputer-cooling-calc-framework.md` (the equations rung 0 must cover).

## Goal

Give MARVIN five abilities, all scriptable, local on Apple Silicon, free, and checked against hand calculations:

1. **Calculate:** first-principles thermal, fluid and structural numbers with honest uncertainty.
2. **Model:** parametric geometry (CAD as code).
3. **Simulate:** conduction FEA, then structural, then CFD.
4. **Draw:** schematics and drawings a person can build from. These are 2D drawings with dimensions, P&ID and loop diagrams, and electrical schematics.
5. **Experiment:** design real-world tests, produce the parts and sensor list and the measurement plan, log the data and compare it with the model.

## Non-goals

- No project-specific designs live in MARVIN. Those go in the project repo (thermal-forge ADR 0001).
- No paid or Windows-only tools such as SolidWorks or ANSYS. No cloud solvers.
- No GUI-first workflows, except optional live viewers.

## Shape

There is one Python package and one skill per ability. MCP is used only where a live app session is the point (composability principle; survey "MCP servers or skills").

    ~/.agents/lib/eng/
      units.py        pint-based units; every public function takes and returns quantities
      props.py        CoolProp wrapper + materials.yaml (k, cp, rho, E, yield, CTE, max temp) with sources
      thermal.py      R-networks, conduction/spreading, convection (Dittus–Boelter, Gnielinski), fins
      twophase.py     boiling (Cooper, Zuber CHF), condensation (Nusselt), thermosiphon head/limits
      cycles.py       Carnot bounds, vapour compression, sorption (Dubinin–Astakhov), temperature budget
      hx.py           epsilon-NTU, LMTD
      structural.py   Barlow, hoop stress, thermal expansion
      uncertainty.py  parameter ranges, Monte Carlo, Sobol via SALib
      cad/            build123d part library (cold plate, fin stack, manifold, tube bends)
      mesh.py         gmsh wrapper with named physical groups
      fea.py          scikit-fem heat (steady and transient); CalculiX adapter later
      cfd/            OpenFOAM case templates via foamlib (later)
      draw.py         technical drawings from build123d (SVG/DXF/PDF), schemdraw P&ID and loop diagrams
      experiment.py   test-plan generator, sensor/BOM list, CSV logger schema, model-vs-measured report
    ~/.agents/skills/eng-*/  eng-calc, eng-cad, eng-sim, eng-draw, eng-experiment
    venv: ~/.agents/venv-eng  (kept apart from the main venv; about 1.5 GB)

The project repo calls the library. thermal-forge keeps its own `model/`, which imports `eng`.

## Rungs (build order)

Each rung ships with adversarial tests: they check against textbook or hand results and try to break inputs and units.

| Rung | Delivers | Done when |
|---|---|---|
| 0 | `units`, `props`, `thermal`, `hx`, `cycles`, `structural`, `uncertainty` + `eng-calc` skill | thermal-forge calc-framework layers 0–11 run as one parameterized model with Monte Carlo and a Sobol ranking; textbook examples reproduce within stated tolerance |
| 1 | `cad/` + `eng-cad` | a parametric copper cold plate exports STEP/STL plus a PNG preview; named faces carry through |
| 2 | `mesh`, `fea` + `eng-sim` | the cold-plate temperature field agrees with rung 0 within 10–20 %; transient works |
| 3 | `draw` + `eng-draw` | dimensioned drawing of the cold plate, and a loop/P&ID diagram of the thermosiphon with instrument tags |
| 4 | `experiment` + `eng-experiment` | the bench plan for "GPU clocks vs coolant temp" and "single R134a loop on a CPU": sensor list, BOM, procedure, safety checklist, logger schema, model-vs-measured report |
| 5 | CalculiX structural | pressure-vessel check of the R134a loop matches Barlow |
| 6 | OpenFOAM on the Mac Mini | condenser airflow case runs headless via the task-dispatch primitive |
| 7 | electronics (SKiDL/kicad-cli) | a sensor/logger board schematic |

The rung order deliberately puts **drawing and experiments (3–4) before CFD (6)**. thermal-forge needs bench data sooner than it needs CFD, and the calc framework says to measure the most sensitive parameters first.

## Complexity

- **Rung 0 per evaluation:** O(1). Monte Carlo is O(N samples). Sobol is O(N·(d+2)) with d parameters, so ~10⁴–10⁵ evals runs in seconds.
- **FEA:** O(mesh elements). Cap the default mesh size and log the count.
- **CFD:** hours. Run it on the Mini via dispatch and never block a session.
- **Storage:** generated artifacts (STEP, meshes, VTU, PNG) are written to the project repo's `out/`, which is git-ignored. Only inputs and reports are committed.

## Decisions (Gil, 2026-10-21)

1. **Library home:** inside `~/.agents/lib/eng` plus `eng-*` skills.
2. **Units:** pint everywhere.
   - **Metric (SI) only, across the board.** Any imperial input (datasheets, US refrigerant cans in oz or lb, psi gauges, AWG) is converted at the boundary and never carried inside.
   - **Temperature is computed in kelvin.** Every number in literature we produce (reports, drawings, test plans) shows kelvin with °C next to it, e.g. "338.15 K (65 °C)". Temperature differences are given in K.
3. **Deterministic tools for hard science.** Every physics, chemistry or engineering number comes from tested code (CoolProp, the `eng` library, solvers), never from model arithmetic. Correlations and constants are sourced through the research tools and cited in the code. Where no deterministic tool exists, we find one or build one before using the number.
4. **CAD:**
   - Try text-to-cad (build123d skills, telemetry off).
   - Also evaluate SolidCraft (bherbruck/solidcraft: SolidWorks-class parametric CAD with a headless CLI and MCP). It's the likely match for the "simulates and improves SolidWorks" repo Gil remembers; to be confirmed with Gil. Neither is installed yet.
5. **Target output:** build-ready schematics that meet, then beat, industry standards. The baseline is metric ISO/IEC:
   - ISO 128 / ISO 129-1 drawings and dimensioning
   - ISO 1101 GD&T
   - ISO 10628 P&ID
   - IEC 60617 electrical symbols
   - EN 378 / ISO 5149 refrigerating-system safety (pressure, charge limits, relief)
   - EN 12735 copper tube for refrigeration

   "Beat" means every drawing traces back to its calculation, safety factors are stated and justified, uncertainty bands are carried through, and a test plan validates each critical number.
6. **First milestone:** rung 0. thermal-forge's calc framework runs as one parameterized, tested model with Monte Carlo and a Sobol ranking.
