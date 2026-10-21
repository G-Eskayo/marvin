# Engineering toolchain survey for MARVIN (2026-10-21)

Research for the physical-workshop vision (memory: `project-physical-workshop-vision`). This is a survey and a proposal. Nothing was installed.

Confidence tiers: **[H]** checked directly today (repo page, PyPI JSON, `brew info`, a command on this machine). **[M]** one secondary source, or well-established background knowledge not re-checked today. **[L]** inference or a single weak source.

## Summary

**The Instagram post.** It isn't in the Aug 22 export. The best match is **SolidCraft** (github.com/bherbruck/solidcraft): an open-source parametric CAD app written in Rust by AI coding agents, covered in October 2026 as one of the "vibecoded clones of SolidWorks and AutoCAD." It ships a macOS Apple Silicon build, a headless CLI and an MCP server, and it is MIT/Apache-2.0 [H]. It has no CFD. If the post also showed a CFD repo, the likeliest ones are **AgentCFD** (an agent-native OpenFOAM wrapper) or **Foam-Agent** (a research multi-agent OpenFOAM driver). Two other candidates: **earthtojake/text-to-cad** (about 22k stars, a Claude Code plugin with build123d/OCP CAD skills) and **Millwright** (an agent that drives real SolidWorks, Windows only). The gruenewald.exe / forgehub.engineering saves are teaser reels ("comment specs for links"). forgehub.engineering itself is a CAD file-hosting marketplace with no repos listed, so that trail ends there [H].

**Recommended stack.** Everything below runs natively on Apple Silicon, with no Linux and no paid keys:
- **Geometry:** build123d or CadQuery, both on the OCP/OpenCascade kernel.
- **Meshing:** gmsh.
- **Conduction FEA:** scikit-fem first (pure Python), then CalculiX or Elmer for bigger jobs.
- **Fluids and conjugate heat transfer:** OpenFOAM through gerlero's native Homebrew tap, which avoids Docker.
- **Fluid properties:** CoolProp.
- **Rendering:** PyVista.
- **Electronics:** KiCad (Python API) and SKiDL.

Docker or OrbStack is only a fallback (SU2, Code_Aster, Salome). exo is not useful here, because it is an LLM-inference sharder and doesn't run solvers. The Mac Mini (M4, 10 cores, 16 GB) is the right host for long runs, but it only has **19 GB of free disk**, which limits heavy CFD cases and container images.

**First build.** A 1D/lumped thermal-resistance calculator plus a 2D/3D conduction run of a cold plate (build123d → gmsh → scikit-fem → PyVista PNG), packaged as one skill with a small Python library. MCP servers wait until a tool needs a live, stateful session (FreeCAD GUI, KiCad, a running OpenFOAM case).

---

## Part A: finding the Instagram post

### What the export shows [H]

`~/.claude/outbox/2026-08-22-instagram-ai-saves/all_saved_posts.json` has 172 items. These are the engineering-related ones:
- gruenewald.exe (Andrew Gruenewald, profile link forgehub.engineering): two reels with the same caption template, "comment 'specs' / 'signal' for links to all projects", saved Jul 16 and Jul 30. The repo links went out by DM, so they aren't in the export.
- artificialzone, "10 GitHub repos competing with products worth billions": CRM, e-signature, video and similar. No CAD.
- "10 GitHub repos that make paid software look harder to justify" and "10 GitHub Repos that feel too powerful": general SaaS replacements. No CAD or CFD in the captions.
- mekhy_w: AERIS-10 open-source radar (github.com/NawfalMotii79/PLFM_RADAR). It's a hardware build, not CAD.

forgehub.engineering is a SaaS for hosting and selling CAD files. It lists .SLDPRT/.SLDASM, STEP, FEA formats and a Pro "AI tools" tier, and links to no third-party repos [H]. Gruenewald's reels probably point to project lists hosted there, but those links aren't visible without the DM.

