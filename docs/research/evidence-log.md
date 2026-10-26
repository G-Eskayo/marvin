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
