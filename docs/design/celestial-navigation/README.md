# Celestial navigation: MARVIN's visual identity

**Status: in progress, not approved.** The icon and the boot sequence are the first pieces. The dashboard UI redo
must use this same theme when it happens, so treat these tokens as the shared source of truth and don't fork them.

## The idea

MARVIN keeps no memory inside the model. It is rebuilt each session from linked notes: memories, handoffs, the lexicon.
A constellation works the same way: separate points that only mean something once they are connected. People also used
constellations as one of the first external memories, to keep stories and to find their way home.

- **Philosophy is the core.** The design rule is elegant sufficiency (Watts / Colton). A star chart exists to get you
  somewhere, not to admire itself.
- **The look is retro.** Apollo-era mission control: phosphor green, amber hairlines, the terminal MARVIN was born in.
- **The tone is sci-fi, in the Evangelion/NERV style.** Hard-edged HUD panels, hazard stripes, target locks, a
  sync-ratio readout and a CRT power-on. It's hopeful exploration, not surveillance: no eyes, nothing watching.

Reference for the palette and HUD language: https://sentry.artificialisabel.com/

## Tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#05040A` | background |
| `--green` | `#54ff8a` | phosphor: stars, primary readouts, "ok" |
| `--amber` | `#f0b32a` | constellation lines, body text |
| `--line` | `#7a5a14` | hairline panel borders |
| `--orange` | `#ff6a1f` | locks, orbits, hazard stripes, in-progress states |
| `--red` | `#ff3b2f` | tags, warnings |
| `--dim` | `#6b551f` | secondary labels |
| `--moon` | `#cfd6e6` | background stars |

Fonts: **Saira Condensed** (600/800) for display and tags, **Share Tech Mono** for data and logs.
Recurring details: scanlines, diamond nodes on panel edges, a faint hex grid toward the edges, red-outlined tags.

## The mark

There are five stars in an M. The centre star (`core`) is MARVIN. It glows brightest and has a dashed orange orbit.
The geometry lives in one `ICON` object (1024 grid), which both `icon.html` and `boot.html` read, so changing the
icon changes the boot as well.

- App icons carry **no words or text**. That was tested on the real devices: text disappears at icon size.
- The icon must survive macOS **tinted icon mode**. Gil's MacBook uses TintedDark with a red tint, which turns every
  icon monochrome. Lines and dots hold up; glow and colour don't.
- Icons are checked on the real OS, not only in HTML. Use a stub Xcode app per variant, the iPhone simulator
  (DeviceHub), and `NSWorkspace.icon(forFile:)` on macOS.

![Icon on iPhone and Mac](icon-on-devices.png)

## The boot sequence (v4, about 5.5 s, any key or click skips it)

Minimal by request (2026-10-14). It uses the **dashboard's own background, `#0f1117`**, so the hand-off is seamless.

1. **CRT power-on:** a bright line opens into the sky.
2. **The sky.** The five M stars are already there, hidden among ordinary stars.
3. **Target lock.** An orange reticle snaps onto the origin star (MARVIN), and the origin star ignites with a dashed orbit.
4. **Lines grow out of the origin** in two branches. Each star they reach pings and turns green.
5. **Four-line log:** `LOCK origin`, `OK memories`, `SYNC mac-mini %`, `PLOT course`. Then "MARVIN · SYSTEMS ONLINE".
6. **Hold** the finished frame for 1.2 s, then **dissolve** straight into the dashboard. Same background, so nothing flashes.

Pacing is a single `K` factor (1.3) and the hold is `HOLD` (1200 ms), so both are easy to tune.
Removed in v4: the hex grid, hazard bar, boxed sync panel, top-left tag and CRT collapse. Those belong to the later dashboard redo if anywhere.

The real build reads live values. If something is actually wrong, the boot shows it (for example, a sync stall
appears as a red `SYNC` chip below 100%) and does not report "nominal".

![Boot](boot.gif)
![Boot keyframes](boot-keyframes.png)

`record.cjs` captures deterministic frames: every animation uses the Web Animations API, so it can be seeked.
Run it with `node record.cjs boot.html frames 25`.
