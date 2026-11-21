# Evidence log: the research behind MARVIN's decisions

One entry per source (or tight source group). Each says what we took from it, how strong it is, and which decision it
drives, so the portfolio and docs can show the reasoning, not just the result. **Add an entry whenever research
informs a decision**, and link the doc, ADR, PR or ticket it drove. Format follows clarity-captions'
`docs/research/evidence-log.md`.

Confidence: **Strong** (controlled study or official documentation), **Moderate** (guideline or several consistent
sources), **Weak** (single small study, secondary report or anecdote), **Ours** (our own measurement or arithmetic).

Public use: **Yes** (fine to cite as written), **Careful** (cite with its caveat), **Internal** (process detail).

---

## MARVIN Surface (hardware), 2026-10-21

Full report: [`marvin-surface-display-2026-10-21.md`](marvin-surface-display-2026-10-21.md).

### E1. Transparent OLED is too low-resolution for desktop text
- **Source:** [LG 30EW5TP-A spec sheet](https://solutions.lg.com/us/digital-signage/lg-30ew5tp-a) (1366x768, 37%
  transparency, $7,500 list, out of stock); 55EW5 listings (1920x1080).
- **What we took:** 52 PPI (30") and 40 PPI (55"), against 138 PPI for a 32" 4K monitor. Pixels are visible at desk
  distance.
- **Confidence:** Ours (arithmetic on Strong specs).
- **Drives:** transparent OLED is a later, secondary ambient display, not the main Surface.
- **Public use:** Yes.