### Candidates, ranked by fit to "reverse engineers and lets us use SolidWorks and CFD"

| # | Project | What it is | Stars / activity | License | macOS? |
|---|---|---|---|---|---|
| 1 | **SolidCraft**, github.com/bherbruck/solidcraft | Parametric CAD in pure Rust, written by Claude agents. Press called it a "clean-room" Fusion/SolidWorks-style clone. Timeline, sketches, assemblies with joints, motion studies, mass properties. STEP/IGES/3MF/STL/glTF/URDF. `solidcraft-cli mcp` is an MCP server, headless or attached to the app. | Reported 0.5k–3.3k stars, depending on the snapshot date. v0.14 (Oct 2026). Very fast-moving [M] | MIT OR Apache-2.0 [H] | Yes, Apple Silicon DMG (unsigned) [H] |
| 2 | **text-to-cad**, github.com/earthtojake/text-to-cad | Claude Code plugin: CAD skills (build123d + OCP), STEP/GLB/STL/3MF, drawings, DFM, URDF, G-code, `cadgen mcp` server | About 22.2k stars, 2.2k forks [H] | MIT [H] | Generic uv install. Probably fine on macOS [M]. Telemetry is on by default, so turn it off |
| 3 | **AgentCFD**, github.com/haoming-luo/agentcfd | Agent-readable `case.py` CFD for pipes and ducts. Writes and runs OpenFOAM cases. Includes a 0D hydraulic-network solver. MCP manifest | 2 stars, pre-alpha (0.1.0a6) [H] | Apache-2.0 [H] | Yes, via native OpenFOAM or the OpenCFD Docker image [H] |
| 4 | **Foam-Agent**, github.com/csml-rpi/Foam-Agent | Research multi-agent system: natural language → OpenFOAM case → run → fix. Reports 83.6% (v1) and 88.2% (v2) task success with Claude 3.5 Sonnet. These are the authors' own benchmark numbers [M] | Academic | Check repo | Linux-first. Works with native OpenFOAM [L] |
| 5 | **Millwright**, github.com/raylanlin/Millwright | An agent that operates real SolidWorks: about 50 native tools, screenshot self-check, confirmation before destructive ops. MCP is on the roadmap | 31 stars, v0.2.134 [H] | Apache-2.0 [H] | **No.** Windows plus a paid SolidWorks licence |
| 6 | SolidWorks MCP servers: vespo92/SolidworksMCP-TS, eyfel/mcp-server-solidworks, haunchen/solidworks-mcp, ghosessx/SolidworksAi | COM-automation bridges | Small, experimental [M] | Mixed | **No.** Windows plus paid SolidWorks |
| 7 | **sim-cli**, github.com/svd-ai-lab/sim-cli | Turns CAE files (Fluent, COMSOL, Abaqus, Icepak, FloTHERM) into agent-readable JSON and ships Claude skills. Doesn't run the solvers unless you hold licences | 241 stars, alpha [H] | Apache-2.0 [H] | Python. Of little use without commercial solvers |

**Verdict [M]:** "Reverse engineers SolidWorks" fits SolidCraft best. It was the October 2026 story about AI agents rebuilding commercial CAD from public behaviour, from the same wave as the ArtCraft "Craft" Adobe clones. It is also recent enough to have reached Gil after the August export. If Gil remembers a CFD half in the same post, the post was probably a listicle that paired SolidCraft or text-to-cad with an OpenFOAM agent (AgentCFD or Foam-Agent). Ask Gil whether the post had a Rust/desktop-app look (SolidCraft) or a Claude-plugin look (text-to-cad).

**Note on SolidWorks:** it is Windows-only and paid. Every "use SolidWorks with AI" repo needs both, so none of them fit MARVIN. SolidCraft and build123d are the realistic substitutes, because they read and write STEP, which SolidWorks also opens.

