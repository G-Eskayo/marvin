# README audit, 2026-10-05

First run of the `readme` skill's audit (`lib/readme_audit.py`) over the 12 public repositories. Criteria: [readme-criteria.md](readme-criteria.md). Scores are the share of that goal's checks that pass (warn counts half); `n/a` means no check applied. The audit is mechanical: it finds broken links, missing paths, stale READMEs and missing visuals, and does not judge quality.

| Repository | Fail | Warn | ORIENT | PROVE | START | NAVIGATE | TRUST | SCOPE | Lines | Visuals |
|---|---|---|---|---|---|---|---|---|---|---|
| marvin | 0 | 3 | 83% | 100% | 100% | 100% | 88% | 75% | 495 | 2 |
| clarity-captions | 1 | 3 | 100% | 62% | 75% | 100% | 90% | 100% | 29 | 0 |
| killer-sudoku | 0 | 4 | 83% | 100% | 75% | 100% | 90% | 75% | 115 | 1 |
| paper-dive | 1 | 2 | 83% | 75% | 100% | 100% | 90% | 100% | 34 | 0 |
| resume-tailor | 1 | 3 | 83% | 75% | 100% | 100% | 90% | 75% | 137 | 0 |
| AI-algorithms | 1 | 4 | 83% | 62% | 75% | 100% | 90% | 100% | 28 | 0 |
| ML_supervised_learning-Regression-Classification-project | 1 | 4 | 83% | 62% | 100% | 100% | 80% | 100% | 91 | 0 |
| ML_unsupervised_learning-anomaly-detection-project | 2 | 4 | 83% | 62% | 100% | 67% | 80% | 100% | 81 | 0 |
| full_ml_pipeline---social-media-project | 1 | 4 | 83% | 62% | 100% | 100% | 80% | 100% | 83 | 0 |
| ML-Powered-Resume-Selector-using-Naive-Bayes | 1 | 4 | 83% | 62% | 100% | 100% | 80% | 100% | 49 | 0 |
| Autonomous-Marketplace-Flipper | 1 | 4 | 67% | 62% | 75% | 100% | 100% | 100% | 94 | 0 |
| CS-GO_Skins-PriceTracker | 1 | 5 | 83% | 62% | 75% | 100% | 80% | 100% | 40 | 0 |

## What it found

1. **Almost nothing is shown.** 10 of 12 READMEs have no screenshot, diagram or demo (Goal 2, the show-don't-tell failure). Only Killer Sudoku and MARVIN have an image.
2. **MARVIN's README is stale.** Last changed 2026-07-15; 99 commits since. Its counts (27 skills, 23 tests, 100 files) are out of date (there are 34 skills).
3. **One dead external link:** the Kaggle dataset link in the anomaly-detection repository returns 404 (the same link is on the portfolio page).
4. **Purpose and status** are the most common soft gaps: READMEs that say what and how but not why, or never say what state the project is in. This matches what the 2018 README study found across GitHub.
5. **Linking:** several repositories have docs, a license or contributing guidance the README never points to.

## Per-repository findings

### marvin
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **info** [TRUST/numbers-to-verify] counts the text states: confirm each is still true (100 files; 23 tests; 27 skills)
- **warn** [TRUST/freshness] the README last changed 82 days before the latest commit, with 99 commit(s) since: likely out of date (README last touched 2026-07-15; repo last touched 2026-10-05)
- **warn** [SCOPE/navigation-aid] 495 lines with no table of contents (GitHub's outline menu helps, a contents list helps more)

### clarity-captions
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **warn** [START/path-to-first-success] no section for getting started (what do I type first?)
- **warn** [TRUST/about-metadata] no GitHub description (it is what search and link previews show)

### killer-sudoku
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **warn** [START/path-to-first-success] no section for getting started (what do I type first?)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit
- **warn** [SCOPE/navigation-aid] 115 lines with no table of contents (GitHub's outline menu helps, a contents list helps more)

### paper-dive
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit

### resume-tailor
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit
- **warn** [SCOPE/navigation-aid] 137 lines with no table of contents (GitHub's outline menu helps, a contents list helps more)

### AI-algorithms
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **warn** [START/path-to-first-success] no section for getting started (what do I type first?)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit

### ML_supervised_learning-Regression-Classification-project
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit
- **warn** [TRUST/about-metadata] no GitHub description (it is what search and link previews show)

### ML_unsupervised_learning-anomaly-detection-project
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **fail** [NAVIGATE/external-links] 1 external link(s) dead (https://www.kaggle.com/datasets/agungpambudi/network-malware-detection-connection-analysis -> 404)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit
- **warn** [TRUST/about-metadata] no GitHub description (it is what search and link previews show)

### full_ml_pipeline---social-media-project
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit
- **warn** [TRUST/about-metadata] no GitHub description (it is what search and link previews show)

### ML-Powered-Resume-Selector-using-Naive-Bayes
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit
- **warn** [TRUST/about-metadata] no GitHub description (it is what search and link previews show)

### Autonomous-Marketplace-Flipper
- **warn** [ORIENT/title] no top-level title (an H1) naming the project
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **warn** [START/path-to-first-success] no section for getting started (what do I type first?)

### CS-GO_Skins-PriceTracker
- **warn** [ORIENT/why] the intro says what it is but not why anyone would want it (the studies find purpose is what READMEs most often omit)
- **fail** [PROVE/visual-evidence] no screenshot, diagram or demo image: nothing shows the project working (show, don't only tell)
- **warn** [PROVE/worked-example] no code example (usage with the output it produces is the quickest proof)
- **warn** [START/path-to-first-success] no section for getting started (what do I type first?)
- **warn** [TRUST/status] never says what state it is in (stable? experimental? maintained?): the other thing READMEs most often omit
- **warn** [TRUST/about-metadata] no GitHub description (it is what search and link previews show)
