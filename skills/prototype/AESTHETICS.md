# Aesthetics for UI prototypes

Read this when the UI branch runs ([UI.md](UI.md)), before writing any variant. Pick the mode first.

## Mode 1: brand lock (the page belongs to an existing brand)

Use the brand's own tokens and type exactly. Variants differ in layout and structure only, never in palette, fonts
or effects. Read the source file; don't copy values from memory.

| Brand | Source of truth | The look in one line |
|---|---|---|
| Seal Speak (clarity-captions) | `site/index.html` `:root` (Peach light, Harbor dark) and the six caption themes in `site/seal-data.js` | warm paper, high contrast, caption text in OpenDyslexic or Atkinson Hyperlegible |
| MARVIN (celestial navigation, marvin#428) | `docs/design/celestial-navigation/README.md` on branch `design/celestial-navigation`; `dashboard/src/components/boot.css` | luminous lines on true black, Saira Condensed + Share Tech Mono, motion only with meaning |
| gileskayo.me | `deploy/brand/brand.css` in portfolio-website-updater (branch `portfolio/9-brand-migration`, PR #11 until it merges) | paper and ink like an engineering drawing; pink = where you are, blue = where you can go |

A brand's choices beat everything in Mode 2: Seal's system font and the portfolio's Inter Tight stay. If the brand
has no token for what you need, derive it from an existing token and say so in the prototype's notes.

## Mode 2: new design (no brand yet)

<frontend_aesthetics>
Left alone you converge on the generic, on-distribution look. Make each design feel chosen for its context.

- **Typography.** Pick one distinctive font and use it decisively; name it before coding. Pair for contrast
  (display + mono, serif + geometric sans). Use extremes: weights 200 vs 800, size jumps of 3x, not 1.5x.
- **Colour and theme.** Commit to one cohesive look, defined as CSS variables. A dominant colour with one sharp accent
  beats a timid, even palette. Borrow from IDE themes, print, signage or a cultural style that fits the subject.
- **Motion.** One orchestrated entrance (staggered `animation-delay`) beats scattered micro-interactions. CSS first.
  Honour `prefers-reduced-motion`.
- **Backgrounds.** Build atmosphere and depth instead of a flat fill: layered gradients, a fine pattern, a texture
  that matches the theme.

Avoid the defaults: Inter, Roboto, Arial, Open Sans, Lato and system fonts; purple gradients on white; the stock
hero, three-card row and centred-everything layout; anything that would fit any product equally well. Don't swap one
safe default for another (Space Grotesk is the usual one).
</frontend_aesthetics>

**Vary across variants.** Each UI variant takes a different direction: light vs dark, a different font family, a
different reference. Two variants with the same font and palette are one idea twice.

Readability still wins: body text at least 16 px, contrast at least 4.5:1, nothing that hides the content being judged.

Source: Anthropic's cookbook "Prompting for frontend aesthetics" (2025). Blind A/B (`bench/RESULTS.md` Run 32): won
7 of 9 pairs, all 6 on landing pages and dashboard cards, and lost 2 of 3 on a settings screen.
