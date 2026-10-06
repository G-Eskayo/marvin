# README fixes proposed for the other public repos (2026-10-05)

From [readme-audit-2026-10-05.md](readme-audit-2026-10-05.md). Nothing here is applied: each repo is public, so each is Gil's call. "Free win" = something already in the repo that the README just does not use. "Needs a run" = needs a real screenshot or output that has to be produced, never invented.

## Free wins (already in the repo, not shown)

| Repo | Show this | Where |
|---|---|---|
| ML_unsupervised_learning-anomaly-detection-project | `Confusion Matrix.jpg` next to the results paragraph | README |
| full_ml_pipeline---social-media-project | `Distribution of Engagement Metrics.jpg` next to the data section | README |
| AI-algorithms | `Mancala Game Implementation/gameplay output.png` under the Mancala entry | README |
| paper-dive, killer-sudoku | link the ADR folders (`docs/adr`) from a docs map | README |
| resume-tailor | link `docs/requirements.md`, `design.md`, `architecture.md` | README |

## Per repo

- **paper-dive** (fail: no visual). Add a Mermaid diagram of the Socratic loop + citation-graph traversal (the ADRs 0007-0011 already define it); add a status line; one sentence of *why*. Needs a run: a real session transcript excerpt.
- **resume-tailor** (fail: no visual). Add a before/after: one job description in, the one-page package out (a real run, personal details redacted); status line; contents list (137 lines); no license file yet (add one, or say all rights reserved).
- **killer-sudoku** (warn). Add *why*, a status line, a "Getting started" heading over the build commands, a contents list. It already has one image; add the gameplay screenshot that is on the portfolio page.
- **AI-algorithms** (fail). Embed the Mancala output; one result image per project folder (the notebooks produce them); status line (coursework, finished); getting-started section; GitHub description is currently a paragraph: shorten to one line.
- **ML_supervised..., ML_unsupervised..., full_ml_pipeline..., ML-Powered-Resume-Selector...** (four notebook projects, same fix). Add: a one-line description (three have none); a status line (coursework, 2025, finished); the result figure at the top of the README; the headline metric as a sentence; how to run the notebook (Colab link or `jupyter` + requirements, which the repos lack). Needs a run: a figure for the supervised and resume-selector repos (the notebooks can export one).
- **ML_unsupervised...: the Kaggle link is NOT dead** (corrected same day): Kaggle answers HEAD requests and script user agents with 404 while the page is fine in a browser. The audit tool now confirms a 404 with a browser-style GET. The original text was: The Kaggle dataset URL (`agungpambudi/network-malware-detection-connection-analysis`) returns 404. Either the dataset was renamed or removed: find the new URL, or say "dataset removed; a copy is not redistributed" and keep the name. The same link is on the portfolio page: fix both together.
- **Autonomous-Marketplace-Flipper.** The audit says the README is fine on links, but the repo has `market-flipper-agent/node_modules` **committed**. Remove it from git and add a `.gitignore`; then a demo screenshot or log excerpt, a status line, and a clear statement of whether it ever buys for real (it "automatically buys and re-lists"). Needs a run.
- **CS-GO_Skins-PriceTracker.** Hero image (free win), description (none), getting-started (`npm install`/`start` from `All_Project_Code/src`), status line. Needs a run: one screenshot of the tracker with data.

## Order

1. Free wins + status lines + descriptions + the dead link (no new content, all verifiable from the repos): about one sitting.
2. The `node_modules` cleanup (a history-visible commit; worth doing on its own).
3. The "needs a run" visuals, repo by repo, when each project is next opened.

## Corrections found while applying these (2026-10-05)

- `CS2thumbnail.png` is Valve's Counter-Strike 2 key art, not a screenshot of the tracker: not used as a hero image.
- **Secrets in a public repo:** `CS-GO_Skins-PriceTracker/All_Project_Code/.env` is committed (Postgres credentials, a session secret, an API key). Rotate the API key and the secret, then remove the file from the repository (and ideally its history).
- Several READMEs described things the notebooks do not do (a Decision Tree that is a Random Forest; a classification task with empty cells; a Random Forest that "beat" Linear Regression when it did not; clone URLs with `yourusername`; `requirements.txt` that does not exist). The applied diffs state what the notebooks actually show.
- The Marketplace Flipper README implied real buying and selling; the project's own submission notes say the marketplace data is simulated.