Other directories worth bookmarking: **Awesome-Physical-Engineering-AI** (github.com/010zx00x1/Awesome-Physical-Engineering-AI) lists freecad-mcp, onshape-mcp, kicad-mcp, openfoam-mcp-server, cadquery MCP servers, CADAM and AgentSCAD [H]. **Zoo / KittyCAD text-to-CAD** (zoo.dev) is hosted and needs an API key, so it conflicts with the no-paid-credentials rule. Skip it [M].

---

## Part B: toolchain by layer

Hardware [H]: the MacBook is an M1 with 8 cores, 16 GB RAM and 79 GB free. The Mac Mini is an M4 with 10 cores, 16 GB RAM and only **19 GB free**. Docker is installed on the MacBook, not on the Mini. Homebrew is at /opt/homebrew.

"Agent-friendly" means three things here: driven from a script, with text in and out, and no GUI needed.

### 1. Parametric CAD (code-first)

| Tool | Apple Silicon install | Scriptability | Agent fit | Maturity |
|---|---|---|---|---|
| **build123d** 0.13.0 | `pip install build123d`. Native arm64 wheel via cadquery-ocp 8.0.1 [H] | Pure Python on the OpenCascade B-rep kernel. STEP/STL export | **Best.** Pythonic, with explicit topology selectors. The basis of text-to-cad | Active, 1.0 nearing [M] |
| **CadQuery** 2.8.0 | `pip install cadquery`. Same OCP wheel [H] | Fluent Python API | Very good. Its string selectors are terser but more fragile for LLM-written code | Mature [M] |
| **OpenSCAD** | Homebrew has only 2021.01 [H]. Use the nightly DMG for the Manifold backend | CSG DSL, CLI render | OK for printable parts. Mesh-only output (no STEP), so poor for FEA/CFD | Mature but stale |
| **FreeCAD** 1.1.4 | `brew install --cask freecad` [H] | Full Python API. Headless with `FreeCADCmd`. FEM workbench wraps CalculiX/Elmer/gmsh | Good through freecad-mcp (about 3k stars, MIT, RPC addon inside the GUI) [H]. Headless scripting works but is fiddly | Mature, large |
| **SolidCraft** | DMG, Apple Silicon [H] | CLI plus MCP | Promising but young. Watch it, don't depend on it | Pre-1.0 |
| **Onshape API** | Cloud REST. A free plan exists, but documents are public | REST plus FeatureScript | onshape-mcp exists (experimental). Cloud-only, with public docs on the free tier, so it's a poor fit for private work [M] | Mature platform |

**Pick build123d.** It produces real B-rep and STEP, which gmsh meshes cleanly and FreeCAD/SolidWorks can open.

### 2. Meshing

| Tool | Install | Notes |
|---|---|---|
| **gmsh** 4.15.2 | `pip install gmsh` (arm64 wheel) or `brew install gmsh` [H] | Python API. Imports STEP via OCC. Tags physical groups for boundary conditions. **The default.** Pair with **meshio** 5.3.5 to convert formats [H] |
| **snappyHexMesh** | Comes with OpenFOAM | Hex-dominant CFD meshes from STL. Driven by dictionaries, so scriptable |
| **Salome** | No native macOS build [M] | Linux or Docker only. Skip unless Code_Aster becomes necessary |

### 3. CFD

