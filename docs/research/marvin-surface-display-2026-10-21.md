# MARVIN Surface: display, touch and shell research

*Research pass, 2026-10-21. Written for Gil. Method: `skills/research/SKILL.md` (triangulate, tier confidence,
separate fact from inference). Most of this is a practical/hardware question, so the sources are mostly the practical
ladder: manufacturer spec sheets (Tier 2), distributor price listings, and maker write-ups (Tier 3). The ergonomics
and legibility sections use peer-reviewed HCI work (Tier 1). Every source tier is marked.*

**What "MARVIN Surface" means here** (from `CONTEXT.md`, "Endpoints and the brief"): an endpoint with at least
*show* and *touch*, with a holographic look. This report asks what hardware and software could make it real, and
whether it can be Gil's everyday desktop.

---

## TL;DR

**Gil's concept (headline, added 2026-10-21):** a sharp, external-light LCD over glass or acrylic; one long, gently
curved sheet held by legs at each end; LEDs shining into the sheet's edges for a soft back glow; built in versions
by price.

1. **"Sharp" panels that use only external light don't come at monitor size, and they aren't see-through.**
   - **Sharp's own Memory-in-Pixel LCDs top out at 4.4 inches.** *(Established, Sharp/Mouser.)*
   - **Reflective LCD monitors** (one that uses room light instead of a backlight) reach 32" (Sun Vision Display,
     about $1,549 in 2022, 1080p, **25:1 contrast**). But they have a mirror layer behind the pixels, so they're
     **opaque** and a glow from behind can't pass through.
   - The panel that fits Gil's idea is a **transparent LCD**: a color LCD with no backlight that is lit by whatever
     is behind it. That's exactly how commercial "transparent showcase" boxes work. *(Likely.)*
2. **Transparent LCD in front of an edge-lit acrylic light guide is buildable and cheap.** It's the right V1.
   - **How it works:** a light-guide plate (LGP) is a clear acrylic sheet with a dot pattern that sends light from
     its edges out through its face. Behind the LCD it acts as the backlight when the LEDs are on, and as clear glass
     when they're off.
   - **The catch:** the panel only passes about 10–15% of the light behind it, so it looks like **smoked glass,
     not clear glass**. *(Samsung quoted over 15% for its color transparent LCD; ordinary LCD stacks pass about
     5–7%.)*
   - **The look inverts.** On an LCD, **black pixels block light**. "Luminous lines on black" renders as **glowing
     lines on a dark smoked slab**, and the see-through part is the *bright* areas, not the black.
     It still looks sleek and sci-fi, but the black isn't "invisible" the way it is on OLED. *(Likely, from how
     LCDs work.)*
3. **Sharpness:**
   - A **32" 1080p transparent LCD is about 69 PPI** and a **21.5" 1080p is about 102 PPI**, much better than the
     buyable transparent OLEDs (40–57 PPI). It's usable for large-type desktop work. Not a code editor at 12 pt.
   - Contrast and color are weak. One JDI see-through LCD quoted 16:1; typical transparent LCDs are low-contrast.
4. **Curve: keep the display flat and curve only the carrier.**
   - **Cold-bent acrylic:** cast acrylic can be cold-bent to about **330x its thickness** (Acrylite). 6 mm sheet bends
     to about R 2.0 m and 4 mm to about R 1.3 m. Gil can do this by hand into curved brackets, with no oven.
   - **Flat panel behind the curve:** a flat 32" panel behind an R 2 m curve has only about a **3 cm gap at its
     edges**, so a flat display set into a gently curved sheet looks right.
   - **Truly curved displays:** among usable monitors, the main one is the **Corsair Xeneon Flex 45"**, a bendable OLED
     ($1,999 list, seen at $1,199 on sale). It's opaque, so it's the "dream curve" alternative, not a transparent one.
5. **Touch:**
   - **IR frames** need a flat plane, so use one over the flat display only.
   - **PCAP foil** (flexible PET film that senses touch through glass, e.g. Zytronic ZYFILM up to 85", through glass up
     to 10 mm) is the option that can follow a gentle curve.
   - **On macOS**, touch needs a third-party driver (UPDD) either way. See §2 and §4.
6. **Version ladder:**
   - **V1 proof of concept:** about **$450–$1,100**, 1–3 weekends.
   - **V2 nicer build:** about **$1,800–$3,500**, about 1–2 months.
   - **V3 dream curve:** about **$5,000–$12,000+**, 3–6+ months.

   See the diagram: [`marvin-surface-builds.svg`](marvin-surface-builds.svg).
7. **Strongest alternative:** a "black-glass" 32" 4K OLED behind dark glass, about $1,100–$1,700. It's sharper and
   has true black, but it isn't see-through or light-guided (§6). Software can start now on any monitor, with a
   transparency simulator (§6).

---

## 0. Gil's concept: transparent LCD + edge-lit curved acrylic

### 0.1 Which panels fit "external light + glass + back glow"

