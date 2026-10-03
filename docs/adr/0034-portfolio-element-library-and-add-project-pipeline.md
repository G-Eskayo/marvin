# 0034. Portfolio: a captured element library and an add-project pipeline

Date: 2026-10-03. Status: accepted (design); implementation not started.

## Context

The portfolio site's inconsistencies came from hand-built pages. Over 2026-10-02 we built a Templates tab,
generators, a layout evaluator and an image generator, but defined the project card from our own template file and
style numbers, and the dashboard re-rendered that file in a simulated page. Gil's approved design is the dev
site itself. Creating a new project page was also never automated: the generators update existing pages only, and
the old New-project form was removed without a replacement.

## Decision

1. The dev site is the master for how an element looks. The **element library** is built once by capturing each
   element from the live dev site and generalizing it; the dashboard shows that element as it renders on the site.
2. Every placement of an element references the one definition (the card already does: one file, three fillers).
3. **Site rules** become one machine-readable file used by both the pipeline and the evaluator, which compares
   instances to the element, not to fixed numbers.
4. An **add-project pipeline** turns a project spec into a dev-site change (create page, append manifest, image,
   regenerate hubs and sidebars, evaluate, report). LLM work is limited to the spec's wording and theme choice.
5. Dev is the pre-production build-and-break copy; production promotion stays a manual act.

## Consequences

- The Templates tab can no longer drift from the site by construction; a parity check proves it.
- A new project becomes data in, finished dev page out, which is the plug-and-play goal.
- Cost: a capture step per element once, and ownership of the page-creation step the generators lacked.