| Tool | Apple Silicon path | Agent fit | Notes |
|---|---|---|---|
| **OpenFOAM** (v2606/v2512) | **Native:** `brew install gerlero/openfoam/openfoam`. Apple Silicon only, 272 stars [H]. Fallback: the OpenCFD Docker image | Text dictionaries, CLI utilities. LLM agents already target it (Foam-Agent, AgentCFD, openfoam-mcp-server). Python: **foamlib** (by the same author, gerlero) [M] | `chtMultiRegionFoam` handles conjugate heat transfer (solid plus coolant), which is exactly the CPU-loop case. Steep learning curve; meshing for CHT is the hard part |
| **SU2** | No Homebrew formula [H]. Build from source with meson, or use Docker [M] | Config-file driven, Python wrapper | Strong at compressible and adjoint optimisation. Lower priority for thermal work |
| **FluidX3D** | OpenCL on macOS is deprecated but still present [M] | C++ setup, recompiled per case | Fast lattice-Boltzmann on GPUs. **Non-commercial licence** [M]. Good for visuals, not for engineering-grade heat transfer |
| **Basilisk** | Builds from C source with clang [M] | C DSL | Research-grade multiphase. Not a first pick |
| **Reduced-order models** | Pure Python | Excellent | Pipe/duct ΔP, Nusselt correlations, pump curves. This covers about 80% of early design questions. AgentCFD's 0D network solver fits here, or write your own |

### 4. FEA and thermal conduction

| Tool | Apple Silicon path | Agent fit | Notes |
|---|---|---|---|
| **scikit-fem** 12.0.2 | `pip install scikit-fem`. Pure Python [H] | **Excellent.** Steady and transient heat equation in about 30 lines. Reads meshes via meshio | The right first solver: no compiled dependencies, easy to test |
| **CalculiX** (ccx 2.23) | conda-forge osx-arm64 [M]. Also bundled inside FreeCAD.app. No Homebrew formula [H] | `.inp` text decks (Abaqus-like). Python: pygccx, or FreeCAD FEM | Mature for structural, thermal and coupled thermo-mechanical work. **The statics workhorse** |
| **Elmer** | No Homebrew formula [H]. Build from source or via FreeCAD. `pyelmer` 1.2.1 exists [H] | .sif text files | Strong multiphysics (heat, flow, electromagnetics). Installing on macOS takes effort [M] |
| **FEniCSx** (dolfinx) | conda-forge osx-arm64 (0.9+) [M]. Not on PyPI [H] | Python UFL weak forms | Powerful but heavy. Use it if scikit-fem becomes too slow |
| **Code_Aster** | Linux or Docker only [M] | Python command files | Industrial-grade. Overkill for now |

### 5. Thermodynamics and properties

| Tool | Install | Use |
|---|---|---|
| **CoolProp** 8.0.0 | pip, arm64 wheel [H] | Water, glycol mixes, refrigerants, air, with high-accuracy equations of state. **Essential for the cooling loop** |
| **Cantera** 3.2.0 | pip, arm64 wheel [H] | Combustion and kinetics. For the diesel engine and biodiesel transesterification thermochemistry |
| **thermo** 0.6.1 / **chemicals** 1.5.2 (Caleb Bell) | pip, pure [H] | Thousands of chemical properties, including mixtures. Good for biodiesel (methyl esters, methanol, glycerol) |
| **TESPy** 0.11.3 | pip [H] | Thermal plant cycles: pumps, heat exchangers, turbines. Good for the heat-driven cooling idea (absorption or ORC loops) |
| **Lumped thermal networks** | Write your own (numpy/scipy) or use `networkx` | R-C networks (die → TIM → cold plate → coolant → radiator → air). Fast, testable, and the first thing to build |

### 6. Materials data

- **Materials Project** (`mp-api` 0.47.0 [H]): the API key is free with an account [M]. It is computed (DFT) data for crystals: elastic tensors, densities, formation energies. Useful for materials science, but it lacks engineering alloy properties such as yield strength or conductivity for 6061-T6.
- **MatWeb:** has no API, and its terms forbid scraping [M]. Use it by hand only.
- **Open options:** the materials libraries in FreeCAD and CalculiX, the NIST cryogenic/thermal data pages, and `thermo`/`chemicals` for fluids. The pragmatic route is a **small curated `materials.yaml`** in the MARVIN repo: about 30 engineering materials (Cu C110, Al 6061-T6, 304 SS, common thermal interface materials, PEEK, and so on), with values and their sources. It is versioned and auditable, which suits the "log research behind decisions" rule.

### 7. Visualization