| Panel type | Uses external light? | See-through? | Works with an edge-lit acrylic backlight? | Biggest you can buy | Desktop sharpness | Price |
|---|---|---|---|---|---|---|
| **Sharp Memory-in-Pixel (reflective)** | Yes | No (mirror layer) | No (front light only) | **4.4"** ([Sharp line-up](https://www.businesswire.com/news/home/20221013005073/en/), [Mouser](https://www.mouser.com/new/sharp-microelectronics/sharpmemorylcd/)) | n/a at this size | samples |
| **Reflective LCD monitor (RLCD)** | Yes | No | No (needs a *front* light) | **32" 1080p** (Sun Vision Display; YouriTaike), 25:1 contrast ([E Ink info](https://www.e-ink-info.com/sdc-32-inch-color-rlcd-monitor), [DisplayDaily](https://displaydaily.com/reflections-on-the-desktop-and-outside/), [GoodEReader](https://goodereader.com/blog/e-paper/chinese-company-youritaike-launches-32-inch-hd-rlcd-android-color-monitor)) | 69 PPI, paper-like, low contrast | about $1,549 (2022); $1,500–$2,500 |
| **Reflective LCD tablet** (Daylight DC-1) | Yes, amber backlight optional | No | No | 10.5" mono, 190 PPI ([Liliputing](https://liliputing.com/daylight-computer-dc-1-is-a-799-tablet-with-a-live-paper-display-designed-to-be-easy-on-the-eyes-but-not-the-wallet/), [SlashGear](https://www.slashgear.com/1655111/daylight-computer-live-pap)) | sharp, but tiny and mono | $729 (2024) |
| **Transflective LCD** | Partly | No | Partly | mostly small industrial | n/a | n/a |
| **Transparent LCD (no backlight)** | **Yes, light from behind** | **Yes, about 10–15%** | **Yes. This is how showcases work** | 5"–84" kits (Crystal Display Systems) ([rAVe](https://ravepubs.com/?p=83020)); 32"–55" boxes on Alibaba/Made-in-China | 21.5" 1080p = 102 PPI; 32" 1080p = 69 PPI; 55" 4K about 80 PPI | 32" showcase from **$499–$600, MOQ 1** (Alibaba, Made-in-China; unverified trade prices); CDS, Pro Display, Planar, BenQ by quote |

Transmission figures: [patent US6697135](https://patents.google.com/patent/US6697135) (about 7.4% for an ordinary
color TFT stack; the color filter alone passes 27%); [Samsung 22" transparent LCD, over 15%](https://www.hartware.de/?p=114062);
[JDI 80% field-sequential see-through LCD, 16:1](https://www.laserfocusworld.com/detectors-imaging/article/16569450/japan-display-reveals-details-on-its-transparent-liquid-crystal-display).

**Verdict:** the honest reading of "a Sharp-style display relying on external light, over glass, with a back glow" is
a **transparent LCD with a light-guide plate behind it**. Reflective panels are opaque. **Confidence: Likely.**

**Things to know before buying a transparent LCD:**
- **The panel's state when unpowered (unknown, check per panel).** Many IPS panels go dark with no signal ("normally
  black"). The Surface may look dark when the Mac sleeps unless the shell shows a light idle state. Ask the seller
  for the panel's mode.
- **Driver board:** showcase kits ship with their own HDMI board. A bare panel needs a board matched to its exact
  model, so buy a kit.
- **Ownership cost:** no burn-in (it's an LCD), and very low power, since there's no backlight of its own. Your LEDs
  are the light.
- **What it looks like:**
  - With the glow **on**, white and bright UI glows and black reads as dark smoked glass.
  - With the glow **off** in a lit room, bright UI areas show the room behind, faintly.
  - With the glow off in a dark room, the panel is nearly invisible.

### 0.2 Curved vs flat: the honest options

| Option | How | Pros | Cons | Rough extra cost |
|---|---|---|---|---|
| **A. Flat display set into a curved carrier** (recommended) | Flat panel (plus its own flat LGP) mounted behind or within a gently curved acrylic or glass sheet | Cheap; any panel; the curve is pure structure and aesthetics | Small air gap at the panel's edges (table below); touch on the curve has a little parallax there | $100–$600 for the curved sheet |
| **B. Several flat panels angled along the curve** | 2–3 transparent LCDs, each tilted a few degrees | Wide "wraparound"; each panel is cheap | Transparent LCDs have driver bezels on one or two edges, so you see seams; 2–3 video outputs (the M4 mini drives up to 3 displays); harder to align | x2–3 panels + brackets |
| **C. Bendable or flexible display** | Corsair Xeneon Flex 45" bendable OLED (3440x1440, 83 PPI) | Real curve, OLED blacks | **Opaque**; no edge-glow concept; $1,199–$1,999 | +$1,200–$2,000 |
| | Flexible e-paper | Bends | Small sizes; slow refresh | n/a |
| | Factory-curved LCD monitor | Cheap | Opaque | +$300–$800 |
| **D. Curve only the carrier, display flat** | Same as A, framed as "the glass is the sculpture" | Simplest | Same as A | Same as A |

**Edge gap (sagitta) of a flat panel behind a curve** (computed: gap = R − √(R² − (w/2)²)):

| Curve radius | 21.5" panel (476 mm wide) | 32" panel (about 700 mm) | 1 m-wide segment |
|---|---|---|---|
| R 1.0 m | 29 mm | 63 mm | 134 mm |
| R 1.5 m | 19 mm | 41 mm | 86 mm |
| R 2.0 m | 14 mm | 31 mm | 64 mm |
| R 3.0 m | 10 mm | 20 mm | 42 mm |

At R ≥ 2 m, a flat 32" panel sits within about 3 cm of the curve: hidden by a 3 cm standoff and invisible at viewing
distance. **Confidence: Established** (geometry).

### 0.3 Edge-lit acrylic (the back glow)

- **How it works (Tier 3, consistent across suppliers):**
  - Light enters the acrylic edge and stays trapped inside by total internal reflection.
  - Printed, laser-etched or V-grooved **dots break that reflection** and send light out of the face.
  - The dots get **denser further from the LEDs**, which evens out the glow.
  - Sources: [LightBurn forum](https://forum.lightburnsoftware.com/t/light-guide-panel/128964),
    [LIGHTPANEL](https://www.newswire.com/view/content/lightpanel-usa-inc-presents-first-ul-listed-laser-cut-laser-engraved-21002695),
    [aspectLED](https://cdn.aspectled.com/downloads/cut-sheets/lighted-panels/AL-LP-12x12-U.pdf).
- **Buy or make the plate:**
  - **Factory LGP** (laser-dotted, up to 12 mm thick, custom shapes): USD 32 for 1200x500x4 mm at MOQ 100 from
    Shenzhen ([Cosun](https://b2usa.com/hotsite/cosuntechnology/laser-dotted-with-strong-uv-resistant-li)). One-off
    custom plates are by quote; LIGHTPANEL does up to 48"x96" with next-day samples.
  - **DIY:** cast acrylic (not extruded) plus a laser engraver at a makerspace. Expect test cuts.
- **Keep the see-through look:** a dotted LGP is slightly hazy.
  - Put the dots **only behind the display area**.
  - Leave the rest of the long sheet clear, or edge-lit only at its polished edges for a glowing outline. That outline
    is a strong Evangelion/Stark cue.
- **Long or curved panels:**
  - Light from both long edges, top and bottom, rather than the short ends. A 1.5 m path from one end won't stay even.
  - Gentle curves (R ≥ 1 m) keep the light trapped inside the sheet. Tight thermoformed bends leak light at the bend.
    *(Inference from the optics of total internal reflection.)*
- **LEDs:**
  - 24 V strip in an aluminium channel pressed to a **polished** edge; 5 mm acrylic matches 5 mm strips.
  - **CRI ≥ 90–95**, **tunable white (2700–6500 K)** or RGBW for a cyan accent.
  - About 5–10 W/m. Heat is small, but give the strip a channel to sink into, because acrylic softens around
    80–90 °C. *(Common practice; datasheet-dependent.)*
- **Control from MARVIN:**
  - An ESP32 running **WLED** firmware (open source; has an HTTP/JSON API) drives the strip.
  - A photoresistor or a light-sensor chip (e.g. VEML7700) on the ESP32 measures room light. MARVIN then sets
    brightness and colour temperature over WLED's API: brighter backing in a bright room, warm and dim at night.
  - WLED's built-in "auto brightness" is a power cap, not an ambient-light feature. Ambient control needs a usermod
    or external automation (Node-RED, Home Assistant, or MARVIN itself):
    [WLED](https://github.com/kolori-dev/WLED), [Node-RED WLED flow](https://flows.nodered.org/flow/2be50f814b08919a6a699e3e26b970b6).
  - **Confidence: Likely.**
- **The shell controls the glow too.** MARVIN OS can raise the glow behind a panel when it shows a bright item and drop
  it when the UI is mostly dark. That one control loop (screen content plus room light → LED level) is what makes it
  feel alive.

### 0.4 Touch on a curved or large surface

| Tech | Fits a curve? | Notes | Price |
|---|---|---|---|
| IR frame | **No** (needs a flat plane) | Fine over the flat display segment in options A and D; raised 5–10 mm bezel | $40–$190 (32") |
| PCAP foil on the back of the carrier | **Yes, gentle curves** | Zytronic ZYFILM: flexible PET, rollable, up to 85", senses through glass up to 10 mm ([InCompliance](https://incompliancemag.com/zytronic-introduces-zyfilm-multitouch-a-rollable-flexible-projected-capacitive-touch-film)); Zytronic PET sensors can go on "some curved surfaces" ([eeNews](https://www.eenewseurope.com/en/projected-capacitive-touch-sensor-range-can-curve)); a 26" curved PCAP demo exists ([Printed Electronics Now](https://www.printedelectronicsnow.com/contents/view_breaking-news/2014-06-05/cima-nanotech-reveals-26-inch-curved-projecte/)) | $1,300 (32" flat foil, Two Way Mirrors); curved by quote |
| Laminated touch glass | Flat, unless custom | Best feel; custom curved lamination is industrial-only | quote |

**Recommendation:** in V1 and V2, put touch only over the flat display, with an IR frame or a flat PCAP foil. A curved
PCAP foil over the whole sheet belongs to V3. Exact bend limits for these foils weren't published. **Confidence:
Plausible.**

### 0.5 Structure: the long curved sheet on two legs

| Material | Weight (1.5 m x 0.6 m x 6 mm) | Clarity | Scratch | Bending | Safety | Notes |
|---|---|---|---|---|---|---|
| **Cast acrylic (PMMA)** | **about 6.4 kg** (1.19 g/cm³) | about 92% transmission, best edge-lighting | Scratches easily (hard-coat optional) | Cold-bend to about 330x thickness (Acrylite: [min radius](https://www.acrylite.co/resources/knowledge-base/article/what-is-the-minimum-raduis-acrylite-acrylic-sheet-can-be-cold-bent)); 6 mm → R ≥ 2.0 m, 5 mm → 1.65 m, 4 mm → 1.32 m; thermoform for tighter (about 160–180 °C) | Breaks into large dull pieces | **Recommended** |
| Polycarbonate | about 6.5 kg | slightly lower, can yellow | Scratches more | Cold-bends much tighter | Nearly unbreakable | Good for legs or brackets, not the face |
| Glass (tempered or laminated) | **about 13.5 kg** (2.5 g/cm³) | Very clear; low-iron is best | Hard | Must be factory hot-bent *before* tempering; cannot be cut afterwards | Tempered shatters into small pieces; laminated holds together | Curved glass about $15–$85/ft² in ballpark guides, but small one-off curved panes are quoted per piece ($2.5k+) ([thepricer](https://www.thepricer.org/tempered-glass-cost/), [latestcost](https://latestcost.com/curved-glass-window-cost/)). V3 only. |

Densities are standard material constants; weights computed.

**Mounting tips** (common fabrication practice, inference where noted):
- **Legs:**
  - Two end legs with **full-height slotted clamps** that grip the sheet's short edges along their length, with
    rubber or EPDM gaskets. This matches Gil's "legs along the edges" idea.
  - Material: aluminium 2020/3030 extrusion or CNC-cut aluminium plate. A bent sheet is stiffer than a flat one (arch
    action), so two end legs can hold a 1.5 m sheet, but a slim low rail at the bottom edge stops sag and creep over
    time (acrylic creeps under constant load).
- **Holes:** slot every hole. Acrylic expands about 7x10⁻⁵ per °C, roughly 7x steel, so a 1.5 m sheet grows about
  1 mm per 10 °C. Never clamp it rigidly.
- **Display and electronics:** mount the display on its own VESA-style frame on the legs, not hanging off the
  acrylic. Hide the driver board and power supply in a leg or a foot.
- **Where to fabricate:**
  - Local plastics shops (TAP Plastics-type), online cut-to-size (e.g. Canal Plastics, Ponoko), or makerspace laser
    cutters for the LGP.
  - Thermoforming and curved glass by quote.
  - Prices for cut-to-size cast acrylic weren't verified this pass. Budget about $100–$250 for a 1.5 x 0.6 m 6 mm
    sheet (estimate).

### 0.6 The version ladder

Diagram: `marvin-surface-builds.svg` (in the outbox folder, next to this report).

**V1: proof of concept (flat, about $450–$1,100, 1–3 weekends, low difficulty)**

The question V1 answers: is a smoked transparent LCD with a back glow readable and pleasant every day?

| Item | Price |
|---|---|
| 21.5" or 32" 1080p transparent LCD showcase kit with HDMI board (Alibaba or Made-in-China, MOQ 1; vet the seller, ask for the panel's unpowered mode and its transmittance) | $300–$600 (unverified) |
| *Or* a DIY strip-down of an old monitor (risky, see §1 option B) | $0–$50 |
| Flat cast-acrylic LGP, 6 mm, laser-dotted at a makerspace, or a factory sample | $50–$150 |
| 2x 24 V high-CRI tunable-white LED strip + aluminium channels + PSU | $60–$120 |
| ESP32 + VEML7700 light sensor (WLED) | $15–$30 |
| Two legs: 2020 aluminium extrusion + 3D-printed clamps + gaskets | $40–$100 |
| Touch: 32" IR frame (USB HID) | $40–$190 |
| UPDD macOS licence (if touch on the Mac mini) | about $100–$170 (unverified) |
| **Total** | **about $450–$1,100** |

**V2: the nicer build (gently curved carrier, about $1,800–$3,500, about 1–2 months, medium difficulty)**

| Item | Price |
|---|---|
| 32" transparent LCD from a known vendor (Crystal Display Systems, Pro Display, Planar or BenQ kit) | quote; plan $800–$2,000 |
| Long cast-acrylic sheet, about 1.4–1.6 m x 0.6 m x 5–6 mm, **cold-bent** to R ≈ 2 m in the leg clamps | $150–$300 |
| Factory LGP behind the display + edge-glow outline on the long sheet | $100–$300 |
| CNC aluminium legs with slotted clamps (SendCutSend-style) | $150–$400 |
| Flat 32" PCAP foil over the display (better feel than IR) | about $1,300 |
| LEDs, ESP32, power supply, wiring, hard-coat film | $100–$200 |
| **Total** | **about $1,800–$3,500** |

**V3: the dream curve (wide, sculpted, about $5,000–$12,000+, 3–6+ months, high difficulty)**

Three routes for the display:
1. **Two or three angled transparent LCDs** tiled along an about 1.8–2 m thermoformed acrylic or factory-bent
   laminated glass arc, with a custom-cut curved LGP and a curved PCAP foil over the whole face. Three video outputs
   from the M4 mini.
2. **A transparent OLED centrepiece** (LG 30", about $7.5k new; wait for used) set into the arc, emissive and truly
   "black = see-through," with edge glow only around it.
3. **The black-glass variant:** a Corsair Xeneon Flex 45" bent to match a smoked curved acrylic face. The sharpest and
   most practical dream, but not transparent.

| Item | Price |
|---|---|
| Thermoformed acrylic arc (by quote) or bent laminated glass (per-piece quote, $2.5k+) | $800–$4,000 |
| Displays (2–3 transparent LCDs, or a transparent OLED, or a Xeneon Flex) | $1,200–$8,000 |
| Curved PCAP foil (custom) | $1,500–$3,000 (estimate) |
| Machined legs, cable management, LEDs, controls | $500–$1,500 |
| **Total** | **about $5,000–$12,000+** |

Gate V3 on MARVIN's engineering tools (CAD for the arc and brackets), per the workshop vision.

**Risks specific to this concept**
1. **Readability:** transparent LCDs are low-contrast smoked glass. V1 exists to test exactly this, so do it before
   spending V2 money.
2. **Seller quality:** Alibaba "MOQ 1" kits can be mislabelled (LCD vs OLED, transmittance). Ask for a video of the
   unit running.
3. **Haze:** a dotted LGP behind the display reduces how clear the see-through effect is. Keep the dots tight to the
   display area.
4. **Acrylic scratches and creeps:** use a hard-coat, slotted holes and a bottom rail.
5. **Unknown unpowered state** (normally black vs normally white) affects how it looks when off.
6. **macOS touch**, as in §2.

---

*The sections below are the original survey: the alternatives and comparisons to Gil's concept (transparent OLED,
Pepper's ghost, projection film, black-glass OLED) and the shared touch, ergonomics and software findings.*

## 1. Alternatives: other transparent display options

### Sharpness, the number that matters for desktop text

| Panel | Resolution | Diagonal | PPI | Pixel pitch | Distance where 1 pixel = 1 arcminute |
|---|---|---|---|---|---|
| LG 30EW5TP-A (transparent OLED) | 1366x768 | 30" | **52** | 0.49 mm | about 1.7 m |
| LG 55EW5 family (transparent OLED) | 1920x1080 | 55" | **40** | 0.63 mm | about 2.2 m |
| LG Signature OLED T (transparent TV) | 3840x2160 | 77" | **57** | 0.44 mm | about 1.5 m |
| Typical 32" 4K OLED monitor | 3840x2160 | 32" | **138** | 0.18 mm | about 0.6 m |
| 27" 5K (Apple Studio Display) | 5120x2880 | 27" | **218** | 0.12 mm | about 0.4 m |

*Computed from the resolutions and diagonals on the spec sheets below. 1 arcminute is the usual threshold for 20/20
acuity. At a normal 60–70 cm desk distance, the transparent panels' pixels are 2–3x past that threshold.*
**Confidence: Established** (arithmetic on Tier 2 specs).

**What that means in practice (inference):** on the 30" LG at a desk, UI text needs to be roughly 20 px or bigger,
and you would fit about as much content as on a 2008-era laptop. It is fine for big glanceable HUD panels, clocks,
the brief's five items or a status ring. It is not fine for code, long documents or dense dashboards.

### Option A: Transparent OLED (the real thing)

| | LG 30EW5TP-A (30") | LG 55EW5 family (55") | LG Signature OLED T (77") |
|---|---|---|---|
| Resolution | 1366x768 | 1920x1080 | 3840x2160 |
| Transparency | 37% (set) | 33–43% depending on variant (38% figure is LG 2018 haze-meter test) | Switchable: transparent or opaque, using a roll-down contrast screen |
| Brightness | 200 nits full-screen / 600 nits at 25% APL (measured without glass) | about 150–200 / 400–600 nits | TV-class |
| Contrast | 200,000:1 (spec) | similar | n/a |
| Touch | Built in: P-Cap, 10 points, 2 mm accuracy, under 100 ms response | Touch variants (TK/TF) mostly discontinued | none |
| Inputs | HDMI, DisplayPort, USB touch | HDMI, DP | wireless box |
| Power | 45 W typical, 86 W max | n/a | n/a |
| Lifetime | "Up to 30,000 hours" | similar | similar |
| Price (Oct 2026) | **$7,500 on LG's store, out of stock**; $10,000–$13,333 MSRP at SHI, Exertis and Almo; a Latvian listing shows €2,772 ex-VAT in one place and €7,237 in another (likely stale or an error) | $16,250–$21,667 new (Full Compass, Avendor, Touchboards) | **$59,999.99** (LG US) |
| Where | AV distributors (SHI, B&H, Almo, Midwich UK); the LG page needs a MyLG Business account for its price | AV distributors | LG and big-box retail |

Sources: [LG 30EW5TP-A spec page](https://solutions.lg.com/us/digital-signage/lg-30ew5tp-a) (Tier 2; note the
page's listed dimensions, 98.8 x 44.2 in and 90 kg, are clearly a data error for a 30" panel and shouldn't be
trusted); [SHI listing](https://www.shi.com/Product/47674105); [Exertis/Almo](https://www.exertisalmo.com/productdetails/LGPRO/30EW5TP-A);
[Dateks.lv](https://www.dateks.lv/en/cenas/lielformata-displeji/1134892-lg-30ew5tp-a);
[Full Compass 55EW5P-M](https://www.fullcompass.com/prod/638659-lg-electronics-55ew5p-m-55-transparent-oled-commercial-display);
[Touchboards 55EW5TK-A](https://www.touchboards.com/LG-55EW5TKA); [LG 55EW5TK-A discontinued](https://solutions.lg.com/us/digital-signage/lg-55ew5tk-a);
[Adorama 55EW5TF-A](https://www.adorama.com/loc55ew5tfa.html); [OLED T price (zmescience)](https://zmescience.com/future/lgs-60000-transparent-tv-is-so-luxe-its-practically-invisible),
[manofmany (AUD)](https://manofmany.com/tech/appliances-tvs/lg-transparent-tv-price).

**Other makers of the same LG Display panel:**
- **LITEMAX TLD3000-L** (30", 1366x768, 43% transparency, 200 typical / 600 peak nits, HDMI and DP; built from an
  OLED panel, an AD control board and a chassis): [LITEMAX](https://www.litemax.com/product-detail/3000-L-transparentOLED-industrial-display/). No public price.
- **CEOLED** (Shenzhen) sells a 30" monitor on the same LG panel. "Contact for price," described as "not cheap":
  [OLED-info](https://oled-info.com/ceoled-launches-30-transparent-oled-monitor-based-lgds-t-oleds),
  [Sixteen:Nine](https://www.sixteen-nine.net/2025/04/21/shenzhens-ceoled-display-makes-pitch-for-a-55-inch-transparent-oled-kiosk/).
- **Xiaomi Mi TV LUX Transparent Edition** (55", 2020, about $7,200, China only, sold out at launch), now only a
  possible grey-market find: [Onliner](https://tech.onliner.by/2020/08/12/xiaomi-momentalno-rasprodala-prozrachnye-televizory-po-7200).

**Driving it:** easy. The LG and LITEMAX units are complete monitors with HDMI and DisplayPort in, so you plug a Mac
into them. A bare panel would need its matching timing controller board. LITEMAX's own docs show it is a custom AD
board, not a generic scaler kit, so don't plan on buying a bare panel. **Confidence: Likely** (spec sheets; no
hands-on report found).

**Burn-in:** LG's "30,000 hours" figure comes from its consumer TV claim (8 hours a day with pixel refresh).
Independent RTINGS long-run tests found permanent retention much sooner wherever static elements stayed on screen.
LG's monitor burn-in warranty excludes signage use. A desktop shell with a fixed status bar is the worst case.
Mitigations: pixel-shift the HUD, avoid fixed chrome, use dark idle states.
[Sixteen:Nine](https://www.sixteen-nine.net/?p=17639), [RTINGS](https://rtings.com/tv/learn/oled-burn-in-not-improved-as-expected).
**Confidence: Likely** that burn-in is a real risk for a desktop shell. The size of the risk on LG's transparent
panels specifically is **Unknown**, since the tests were on TVs.

**Contrast in a normal room:** only 37–43% of light passes through, and anything bright behind the panel adds
directly to the "black" level. Bright light behind the glass washes out the image. LG's own consumer answer (OLED T)
was a roll-down black screen behind the panel, which is a strong hint (inference). In practice, sit the panel against
a dark wall, or put a dark switchable film behind it (see §3).

**Availability, verdict:** single units can be bought through AV distributors (B&H, SHI). Prices are commercial
signage prices. **Not cheap, not sharp, but genuinely transparent and touch-enabled out of the box.**

### Option B: Transparent LCD with a backlight box

- **How it works:** an LCD panel with its backlight removed, sitting in front of a bright, lit box ("showcase").
  Transparency comes from light passing through the box, so the box must be lit.
- **The problem for this look:** in an LCD, black pixels block light and white pixels pass it. "Luminous lines on
  black" renders as **an opaque black field with clear lines**, the inverse of a hologram. Only white or light UI
  backgrounds look see-through. **Confidence: Likely** (inference from how LCDs work, consistent with DIY reports
  that transparency needs at least "50% more light in the box": [warped3](https://warped3.substack.com/p/transparent-lcd)).
- **Sharpness:** better than transparent OLED. 1080p kits exist at 21.5" (about 102 PPI). Samsung's LTI220MT02 is
  discontinued and third-party replacement kits exist: [eeNews](https://www.eenewseurope.com/en/grab-a-full-hd-1920x1080-transparent-display-kit/).
- **Price:** Alibaba "32-inch 1080p transparent LCD showcase" listings show $499–$5,805 with MOQ 1. The range is too
  wide to treat as a real price: [Alibaba](https://electronics.alibaba.com/product/tlcd). DIY from a dead monitor
  costs about $10–$50 but is fragile; the flex cable is the usual failure point:
  [Blair Neal survey](https://blair-neal.gitbook.io/survey-of-alternative-displays/appendix/diy-transparent-screens),
  [Hackaday](https://hackaday.com/tag/lcd-monitor), [TechRadar](https://www.techradar.com/pro/someone-turned-a-dollar10-discarded-monitor-into-a-transparent-lcd-screen-great-for-geeks-but-it-is-definitely-not-going-to-run-windows).
- **Verdict:** wrong for an OLED-style "black = invisible" hologram, but **right for Gil's concept** (§0): glowing lines on a smoked panel, lit by an edge-lit acrylic glow. See §0 for the build.

### Option C: Pepper's ghost / beam-splitter glass

- **How it works:** a normal monitor lies flat (or is angled) and its image reflects off a partly mirrored glass
  plate at about 45°. The reflection appears to float behind the glass. It is **additive**, so black is invisible:
  exactly the holographic look.
- **Sharpness:** **as sharp as the source monitor** (a 4K panel gives 4K). This is the big advantage over every
  "real" transparent display. **Confidence: Likely** (optics; maker builds below).
- **Brightness:** the glass reflects only part of the light. A 70/30 (70% reflect) beam-splitter gives a bright ghost
  but dims the view through it. Plain glass reflects only about 4–8% and needs a very bright source. Specialist
  "stereoscopic" beam-splitter glass from Two-Way Mirrors comes in sizes up to 49" x 70", with a 6"x6" sample at
  $14.95. Larger sizes need a quote: [twowaymirrors.com](https://www.twowaymirrors.com/?p=608794).
- **Gotchas:**
  - The reflection is mirror-flipped on one axis. macOS can rotate displays but not mirror them, so the MARVIN shell
    must render flipped. That is easy, since it is our own app.
  - **You can't touch the image.** It floats behind the glass, so a touch layer on the glass has depth parallax. This
    is fine for a show-only "hologram mode," but bad as the main touch surface.
  - It takes desk depth, and it needs a dark area behind it to look good.
- **Builds:** VEEB's Transparent Floating Display (Raspberry Pi with a round LCD under an about 45–60° reflector,
  plus a privacy shield) and Xandar Chin's OpenGhost cube:
  [Raspberry Pi Magazine, Cubism](https://magazine.raspberrypi.com/articles/cubism-holographic-display),
  [Yanko Design, Pepper's-ghost PC](https://www.yankodesign.com/?p=536590).
- **Price:** about $300–$600 (an old monitor Gil already has, plus a cut beam-splitter about 24x32", plus a frame).
  The glass price is an estimate, since a quote is needed.
- **Verdict: the cheapest true-hologram look, and very sharp, but show-only.**

### Option D: Holographic rear-projection film on glass

- **How it works:** a semi-clear diffusing film on a sheet of glass, lit from behind by a short-throw projector.
- **Specs:** clear films claim 82–88% transmittance (Pro Display Clearview: 82%), while dark-grey films are about 35%
  but give much better contrast. Prices run about $12–$70 per square meter from Chinese suppliers. eBay pieces
  measuring 152 x 50 cm cost about $55:
  [Pro Display](https://prodisplay.com/projection-screens/front-projection/clearvision-holographic-display/),
  [eBay listing](https://www.ebay.de/itm/325660418582), [Alibaba](https://electronics.alibaba.com/product/back-projection-foil).
  3M Vikuiti, the old reference film, is discontinued.
- **Sharpness:** limited by the projector (1080p or 4K) and by the film's haze. It is softer than a monitor, and the
  image has a visible hotspot. Contrast in a lit room is poor.
- **Touch:** good. The image sits on the glass plane, so a PCAP foil or IR frame on the same glass has no parallax.
- **Price:** film $50–$150, plus a short-throw projector (about $500–$1,500, not verified this pass), plus glass and
  a frame.
- **Verdict: the cheapest large, touchable, see-through display.** Text quality is poor and it needs a dim room. It
  is a good "war-table" demo, but a bad monitor.

### Summary of options

| | Transparent OLED | Transparent LCD | Pepper's ghost | Projection film | *Black-glass OLED (not transparent)* |
|---|---|---|---|---|---|
| Hologram look (black = see-through) | Yes | **Inverted: glowing lines on smoked glass (Gil's concept, §0)** | Yes | Yes | Looks like it in a dim room |
| Sharp desktop text | No (40–57 PPI) | Medium | **Yes** | No | **Yes (138 PPI)** |
| Touchable at the image | Yes | Yes | **No** | Yes | Yes |
| Lit-room contrast | Fair | Fair | Poor–fair | Poor | **Excellent** |
| Price for about 30" | $7.5k–$13k | about $0.5k–$5k (unclear) | about $0.3k–$0.6k | about $0.7k–$1.7k | **about $1.1k–$1.7k** |

---

## 2. Touch on glass

| Tech | How | Accuracy and feel | Multitouch | Through glass | 32" price | OS support |
|---|---|---|---|---|---|---|
| **IR touch frame** | LED/photodiode grid in a bezel just above the surface | Fair. Fires just *before* contact (hover false touches); bugs and sleeves trigger it; no real palm rejection | 10–40 points | Sits on top of any glass, raised edge about 5–10 mm | **$35–$39** (Alibaba), **$189** (Newegg, "USB HID driver-free, Mac via HID") | USB HID digitizer; works on Linux; one point on macOS without a driver |
| **PCAP foil** (behind glass) | Wire-grid film stuck to the back of the glass | Good. Real contact, typical 1–2 mm | Multi-touch formats | Up to 12 mm multitouch / 20 mm single (Pro Display) | **$1,299.62** (Two Way Mirrors 32") | USB HID |
| **Laminated PCAP glass** | Sensor bonded to cover glass (what the LG 30" has built in) | Best. LG lists 2 mm accuracy, under 100 ms, 8 mm minimum object | 10 points | n/a | Bundled with display, or custom | USB HID |

Sources: [Newegg IR overlay](https://www.newegg.com/global/om-en/31-5-no-limited-ir-touch/p/33X-0034-00006);
[Alibaba IR frames](https://electronics.alibaba.com/product/ir-touch-screen-frame-overlay);
[Pro Display IR datasheet](https://prodisplay.com/wp-content/uploads/2022/05/Infrared-Touch-Overlay-Datasheet.pdf);
[Two Way Mirrors PCAP foil](https://www.twowaymirrors.com/pcap-foil/);
[Pro Display PCAP foil](https://prodisplay.com/touch-screens/interactive-overlays/pcap-touch-foil/);
[LG 30EW5TP-A spec](https://solutions.lg.com/us/digital-signage/lg-30ew5tp-a). OS claims on the listings come from
sellers. **Confidence: Likely** for prices; **Plausible** for the "driver-free on Mac" claims.

**Latency and palm rejection** (inference from how the technologies work, no bench data found): PCAP rejects palms
better because it measures contact area. IR frames see any object that breaks the beams. Consumer-grade latency for
both is around 10–30 ms on the bus, while LG's own spec allows up to 100 ms. Plan for an IR frame to feel
"kiosk-grade," not iPad-grade.

### macOS vs Linux touch support

- **macOS:** no native touchscreen model. An HID touchscreen is usually driven as a **single absolute pointer**
  (tap = click, drag = drag). Apple developer-forum threads show macOS ignoring the multitouch HID interface entirely
  on some devices and using only the single-touch one:
  [Apple Dev Forums #829408](https://developer.apple.com/forums/thread/829408),
  [#768586](https://developer.apple.com/forums/thread/768586).
  - **UPDD V7 (Touch-Base)** is the standard fix. It supports macOS on Intel and Apple Silicon from 10.14, offers
    "full multi-touch gesture support" that mimics a trackpad, and has an API plus **TUIO** output that hands raw
    touches to apps: [touch-base.com](https://touch-base.com/),
    [support page](https://support.touch-base.com/Print50324.aspx).
  - **Price:** not published this pass (purchase portal only). Old figures (2015: about $171 commercial) and
    third-party estimates ($100–$150) are not current.
  - **Alogic** (June 2026) ships Mac-compatible touch monitors with its own gesture software, including the Aspekt
    Touch 27" from $1,799: [MacRumors](https://www.macrumors.com/2026/06/19/alogic-touchscreen-monitors-portable-displays/).
    Reviewers call macOS "touch-compatible, not touch-optimized"; Macworld reviewed the
    [32" model](https://macworld.com/article/3155467/alogic-aspekt-4k-touch-review.html).
  - **Confidence: Likely.** Several consistent sources, but no 2026 bench test of UPDD on macOS 26.
- **Linux:** the kernel `hid-multitouch` driver plus libinput deliver real multitouch to the compositor and to apps,
  and Chromium/Electron get W3C Touch and Pointer Events. GNOME on Wayland has built-in multi-finger gestures, though
  they are mostly documented for touchpads. KDE KWin's gestures are hard-coded:
  [itsfoss](https://itsfoss.com/three-finger-swipe-gnome/), [KDE wiki](https://community.kde.org/KDE_Visual_Design_Group/Gestures).
  **Confidence: Likely.** Linux handles touch better, especially when MARVIN's own shell owns the gestures. Kiosk
  setups have real rough edges, such as touchscreen-to-display mapping on multi-monitor setups
  ([Cage wiki](https://github.com/cage-kiosk/cage/wiki)).

---

## 3. Can it be an everyday monitor?

**Legibility on see-through displays (Tier 1):**
- **Scharff & Ahumada (2002, *Journal of Vision*):** how readable transparent text is depends on a masking index:
  text contrast against how busy the background is. It predicted search times with r = 0.89–0.91. A busy background
  behind the glass directly costs reading speed:
  [laurenscharff.com](https://laurenscharff.com/research/transtext.html).
- **Fiorentino et al. (2013, *Presence*, n=14, 2,520 trials, see-through AR):** maximum contrast is best when reading
  speed matters, and a solid "billboard" behind text helps.
- **TU Delft study (n=25):** drop shadows and billboards improve legibility over complex backgrounds:
  [TU Delft repository](https://repository.tudelft.nl/file/File_15420783-93bb-4277-8305-e4f285d0ea27).
- **Confidence: Likely.** These are AR and HUD studies, not desktop panels, but the mechanism carries over.

**What follows for MARVIN OS design (inference):**
- Text panels get a **dark translucent backing plate** (a "billboard"): see-through *around* the content, solid
  *behind* the text.
- The fully transparent look is for chrome, rings, graphs and the brief headline, not for paragraphs.

**Opaque mode behind the panel:**
- Standard **PDLC smart film switches between clear and milky white**, with over 94% haze when off. White haze behind
  a transparent OLED *raises* the black level, the wrong direction.
- **Dye-doped "black" PDLC** exists. Vendors claim near-total blocking, but a government guide says the dark state
  can still pass 2–65% depending on the dye:
  [Smart Glass Country press](https://norfolkdailynews.com/online_features/press_releases/the-dark-side-of-smart-glass-smart-glass-country-introduces-dyed-pdlc-for-architectural-privacy/article_b6e1061b-96d9-55db-8131-ed95ce27af06.html),
  [Alberta TEC guide](https://www.alberta.ca/system/files/tec-dtseries21pdlcglass.pdf).
- Price: about $29–$80 per square foot for adhesive PDLC, so about $150–$400 for a 30" panel area, plus a power
  supply: [thepricer](https://www.thepricer.org/how-much-does-smart-tint-cost/).
- A motorized black roller blind (what LG did on OLED T) is cheaper and darker. **Confidence: Plausible.**

**Ergonomics (Tier 1):**
- **Gorilla arm is real and measurable.** Consumed Endurance (Hincapié-Ramos et al., CHI 2014,
  [doi:10.1145/2556288.2557130](https://doi.org/10.1145/2556288.2557130)) and its 2024 successor NICER
  ([arXiv 2406.08875](https://arxiv.org/abs/2406.08875v1)) model arm fatigue from how long the arm is held up.
  Sustained raised-arm use tires the shoulder quickly.
- **Desktop touch raises neck and shoulder muscle load compared with keyboard and mouse.** Given the choice, users
  pulled the screen **closer, lower and more tilted** when touching it:
  [UNIST study](https://scholarworks.unist.ac.kr/handle/201301/46811).
- **An upright, monitor-like screen is the worst angle for touch.** In one study, 75° from horizontal was the least
  preferred and the most tiring: [Schultz & Batten 1998](https://davidbatten.yolasite.com/resources/Website_Documents/schultzBatten1998.pdf).
  Steeper tablet tilt reduces neck flexion: [PubMed 26967038](https://pubmed.ncbi.nlm.nih.gov/26967038/).
- **Confidence: Likely.**

**Verdict, what makes it practical daily:**
1. **Hybrid, not touch-only.** Keyboard and trackpad for text and work; touch for big targets (approve, dismiss, open
   item 3, swipe between rooms). Touch is for a few seconds at a time, not hours.
2. **Low and tilted** (drafting-table angle, about 20–45° from horizontal) if touch is primary, or upright with touch
   as occasional.
3. **Sharp main display for text.** A transparent panel can be the *secondary* or ambient Surface; it cannot be the
   only screen.
4. **A dark background behind any see-through panel** (wall, blind or black PDLC).
5. **Billboarded text, large type, and no fixed chrome** (to limit burn-in).

---

## 4. Driving it

**M4 Mac mini:**
- **Video:** yes. Any of these displays takes HDMI or DisplayPort, which the Mac mini outputs over HDMI and
  Thunderbolt/USB-C. **Confidence: Established.**
- **Touch:** single-point out of the box. Gestures need UPDD or vendor software. For the MARVIN shell, the better path
  is **UPDD → TUIO → a small local bridge → the shell**, so the shell gets raw multi-finger touches itself instead of
  relying on macOS gestures. **Confidence: Plausible** (UPDD documents TUIO output; we haven't tested the
  bridge).

**Linux (Kali box, or a 2012 Mac Pro):**
- **Better for touch.** Native multitouch reaches Chromium through Touch and Pointer Events.
- **Mac Pro 2012 towers:** they can run Linux and drive a display, but their GPUs are old, their idle power draw is
  high (not measured here), and they add nothing the Mini can't do. Treat them as optional Linux hosts, not a
  requirement. **Confidence: Plausible.**

**What a MARVIN OS shell could be:**

| Approach | Host | Notes |
|---|---|---|
| **Fullscreen Electron or web app over macOS** | Mac mini | Fastest path. Reuses the dashboard's web stack. Touch arrives as mouse events unless UPDD/TUIO is bridged in. macOS menu bar and Dock need hiding (kiosk mode). |
| **Chromium kiosk under a Wayland kiosk compositor (Cage)** | Linux | One fullscreen app with touch support. Cage 0.2 (2024) is on wlroots 0.18: [Cage wiki](https://github.com/cage-kiosk/cage/wiki), [Phoronix](https://phoronix.com/news/Cage-0.2-Released). Touch-mapping can be fiddly. |
| **Quickshell (QML) desktop shell** | Linux | Toolkit for writing your own bars, widgets and overlays on Wayland (Hyprland, Sway): [quickshell.org](https://quickshell.org/about). Good for a "native" sci-fi shell later. |
| **Übersicht** | macOS | HTML widgets on the macOS desktop: [maketecheasier](https://maketecheasier.com/customize-mac-desktop-ubersicht/). A lightweight HUD over a normal desktop. |
| **eDEX-UI** | Electron (any OS) | The famous sci-fi terminal/dashboard. Archived since Oct 2021 (GPL-3.0); a useful visual reference and code to borrow, not a base to build on: [AlternativeTo](https://alternativeto.net/software/edex-ui). |

**Recommendation (inference):** build the shell as a **web app with an input abstraction layer** (Pointer Events
plus an optional TUIO-over-WebSocket source). Then:
- On macOS it runs in Electron with UPDD feeding TUIO.
- On Linux it runs in a Chromium kiosk with native touch.
- It is the same code as the existing MARVIN dashboard tech, and it can show the same **Content** (the brief, a
  ticket, a chart) the Endpoints model already defines.

---

## 5. Build recipes and lessons

- **Transparent LCD from a dead monitor** (Hackaday, the Blair Neal survey, warped3, TechRadar): costs about $10.
  Lessons: the flex cable is fragile; some panels have a diffusion film that blurs the background; it needs at least
  50% more light behind it; color is poor; old CCFL backlights contain mercury.
- **Pepper's ghost floating display** (VEEB, OpenGhost): Pi plus a round LCD plus a 45–60° reflector and a privacy
  shield. "A lot of tinkering and mathematics" to get the angles right.
- **Commercial "monitor builds" on LG's 30" transparent OLED** (CEOLED, LITEMAX): they confirm the panel needs its
  vendor controller board. **I found no hobbyist write-up of a desktop transparent-OLED monitor**, which is itself a
  signal about cost and availability (inference).
- **Lesson across all of them (inference):** the look sells in photos and demos, which are dark, staged and short.
  None of the builds found claims daily-driver use.

---

## 6. Alternative path: the black-glass OLED Surface, and software first

### Phased path

| Phase | What | Rough cost | Why |
|---|---|---|---|
| **0. Software first (now)** | MARVIN OS shell as a fullscreen web app: black-first theme, billboarded text, input abstraction (Pointer + TUIO), **transparency simulator** (blend a photo or live camera image of the desk behind the UI at 37–45%, and dim blacks to simulate ambient light), pixel-shift anti-burn-in, mirror-render flag for Pepper's ghost | $0 | Proves the look and legibility on any monitor before hardware arrives; reuses dashboard code |
| **1. Black-glass Surface (main)** | 32" 4K OLED monitor ($600–$1,000 street, 2026 listings) + front glass or acrylic sheet ($50–$150) + PCAP foil ($1,300) **or** IR frame ($40–$190) + UPDD licence (about $100–$170, unverified) + low tilted mount ($100–$200) | **about $900–$1,700** (IR) / **about $2,100–$2,800** (PCAP foil) | Sharp, daily-usable, touch on macOS, holographic look on a black theme |
| **2. Hologram mode** | Pepper's-ghost rig: a spare monitor face-up + custom beam-splitter glass (quote needed) + frame | about $300–$600 | Real floating effect for the brief, status and ambient displays; show-only |
| **3. True transparent OLED** | LG 30EW5TP-A or LITEMAX TLD3000-L, used or refurbished, plus a black blind or dyed PDLC | target **under $3,000 used**; new $7,500–$13,333 | Buy when the price drops; use as a secondary ambient Surface with built-in touch |
| **(alt) Linux host** | Run the same shell in a Chromium kiosk on the Kali box or a Mac Pro if macOS touch disappoints | $0–$200 | Native multitouch |

### Bill of materials for Phase 1 (recommended starting build, IR variant)

| Item | Price | Source/confidence |
|---|---|---|
| 32" 4K QD-OLED monitor (e.g. MSI MAG 321UPXB, Gigabyte MO32U, Alienware AW3225QF) | $600–$1,000 | 2026 deal listings: [Slickdeals](https://slickdeals.net/f/19839090-32-msi-mag-4k-uhd-qd-oled-g-sync-240hz-gaming-monitor-600-free-s-h), [WePC](https://www.wepc.com/news/amazon-deal-cuts-180-off-this-32-inch-4k-qd-oled-gaming-monitor/), [TechRadar](https://www.techradar.com/gaming/the-alienware-aw3225qf-4k-qd-oled-gaming-monitor-has-crashed-to-its-lowest-ever-price-at-best-buy-just-in-time-for-the-ps5-pro); check the current price |
| 32" 10-point IR overlay, USB HID | $40–$190 | Newegg, Alibaba; seller claims |
| Cut glass or low-iron acrylic front (about 3–4 mm), edge-lit optional | $50–$150 | local glass shop (estimate) |
| UPDD V7 macOS licence | about $100–$170 | price not published; estimate |
| Low, tilting mount or drafting-arm VESA stand | $100–$200 | estimate |
| **Total** | **about $900–$1,700** | |

### Risks

1. **macOS touch quality.** UPDD is the only mature path, and its price and macOS 26 behaviour weren't verified.
   *Mitigation:* the shell owns gestures through TUIO; Linux is the fallback host.
2. **Transparent OLED price and supply.** The 30" is out of stock at LG, and several 55" touch variants are
   discontinued. The category may stay signage-only.
3. **Burn-in** on any OLED (black-glass or transparent) with a static HUD. *Mitigation:* pixel shift, no fixed chrome,
   dark idle states.
4. **Legibility on see-through panels** drops with a busy background (Scharff and Ahumada). *Mitigation:*
   billboards, dark backdrop, large type.
5. **Arm and neck fatigue** if touch becomes the main input. *Mitigation:* hybrid input, low tilted mount.
6. **Scope creep against current priorities.** Per the workshop-vision memory, the Surface is a future physical
   build. Phase 0 is software that composes with the Endpoints/Content work and is the only part worth doing before
   Seal Speak ships.

### What to prototype first in software

1. **Shell skeleton:** fullscreen web app, a black canvas, and luminous-line components (rings, brackets, scan
   lines), with the five-item brief as the first Content.
2. **Transparency simulator:** a background-image layer at 37% (LG spec) and 43% (LITEMAX), plus an "ambient light"
   slider that lifts blacks. Use it to judge billboard designs.
3. **Input layer:** Pointer Events first, then a TUIO-over-WebSocket adapter (test with a TUIO simulator). Gestures:
   tap, long-press, two-finger pan, pinch.
4. **Display profiles:** `black-glass` (138 PPI), `toled-30` (52 PPI: render at 1366x768 and scale up, to *feel* the
   real sharpness), `ghost` (mirrored).
5. **Burn-in guard:** a slow pixel-orbit of the whole HUD and a dim-on-idle mode.

---

## What would change these conclusions

- A verified **used 30" transparent OLED under $2,500**: moves Phase 3 earlier.
- A **higher-PPI transparent OLED** (for example a 1080p or 4K 30") reaching the market: the "secondary only" verdict
  would need rechecking.
- **Apple shipping touch on macOS** (rumoured, not confirmed): the Linux fallback matters less.
- **UPDD failing on macOS 26** with the chosen frame: Linux host becomes Phase 1.
- **V1 shows smoked transparent LCD text is tiring to read:** switch the headline build to the black-glass OLED
  (§6) and keep the edge-lit acrylic as a frame and glow element.

## Gaps in this pass

- **Marketplace prices (AliExpress, eBay sold listings):** pages blocked or returned no data. No street price for
  bare transparent OLED panels was found.
- **UPDD:** current licence price not published.
- **Projectors:** short-throw projector prices not verified.
- **Transparent OLED text quality:** no independent hands-on review of text on LG's 30" panel.
- **Transparent LCD kits:** prices ($499–$600, MOQ 1) are unverified trade listings. Vendor quotes (Crystal Display
  Systems, Pro Display, Planar, BenQ) weren't requested. Each panel's unpowered state (normally black vs white) is
  unknown.
- **Fabrication:** curved PCAP foil bend limits, one-off cut-acrylic prices and thermoforming quotes weren't
  verified.
- **Semantic Scholar:** the academic search script returned 429 (rate-limited), so Tier 1 citations came from
  OpenAlex/arXiv and direct sources.
