# HTML Report Scaffold

Self-contained file, no build step, no external app dependencies beyond CDN. Write to
`<tmpdir>/architecture-review-<timestamp>.html`.

## Base scaffold

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Architecture Review — [project name]</title>
<script src="https://cdn.tailwindcss.com"></script>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
</script>
</head>
<body class="bg-slate-50 text-slate-900 p-8 max-w-5xl mx-auto space-y-8">

  <header>
    <h1 class="text-3xl font-bold">Architecture Review</h1>
    <p class="text-slate-600">[project name] — [date]</p>
  </header>

  <!-- one card per candidate, repeat this block -->
  <section class="bg-white rounded-xl shadow p-6 space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold">[Candidate title]</h2>
      <span class="px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
        Strong <!-- or: Worth exploring (amber-100/amber-800), Speculative (slate-100/slate-600) -->
      </span>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
      <div><h3 class="font-semibold mb-1">Files</h3><p>[which modules]</p></div>
      <div><h3 class="font-semibold mb-1">Problem</h3><p>[why current architecture causes friction]</p></div>
      <div><h3 class="font-semibold mb-1">Solution</h3><p>[what would change]</p></div>
      <div><h3 class="font-semibold mb-1">Benefits</h3><p>[locality/leverage gains, test improvements]</p></div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <h3 class="font-semibold text-sm mb-2">Before</h3>
        <pre class="mermaid text-xs">
graph TD
  A[Caller] --> B[Shallow Module]
  B --> C[Detail 1]
  B --> D[Detail 2]
  A -.->|must know both| C
  A -.->|must know both| D
        </pre>
      </div>
      <div>
        <h3 class="font-semibold text-sm mb-2">After</h3>
        <pre class="mermaid text-xs">
graph TD
  A[Caller] --> B[Deep Module]
  B --> C[Detail 1]
  B --> D[Detail 2]
        </pre>
      </div>
    </div>
  </section>
  <!-- /card -->

  <section class="bg-indigo-50 rounded-xl p-6">
    <h2 class="text-lg font-semibold mb-2">Top recommendation</h2>
    <p>[which candidate first, and why]</p>
  </section>

</body>
</html>
```

## Diagram guidance

- **Mermaid** for anything graph-shaped: call graphs, dependency chains, sequence diagrams. It's
  faster to write and good enough for structure — don't hand-draw what Mermaid already does well.
- **Hand-built SVG/CSS** for anything more editorial: illustrating *why* a shallow module hurts
  (e.g. a caller reaching into three boxes at once with arrows crossing), a "mass" diagram
  comparing interface-size-vs-complexity as literal shape sizes, or a collapse animation showing
  several shallow pieces folding into one deep one. Mermaid can't express these well — don't force
  it.
- Keep before/after diagrams side by side, same visual scale, so the *reduction* in what a caller
  has to know is visually obvious at a glance, not something the reader has to reconstruct from
  reading two separate diagrams.
- Badge colors: `Strong` = green, `Worth exploring` = amber, `Speculative` = slate/gray. Keep this
  consistent across every card so a reader can scan badge color alone to triage.