- **PyVista** 0.49.1 (pure) on **VTK** 9.7.1 (arm64 wheel) [H]: off-screen PNG rendering from scripts. **This is the default.** Images can then go into tickets and docs per the screenshot rule.
- **ParaView** 6.2.0 cask with `pvpython` [H]: for heavy OpenFOAM results and interactive inspection.

### 8. Electronics

- **KiCad** 10.0.7 cask [H]. The IPC API (`kicad-python` 0.8.0 [H]) needs the KiCad app running. `kicad-cli` handles headless exports (Gerbers, DRC, netlists) [M]. kicad-mcp (lamaalrajih) is experimental.
- **SKiDL** 3.0.0 [H]: defines a schematic in Python and outputs a netlist. A good fit for agents.

### Linux, Docker and offloading

- **Needs Linux/Docker:** Salome, Code_Aster, probably SU2, and the OpenFOAM fallback. **OrbStack** (cask 2.2.4 [H]) is lighter than Docker Desktop and would suit the Mini. With 19 GB free, the Mini can't hold several 2–5 GB images plus case data, so **free disk first or use an external SSD** [H for the disk figure, M for the image sizes].
- **Mac Mini as a solver host:** yes. Run long cases with `ssh gils-mac-mini` and `nohup` through a wrapper script (memory: ssh-nohup gotcha). Native OpenFOAM runs in parallel under MPI across its 10 cores. Use the same task-dispatch primitive MARVIN already has.
- **exo:** not applicable. It shards LLM inference, and MPI solvers don't run through it. Splitting one solver run across both Macs over Tailscale with MPI is possible in principle but not worth the trouble at this scale [L].

---

## Part C: capability ladder

Each rung is usable on its own and adds one capability. Every rung checks itself against a hand calculation, which follows the "tests try to break it" rule.

**Rung 0: hand-calc engine (a skill plus a small library).** `marvin_eng.thermal` provides lumped R-networks, fin and plate correlations, Dittus-Boelter/Gnielinski convection, and pipe ΔP, with CoolProp for coolant properties and a `materials.yaml` table. Result: the full loop budget (CPU W → ΔT at each interface → pump and radiator sizing) in under a second. **This answers most early design questions.**

**Rung 1: geometry.** A build123d script library for parametric parts (cold plate with channels, fin stack, manifold) that exports STEP and STL, plus a PyVista preview PNG. A skill holds the conventions: units in mm, named faces become boundary tags.

**Rung 2: conduction FEA.** STEP → gmsh (Python API, physical groups for heat source, convective face and insulated faces) → **scikit-fem** steady and transient heat equation, with convection as a Robin boundary condition using h from Rung 0 → PyVista temperature map. Validate against the Rung 0 resistance numbers; they should agree within about 10–20%. Result: the first real thermal analysis of the cold plate.

**Rung 3: structural and thermo-mechanical.** The same mesh into CalculiX (conda-forge arm64) for stress, deflection and thermal expansion. This opens statics for brackets, frames and pressure vessels, which covers the biodiesel reactor.

**Rung 4: CFD and conjugate heat transfer.** Native OpenFOAM via the gerlero tap, on the Mini. Start with an internal-channel `simpleFoam` case (the AgentCFD pattern), then move to `chtMultiRegionFoam` for coolant plus solid. Use foamlib for case editing and ParaView/PyVista for post-processing. Consider adopting AgentCFD's `case.py` idea or Foam-Agent's error-repair loop rather than building one.

**Rung 5: process and cycle thermodynamics.** TESPy for the heat-driven cooling cycle, Cantera for engine combustion, thermo/chemicals for biodiesel process mass and energy balances.

**Rung 6: electronics.** SKiDL plus `kicad-cli` for sensor and control boards.

### MCP servers or skills

