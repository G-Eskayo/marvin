# UI Prototype

Goal: answer "what should this look like?" by putting several radically different visual
directions in front of the user on one route, not by polishing a single guess.

## Shape

One route in the project's existing routing convention (don't invent a new top-level structure),
rendering N variations that are genuinely different from each other — different layout
philosophies, not just color/spacing tweaks on the same structure. If all N variants look like
minor iterations of one idea, that's not exploring the design space, that's polishing a single
guess N times.

**Switching mechanism**: a URL search param (e.g. `?variant=2`) selects which one renders, plus a
floating bottom bar (fixed position, always visible regardless of scroll) with a button per
variant so the user can flip between them without touching the URL bar. Keep the bar itself
minimal — it's scaffolding for comparison, not part of any variant being judged.

```jsx
function PrototypeRoute() {
  const [variant, setVariant] = useSearchParamState("variant", "1");
  const variants = { 1: <VariantCardGrid />, 2: <VariantSidebarList />, 3: <VariantTimeline /> };

  return (
    <>
      {variants[variant]}
      <div className="fixed bottom-4 left-1/2 -translate-x-1/2 flex gap-2 bg-black/80 rounded-full px-4 py-2">
        {Object.keys(variants).map(k => (
          <button key={k} onClick={() => setVariant(k)}
                  className={variant === k ? "text-white font-bold" : "text-white/50"}>
            {k}
          </button>
        ))}
      </div>
    </>
  );
}
```

## Data

Use realistic-looking fixture data, not "Lorem ipsum" or `item 1`/`item 2` — a design decision
often looks fine with placeholder text and falls apart with real-length names, long titles, or
edge-case content (empty state, very long string, unusual number). Include at least one edge case
in the fixture set on purpose.

## What NOT to build

No real data fetching, no persistence, no interactivity beyond what's needed to judge the visual
design (a button that would normally submit a form doesn't need to actually submit anything). Skip
responsive-breakpoint perfection unless the question is specifically about responsive behavior.
