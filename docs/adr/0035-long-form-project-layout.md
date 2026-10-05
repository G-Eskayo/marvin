# 0035. A second project layout for long-form pages

Date: 2026-10-05. Status: accepted.

## Context

Two project pages (Helicopter Crutches, SkineeDipping) are long write-ups with sections, diagrams and image/text rows
outside the title card. The short project page cannot hold them without losing structure or being squeezed into a narrow
card; the migration tool correctly refused them. Gil wants more projects to be like this: diagrams and detail, showing
and telling.

## Decision

Add a **long-form project page** layout: the same frame as the project page (hero, title card with a short lead, Stack line,
action row, Other Projects footer) followed by any number of **sections**, each a centred heading with free-form content
built from library parts (figure, figure row, callout). A project page conforms if it matches either layout. Migration of
a legacy long page keeps every block and standardizes only the frame; the add-project pipeline accepts `layout` and
`sections`.

## Consequences

- More projects can be long form without hand-built pages: the parts and their stylesheet are copied from the library.
- Two project layouts to keep in the library, captured and checked like the others.
- Diagram-heavy pages depend on images in the media library; the pipeline places generated images, not diagrams (those are
  authored).