- **Skills plus a plain Python library (default):** Rungs 0, 1, 2, 3 and 5. These are one-shot, stateless scripts. A skill (conventions plus examples) plus `~/.agents/lib/eng/` modules called from Bash is the smallest composable unit and fits the composability principle. No server process to babysit.
- **MCP servers, only where a live session is the point:**
  - **freecad-mcp**, when Gil wants to see and edit a model interactively in a GUI.
  - **KiCad IPC MCP**, because its API requires the running app.
  - **An OpenFOAM job MCP (later):** submit, poll and fetch residuals for long runs on the Mini. This could wrap the existing task-dispatch primitive instead of being new.
- **Adopt rather than build:** try **text-to-cad**'s skills (build123d/OCP) as a reference or install, with telemetry off, before writing Rung 1 from scratch (the check-for-reuse rule). Keep an eye on SolidCraft's MCP server as a future GUI CAD target.

### Smallest first deliverable

`eng-thermal` skill: give it "CPU 150 W, 40×40 mm copper cold plate, 6 channels, 1 L/min 30% glycol" and it returns:
1. The lumped ΔT budget.
2. A build123d STEP file.
3. A gmsh/scikit-fem steady temperature field.
4. A PyVista PNG.
5. A markdown note that cites its correlations and material sources.

Everything installs from pip (build123d, gmsh, meshio, scikit-fem, CoolProp, pyvista) into a dedicated venv, which is roughly 1.5 GB and has no Docker or Homebrew solver dependencies [M]. Per the doc-first rule, this needs a short design doc and task list before any code. It also should not start until Seal Speak ships.

---

## Sources

- SolidCraft README: https://raw.githubusercontent.com/bherbruck/solidcraft/main/README.md
- "Vibecoded clones of SolidWorks and AutoCAD released as open-source" (3D Printing Industry): https://3dprintingindustry.com/news/vibecoded-clones-of-solidworks-and-autocad-released-as-open-source-255770/
- SolidCraft coverage: https://botmonster.com/ai/solidcraft-is-a-fusion-360-alternative-ai-wrote-in-10-days/ ; https://explainx.ai/blog/solidcraft-open-source-rust-parametric-cad-mcp-agents-2026
- text-to-cad: https://github.com/earthtojake/text-to-cad
- AgentCFD: https://github.com/haoming-luo/agentcfd
- Millwright: https://github.com/raylanlin/Millwright
- SolidAI: https://github.com/ghosessx/SolidworksAi
- SolidWorks MCP listings: https://glama.ai/mcp/servers/vespo92/SolidworksMCP-TS ; https://mcpservers.org/servers/haunchen/solidworks-mcp ; https://glama.ai/mcp/servers/yimu0824/solidworks-mcp
- sim-cli: https://github.com/svd-ai-lab/sim-cli
- Awesome-Physical-Engineering-AI: https://github.com/010zx00x1/Awesome-Physical-Engineering-AI
- Foam-Agent papers: https://arxiv.org/abs/2505.04997 ; https://arxiv.org/html/2509.18178v2
- OpenFOAMGPT: https://arxiv.org/pdf/2501.06327
- MetaOpenFOAM review: https://themoonlight.io/review/metaopenfoam-an-llm-based-multi-agent-framework-for-cfd
- OpenFOAM for macOS (gerlero): https://github.com/gerlero/openfoam-app
- freecad-mcp: https://github.com/neka-nat/freecad-mcp
- CalculiX on conda-forge: https://anaconda.org/conda-forge/calculix/files
- FEniCSx on Apple Silicon: https://fenicsproject.discourse.group/t/installing-fenicsx-using-conda-on-mac-m1-and-m2-chips/16579
- FluidX3D licence (AUR listing): https://aur.archlinux.org/packages/fluidx3d
- forgehub.engineering landing page (fetched 2026-10-21)
- Local checks on 2026-10-21: `brew info` (gmsh, openscad, open-mpi, freecad, paraview, kicad, orbstack casks), PyPI JSON for arm64 wheels, `pip index versions`, and hardware/disk on both Macs.