### E2. Transparent LCD passes about 10–15% of light, and black pixels block it
- **Source:** [US6697135](https://patents.google.com/patent/US6697135) (an ordinary color TFT stack passes about
  7.4%); [Samsung 22" transparent LCD, over 15%](https://www.hartware.de/?p=114062).
- **What we took:** a transparent LCD over a back glow looks like smoked glass, and its "luminous on black" look is
  glowing lines on a dark slab, not invisible black.
- **Confidence:** Moderate.
- **Drives:** V1 of Gil's concept (transparent LCD + edge-lit acrylic) exists to test readability before any V2
  spend.
- **Public use:** Careful.

### E3. Large "external-light" Sharp-style panels don't exist; reflective LCDs are opaque
- **Source:** [Sharp Memory LCD line-up, up to 4.4"](https://www.businesswire.com/news/home/20221013005073/en/);
  [Sun Vision 32" RLCD, 25:1, $1,549](https://www.e-ink-info.com/sdc-32-inch-color-rlcd-monitor).
- **What we took:** the concept maps to a transparent LCD with a light guide behind it, not a reflective panel.
- **Confidence:** Moderate.
- **Drives:** panel choice for V1–V2.
- **Public use:** Yes.

### E4. Cast acrylic cold-bends to about 330x its thickness
- **Source:** [Acrylite minimum cold-bend radius](https://www.acrylite.co/resources/knowledge-base/article/what-is-the-minimum-raduis-acrylite-acrylic-sheet-can-be-cold-bent).
- **What we took:** 6 mm sheet → R ≥ 2.0 m; a flat 32" panel behind R 2 m leaves about a 3 cm edge gap.
- **Confidence:** Strong (manufacturer data) + Ours (geometry).
- **Drives:** curve strategy: flat display, curved carrier (V2); thermoform or bent glass only in V3.
- **Public use:** Yes.

### E5. macOS has no native touchscreen model
- **Source:** [Apple Developer Forums #829408](https://developer.apple.com/forums/thread/829408);
  [Touch-Base UPDD](https://touch-base.com/);
  [MacRumors on Alogic, June 2026](https://www.macrumors.com/2026/06/19/alogic-touchscreen-monitors-portable-displays/).
- **What we took:** touch on the M4 mini needs UPDD or vendor software. The shell should read input through an
  abstraction layer (Pointer Events + TUIO) so Linux can host it with native multitouch.
- **Confidence:** Moderate.
- **Drives:** MARVIN OS shell input design.
- **Public use:** Careful.

### E6. Touch at a desk loads the neck and shoulders; upright touch screens tire fastest
- **Source:** [Hincapié-Ramos et al., CHI 2014, Consumed Endurance](https://doi.org/10.1145/2556288.2557130);
  [UNIST desktop-touch study](https://scholarworks.unist.ac.kr/handle/201301/46811);
  [Schultz & Batten 1998](https://davidbatten.yolasite.com/resources/Website_Documents/schultzBatten1998.pdf).
- **What we took:** hybrid keyboard + touch, with touch for short big-target actions. A lower, tilted mount if touch
  is primary.
- **Confidence:** Strong.
- **Drives:** Surface ergonomics; the shell's touch-target sizing.
- **Public use:** Yes.

### E7. Text on see-through displays needs a solid backing ("billboard")
- **Source:** [Scharff & Ahumada 2002, *J. Vision*](https://laurenscharff.com/research/transtext.html);
  [TU Delft overlay-legibility study](https://repository.tudelft.nl/file/File_15420783-93bb-4277-8305-e4f285d0ea27).
- **What we took:** a busy background costs reading speed (masking index, r ≈ 0.9). Billboards and drop shadows
  restore it.
- **Confidence:** Strong (AR/HUD context, transferable).
- **Drives:** MARVIN OS text panels get dark translucent backing plates; the transparency simulator tests them.
- **Public use:** Yes.

---

## Knowledge graphs, 2026-10-26

Full report: [`knowledge-graphs-2026-10-26.md`](knowledge-graphs-2026-10-26.md).

### E1. Graph retrieval loses to plain RAG on single-hop questions
- **Source:** [Han et al., RAG vs. GraphRAG](https://arxiv.org/abs/2502.11371);
  [GraphRAG-Bench](https://arxiv.org/abs/2506.05690).
- **What we took:** graphs win only on multi-hop questions. Route to them; don't default to them.
- **Confidence:** Strong.
- **Drives:** gold-question eval before keeping "graphify first" in CLAUDE.md; graph traversal as an opt-in tool.
- **Public use:** Yes.

### E2. LLM-judged graph-RAG wins are inflated by position bias
- **Source:** [Zeng et al.](https://arxiv.org/abs/2506.06331).
- **What we took:** comparing a system with itself swung win rates by more than 30 points depending on answer order.
  Use known-answer recall@k.
- **Confidence:** Strong.
- **Drives:** the eval scores against ground truth, not an LLM judge.
- **Public use:** Yes.

### E3. Bi-temporal facts, invalidate instead of delete
- **Source:** [Zep/Graphiti paper](https://arxiv.org/html/2501.13956v1).
- **What we took:** facts carry valid/invalid and learned/retired times; contradictions retire old facts.
- **Confidence:** Strong (design); Moderate (benefit, single vendor paper).
- **Drives:** proposed `valid_from`/`invalid_at`/`superseded_by` memory frontmatter.
- **Public use:** Yes.

### E4. Auto-built code graphs go stale and drown in hub files
- **Source:** [practitioner test of graphify vs ripgrep](https://praveenvijayan.substack.com/p/your-knowledge-graph-is-making-your);
  our own measurement (graph 84 commits behind HEAD, 242 MB of unpruned snapshots).
- **What we took:** staleness, not schema, is the main failure of our code graph.
- **Confidence:** Weak (3 queries) plus Ours.
- **Drives:** graphify rebuild on merge/rewrite, a stale-graph warning, snapshot pruning.
- **Public use:** Careful.

### E5. On MARVIN's own questions, keyword grep beats graphify; memory_graph wins on memory
- **Source:** our retrieval eval, 2026-10-26 (`bench/RESULTS.md`, marvin#705). 30 questions with known answers, no LLM
  judge.
- **What we took:** hit@5 was rg 0.67 against graphify 0.38. On multi-hop questions graphify scored 0 of 4 and rg 3
  of 4. memory_graph related scored 0.83 on memory questions, at about 1/12 of rg's tokens.
- **Confidence:** Ours (n = 30, one author; a single-pass rg understates an agent's real grep).
- **Drives:** PR #713's decision on the graphify-first rule in CLAUDE.md; memory_graph as the memory retriever.
- **Public use:** Careful.

### E8. A control-led review prompt beat the built-in review on unseen apps, at similar cost
- **Source:** our A/B, 2026-11-06 (marvin#1158). `security-sweep` vs `/security-review` vs Cloudflare's security-audit skill (MIT). Two held-out apps written by a separate agent, 12 planted bugs and 6 decoys each, 3 runs per arm per app, Sonnet, blind Opus scoring.
- **What we took:** bugs found were 72 of 72 for `security-sweep` and 67 of 72 for `/security-review`, at about $0.19 and $0.16 a run. Cloudflare's skill found 59 of 60 in valid runs at about $3. No arm flagged a decoy. `security-sweep` also produced 4 wrong extra findings.
- **Confidence:** Ours (6 runs per arm, near the ceiling, one model; the planted-bug apps are synthetic).
- **Drives:** `skills/security-sweep`; Cloudflare's skill kept for occasional deep audits only.
- **Public use:** Careful.

### E9. ASD-STE100 prompting read easier but lost blind preference
- **Source:** our A/B, 2026-11-06 (marvin#1158). 12 technical questions, 2 reps, plain vs STE vs `caveman`, blind Opus judge.
- **What we took:** STE dropped reading grade from 6.9 to 4.8 with similar fact coverage, but plain beat it 39 to 9 and `caveman` beat it 36 to 12.
- **Confidence:** Ours (a model judge, written text only).
- **Drives:** STE not adopted as a default.
- **Public use:** Careful.

---

## Rooting a 1st-gen HomePod to retire Siri, 2026-11-20

Research for marvin#651: can we checkm8-root one 1st-gen HomePod (AudioAccessory1,1, on HomePod
software 27.2), take over its mics and speaker, and keep it rooted. These are hobbyist/forensic
sources (general web + two vendor forensics blogs + three GitHub repos); no academic tier applies.

### E10. Opening the glued base is the real risk; the diagnostic port is a known USB/UART pad
- **Source:** [ElcomSoft, HomePod Forensics I](https://blog.elcomsoft.com/2023/03/homepod-forensics-i-pwning-the-homepod/);
  [UnbendableStraw/homepwn-simple](https://github.com/UnbendableStraw/homepwn-simple).
- **What we took:** the bottom lid is glued; warm it with a fan in 10–15 s bursts and pry with a flat
  screwdriver. Over-heating melts the material and the lid can be damaged — this voids the warranty and
  is "not for casual users." Under the lid is a combined USB/UART port. Pinout (top row, port up):
  NC, TX, RX, CTRL, D+, D-, GND. USB-only restore/root needs four probes (+5V, D+, D-, GND); UART is
  **1.8 V only** (3.3/5 V damages it), console at 115200 baud via an FTDI 1.8 V adapter. Pogo pins
  P75-D2/P75-J1, held by four M2x6 screws.
- **Confidence:** Strong (two independent sources, one a detailed build repo).
- **Drives:** the mechanical step is the gating risk; buy or print the adapter, don't solder to pads.
- **Public use:** Careful.

### E11. The adapter is open-source and also sold pre-made; no published price
- **Source:** [UnbendableStraw/homepwn-simple](https://github.com/UnbendableStraw/homepwn-simple) (OpenSCAD
  + STL for adapter, stand and dock); author's shop at nicsfix.com/shop.
- **What we took:** the PCB-less pogo-pin adapter, a table stand and a dock are free STL/OpenSCAD files;
  BOM is 4x M2x6 screws, pogo pins, a USB cable, and (for UART) a 1.8 V FTDI adapter such as a DSD TECH
  SH-U09C5. Pre-assembled docks/adapters are sold at nicsfix.com/shop, but no price appeared in the
  sources (Unknown as of Nov 2026).
- **Confidence:** Strong (files) / Weak (shop price unseen).
- **Drives:** buy-vs-print decision on #651.
- **Public use:** Careful.

### E12. checkm8 root is real and unpatchable, but no published tooling produces a working jailbroken boot on audioOS 26/27
- **Source:** [checkra1n 0.12.1 partial HomePod support, 2020](https://9to5mac.com/2020/11/20/first-generation-homepod-can-now-be-jailbroken-with-checkra1n/)
  (CLI-only, tested audioOS 13/14); [ElcomSoft, Nov 2025](https://blog.elcomsoft.com/2025/11/exploring-ipados-tvos-and-audioos-17-and-18-devices-file-system-and-keychain-extraction/)
  (EIFT 8.81 extends checkm8 to 1st-gen HomePod on OS 17/18, but "does not support checkm8 extractions"
  on audioOS/tvOS 26 builds); [UnbendableStraw/homepod-restore](https://github.com/UnbendableStraw/homepod-restore)
  (gaster + idevicerestore; warns builds newer than 18.3 "may restore fine but boot loop after a reset").
- **What we took:** the A8 bootrom flaw (checkm8) cannot be patched by any OS update, so 27.2 does not
  close the door. But every published HomePod path tops out well below 27: checkra1n tested at 13/14,
  restore/boot stable only up to ~18.3, forensic extraction not yet on 26. So on 27.2 root is possible
  in principle, but the known-good jailbreak+boot path has **not** been demonstrated. Practical route:
  restore/downgrade the target to a known-good version (≤18.3) first, then root — not root 27.2 directly.
  Current tooling is **gaster** (maintained checkm8 impl) + `idevicerestore` + a custom ipsw, not the
  stale checkra1n.
- **Confidence:** Moderate (bootrom fact Strong; the "no working 27.x boot" is absence-of-evidence across
  the maintained sources, not a proof of impossibility).
- **Drives:** plan #651 should budget a downgrade step; don't assume 27.2 roots as-is.
- **Public use:** Careful.

### E13. Host can be the Mac mini M4; a Pi can't yet run the exploit, only automate DFU entry
- **Source:** [UnbendableStraw/homepod-restore](https://github.com/UnbendableStraw/homepod-restore)
  (Mac tested on Apple Silicon and Intel; Linux "should work" untested; Homebrew + libimobiledevice +
  `gaster` + pinned `idevicerestore`); [ElcomSoft, Automating DFU with a Raspberry Pi Pico](https://blog.elcomsoft.com/2023/04/automating-dfu-mode-with-raspberry-pi-pico/)
  (Pi Pico drives the Lightning ID lines to force DFU on iPhones, not HomePods);
  [MatthewPierson/PyBoot](https://github.com/MatthewPierson/PyBoot) (tether-boots checkm8 iOS devices,
  macOS-only, author warns it is "most likely extremely broken").
- **What we took:** the Mac mini M4 is a confirmed-good host. A Raspberry Pi is not a demonstrated host
  for the exploit itself — the only Pi work automates the DFU-entry button sequence, not the jailbreak.
- **Confidence:** Moderate.
- **Drives:** run the exploit from the Mini; a Pi is a candidate only for DFU automation, unproven.
- **Public use:** Careful.

### E14. Tethered re-root on every boot is unbuilt for HomePod
- **Source:** checkm8 is tethered (re-run each boot) per all sources above; no project automates HomePod
  re-root. [joeblackwaslike/homepod-update](https://github.com/joeblackwaslike/homepod-update) blueprint
  says only "you can always re-jailbreak" (manual).
- **What we took:** an always-attached Pi/Pico that re-runs `gaster pwn` + tether-boot on power-up is
  feasible in principle but nobody has published it for the HomePod. This is net-new engineering.
- **Confidence:** Moderate (feasibility is inference from how checkm8 tethered boot works elsewhere).
- **Drives:** scope a bespoke re-root rig as its own task; don't assume an off-the-shelf solution.
- **Public use:** Careful.

### E15. Blocking OTA updates on a rooted HomePod is undocumented
- **Source:** web search returned no method; [joeblackwaslike blueprint](https://github.com/joeblackwaslike/homepod-update)
  notes checkm8 "cannot be patched" by OTA but that updates still wipe tweaks (reinstall needed).
- **What we took:** no published HomePod-specific OTA block. Generic options (block Apple update
  endpoints at the router/DNS, or disable the update daemon on the rooted filesystem) are untested here.
- **Confidence:** Weak (absence of sources).
- **Drives:** treat OTA-blocking as unsolved; likely a router/DNS block plus keeping the device off
  Apple's update path.
- **Public use:** Careful.

### E16. Mic access from root: a concrete blueprint now exists, but nothing working has been demonstrated
- **Source:** [joeblackwaslike/homepod-update](https://github.com/joeblackwaslike/homepod-update) and its
  [docs/blueprint.md](https://raw.githubusercontent.com/joeblackwaslike/homepod-update/main/docs/blueprint.md)
  (© 2026, 6 stars, 0 forks, 5 commits, no releases).
- **What we took:** the project proposes a MobileSubstrate tweak that `MSHookFunction`s `AudioUnitRender`
  inside `mediaserverd`, copies the bus-1 buffer (assumed to be the beamformed mic array), and streams it
  48 kHz/16-bit mono over the Wyoming protocol (TCP 10700) to a server; a Go dashboard on port 8080
  monitors it. Replies come back via AirPlay/Shairport Sync, so the **speaker is not driven directly** —
  "no speaker-side injection code needed." Crucially the doc is an **untested blueprint**: it hedges
  throughout ("assumed," "likely," "update asbd_* constants if they differ") and has unfinished code.
  This updates our prior "nobody has published mic access": a published *design* exists, but no working
  demonstration, and the mic-array-on-bus-1 assumption is unverified.
- **Confidence:** Weak (single unverified hobby repo, self-described as untested).
- **Drives:** the mic-capture daemon is still the research risk on #651; the blueprint is a starting
  point, not a solution. Direct speaker injection into the render graph remains unpublished.
- **Public use:** Careful.

### E17. DFU restore through the same port recovers software bricks; speaker works as a stock USB gadget
- **Source:** [UnbendableStraw/homepod-restore](https://github.com/UnbendableStraw/homepod-restore)
  (`gaster pwn` → `gaster reset` → `idevicerestore -d -e signed.ipsw`, pre-built signed 18.3 ipsw provided,
  10–15 min, Mac + Homebrew); [9to5Mac, Aug 2024](https://9to5mac.com/2024/08/09/fix-software-bricked-homepods/);
  the diagnostic port also exposes a stock USB-audio gadget (HomePod appears as a USB speaker to a
  connected Mac) on HomePod software 14.0+ (homepwn-simple README).
- **What we took:** the software side is recoverable — the same port that roots it also DFU-restores it,
  so a bad flash is not a brick. That de-risks everything except the one-time mechanical act of opening
  the base. Separately, the speaker can be driven over USB with no jailbreak at all (output-only, needs a
  permanent USB host), which is a lower-risk fallback for playback.
- **Confidence:** Strong (restore) / Moderate (USB-gadget audio).
- **Drives:** mechanical risk dominates; software failures are reversible. USB-audio is a no-root
  fallback for the speaker if root stalls.
- **Public use:** Careful.
