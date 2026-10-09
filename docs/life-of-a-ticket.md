# The life of a MARVIN ticket

*How work moves through MARVIN, from an idea to code running on both Macs. Where it works, where it gets stuck,
and how far we are from "constant flow". Written 2026-10-09, after a night of fixing the pipeline.*

---

## How to read this

- **Colors mean the same thing everywhere** (in the pictures and the text):
  - 🟢 **Works on its own.** Nobody has to touch it.
  - 🟡 **Works, but needs you, or is fragile.**
  - 🔴 **A known problem.** Every red item is listed in [Where it breaks](#where-it-breaks-the-red-list).
  - ⚪ **Planned.** Not built yet.
  - 🟣 **Your step.**
- **Short on time?** Read [The 30-second version](#the-30-second-version), then look at the pictures.
- **Words you might not know** are in the [Glossary](#glossary) at the end.
- **There are 8 pictures.** They're drawn by a script, so they stay up to date. **To update them** after a fix: `~/.agents/venv/bin/python ~/.agents/docs/diagrams/make_pipeline_diagrams.py`.

---

## The 30-second version

1. **A ticket is a to-do item** on GitHub. It says what to build and how we'll know it's done.
2. **Every hour, the Mac mini picks the most important ready ticket** and gives it to an AI agent.
3. **The agent builds it in its own private copy of the code,** runs the tests, and opens a **pull request (PR)**.
4. **You approve the PR** in the dashboard. That's your one required step.
5. **MARVIN merges it, checks nothing broke, and both Macs pick up the new code.** Then the cycle repeats.

When it works, you only touch step 4. When it doesn't, something in the [red list](#where-it-breaks-the-red-list)
is usually the reason.

**Where the time actually goes** (measured over the last 46 pipeline PRs): the machine parts take minutes, and the
waiting takes hours.

![Where the time goes](docs/diagrams/where-time-goes.svg)

---

## The picture: start to finish

![The life of a ticket, with every loop back](docs/diagrams/life-of-a-ticket.svg)

**Read it top to bottom.** The middle column is the happy path.
- **Boxes on the right** are the loops: where work goes *back* to an earlier step to try again.
- **Boxes on the left** are the known problems that slow it down.

---

## The journey, step by step

Each step answers four questions: **What happens? Who does it? How long? What can go wrong?**

### 1 · Idea 🟡

- **What happens:** something needs doing. You notice it, a daily digest or sweep suggests it, or a session finds a bug.
- **Who:** you, or MARVIN.
- **How long:** whenever it comes up.
- **What can go wrong:** 🔴 **two sessions chase the same idea at once.** On 2026-10-08/09, two tabs and the pipeline
  built the same five fixes. Fixed by #326: sessions now see each other's work. Your open tabs need a restart to get it.

### 2 · Ticket filed 🟢

- **What happens:** the idea becomes a GitHub issue with:
  - **acceptance criteria:** how we'll know it's done;
  - a **project label**, so it shows on the right board (ADR 0060);
  - **"Blocked by"** links when it depends on another ticket.
- **Who:** MARVIN, usually through the `to-issues` skill.
- **How long:** a minute.
- **What can go wrong:** a ticket filed for another project lands on MARVIN's board. The hourly project tagger fixes the
  clear cases and lists the unclear ones in Health.

### 3 · Triage 🟢 *(since 2026-10-09)*

- **What happens:** the triage agent reads the ticket and puts it in one state:
  - `ready-for-agent`: an agent can build it;
  - `ready-for-human`: it needs you (a login, a decision, a purchase);
  - `needs-info`: something's missing; the agent comments what.
- **Who:** the triage agent, hourly.
- **What can go wrong:** until today it was **propose-only**. It worked out what to do but changed nothing, so
  **53 tickets had no state and the pipeline saw nothing to do.** That's why both Macs were idle. Switched on tonight:
  138 label changes, and **20 tickets became ready**.

**Every state a ticket can be in, and what moves it:**

![Ticket states](docs/diagrams/ticket-states.svg)

### 4 · Prioritize 🟡

- **What happens:** each ticket gets `priority:p0` (urgent) to `p3` (whenever). The score comes from what it unblocks,
  due dates, whether it's a bug, and its age.
- **Who:** the prioritize agent, hourly.
- **What can go wrong:** 🟡 still **propose-only until 2026-10-12**. Until then the scan uses "oldest first" more than
  real priority.
- 🔴 **Chains wait on you.** A ticket can't start while its blocker is open. For example, the MARVIN Mobile push chain
  (#162–#165) waits on #153, creating the push key, which needs your Apple login.

### 5 · Scan + claim 🟢

- **What happens:** every hour the **Mac mini** looks for tickets that are ready, unclaimed, unblocked and not already
  done. It takes the most important one and labels it `claimed:mac-mini-1`, so no one else takes it. It also runs
  sooner, right after a merge.
- **Parallel work:** up to **3 at once**, 2 on the mini and 1 on the laptop. It holds back if disk drops under 15 GB or
  GitHub's hourly allowance under 20%.
- **What can go wrong:**
  - 🔴 **Stale claims.** A claim that outlives its run blocks a rebuild forever (#255 sat 12 hours). The
    stale-claims agent can release them, but it's propose-only.
  - **"Already done" false matches.** A docs commit that only *mentioned* #213 and #259 made them look finished.
    Fixed tonight: a commit now counts only if it *claims* the ticket.

### 6 · Build 🟢

- **What happens:** an AI agent gets its **own copy of the code** (a worktree, on branch `pipeline/<repo>#<n>`). It
  plans, writes the code and the tests, and commits. It never touches the copy you work in.
- **Who:** an agent run (`run_ticket.py`), on the mini or the laptop.
- **How long:** usually 10–40 minutes.
- **What can go wrong:** 🟡 an agent can be refused a command its allowlist blocks (#277, fixed, being measured).

### 7 · Verify 🟢

- **What happens:** the project's own tests and checks run. Nothing leaves until they pass.
- **Loop ↩ retry:** if tests fail, the agent fixes and re-runs.
- **The failure breaker:** if **3 different tickets** of one project fail the same way within **2 hours**, that
  project's dispatch pauses. The machine is probably broken, not the tickets, so it stops wasting runs.

### 8 · PR raised 🟢

- **What happens:** a pull request opens. Its description carries the evidence (metrics before and after, test
  results) and `Closes #<n>`, so merging it closes the ticket.

### 9 · MR Review 🟡

- **What happens:** the dashboard's **MR Review** tab shows one card per PR. Each card has **one headline** and only the
  buttons that make sense, for example "Ready to merge", "Conflicts with main" or "Its ticket is already closed".
- **What can go wrong:**
  - 🔴 **Every PR waits for you,** even small, green, low-risk ones: a **median of 9.4 hours** per PR over the last
    46. This is the biggest brake on "constant flow"
    (see [Where you want to be](#where-you-want-to-be)).
  - 🔴 **UI bugs reach main.** Nothing screenshots or clicks through a UI change before merge (#126). Tonight a
    pipeline-built screen blanked the Activity tab. React's hook rules are now tested on every file, but a full
    "does it render" check is still missing.

### 10 · You approve 🟣

- **What happens:** you press **Approve**, or **Deny** with a reason.
- **Loop ↩ rebuild (denied):** your reason goes on the ticket, and the ticket is sent back to be rebuilt.
  - 🔴 The **refeed** agent, which re-queues sent-back tickets, is **propose-only**. Sent-back tickets can park
    instead of being rebuilt.
  - After **3** reworked PRs, a ticket goes to a person instead of looping.

### 11 · The merge gate 🟢 *(reworked 2026-10-09, ADR 0061)*

![The merge gate's questions](docs/diagrams/merge-gate.svg)

The gate asks two questions:

| Is the PR behind main? | Does main now touch the same files? | What happens |
|---|---|---|
| No | — | **Merge directly** (seconds) |
| Yes | No | **Merge directly**; the timeline says "no retest needed" |
| Yes | Yes | **Rebase onto main, rerun the tests, then merge** (minutes; cut off at 40 min) |
| Can't tell | — | **Retest, to be safe** |

Before the gate it also checks three things:
- the PR targets `main`, not some side branch;
- its ticket wasn't sent back;
- its GitHub checks passed.

### 12 · Merged to main 🟢

- GitHub closes the ticket. The board moves the card to **Done**.

### 13 · After the merge 🟡

![After the merge, in order](docs/diagrams/after-merge.svg)

Several things happen automatically, in order:

1. **Stacked PRs move onto main.** A PR built on top of the one that just merged is pointed at `main`. If this is ever
   missed, MR Review's refresh catches it.
2. **Every other open PR gets a conflict check** (seconds; no tests, no pushes). A conflict shows on its card.
3. **The dashboard app rebuilds** if the PR touched `dashboard/`.
4. **main-health re-runs the full test suite.** If main is red, **all merges are refused** until it's fixed.
5. **The scan runs again,** so the next ticket starts right away.

### 14 · Running on both Macs 🔴

- **What happens:** `code_sync` pulls the new code onto each Mac **every 30 minutes**.
- **What can go wrong:**
  - **Long-running programs keep old code.** The merge server and the dashboard keep running what they started with
    until they restart. The dashboard rebuild waits 15 minutes after a change and won't interrupt an open app until it
    is an hour behind. Tonight the mini's app wasn't running at all after a rebuild.
  - **Sync collisions.** Auto-generated metrics files collide in sync stashes (#280). It happened twice tonight.

### 15 · Proves its purpose ⚪

- **What happens:** a ticket that promises something measurable ("fewer GitHub calls", "faster Approve") carries a
  **purpose metric**. After its date, MARVIN measures it and comments **✅ met** or **❌ missed**.
- **Loop ↩ the big one:** a missed purpose **becomes a new ticket**, back at step 1. That loop is what turns a pipeline
  into a system that improves itself.
- **Status:** built (#304), but few tickets carry a metric yet.

---

## Every loop, in one place

| Loop | Starts when… | Goes back to | Who acts | Status |
|---|---|---|---|---|
| **Needs info** | the ticket is missing something | Triage (3) | **you** answer | 🟡 |
| **Retry** | tests fail during the build | Build (6) | the agent | 🟢 |
| **Failure breaker** | 3 tickets fail the same way in 2 h | pauses that project | **you** clear it | 🟢 |
| **Denied** | you press Deny | Scan (5), rebuilt | refeed agent | 🔴 propose-only |
| **Conflict, safe kind** | both sides only *added* lines | stays at Review (9) | conflict repair: rebase, test, push | 🟢 new tonight |
| **Conflict, real** | an existing line changed on both sides | Scan (5) if pipeline-built; flagged for you if hand-made | the scan | 🟢 |
| **CI failed** | GitHub checks fail | Scan (5), rebuilt | the scan | 🟢 |
| **Main went red** | main's own tests fail | blocks every merge | **you** or a fix ticket | 🟡 |
| **Stale claim** | a claim outlives its run | Scan (5) | stale-claims agent | 🔴 propose-only |
| **Purpose missed** | the metric isn't met | Idea (1) | MARVIN files a ticket | ⚪ few metrics |

---

## The merge edge cases ("the zoo")

Everything that happens around merges, including the strange cases we hit tonight.

**The most common one, a conflict, as a picture:**

![When a PR conflicts](docs/diagrams/conflicts.svg)

| Situation | What MARVIN does now | Since |
|---|---|---|
| PR is up to date | Merges in seconds | always |
| PR is behind, no shared files | Merges directly. The timeline says "no retest needed" | 2026-10-09 |
| PR is behind and shares files | Rebases, retests, then merges | ADR 0026 |
| **Stacked PR** (built on another PR) | After the parent merges, it moves onto `main` automatically; MR Review's refresh is the safety net | 2026-10-09 |
| Parent closed **without** merging | Left alone. Moving it would drag in unmerged work. The card says "change its base" | 2026-10-09 |
| Both sides added lines in one file | Keeps both (main's first), tests, pushes. No rebuild | 2026-10-09 |
| A real conflict, **pipeline** PR | Ticket sent back, naming the files | 2026-10-09 |
| A real conflict, **hand-made** PR | Flagged on the PR once. Never sent for an agent rebuild | 2026-10-09 |
| Sent back, but its PR still conflicts | The scan tries the cheap repair; if it works, clears "sent back" | 2026-10-09 |
| PR whose ticket is already closed | Card says "probably superseded", no Approve | 2026-10-09 |
| GitHub checks failing or pending | Waits while pending; sent back if failed | earlier |
| Main is red | Every merge refused until main is green | earlier |
| GitHub says "slow down" | The gate pauses every caller on that Mac together; background work waits | 2026-10-08 |
| Generated files conflict (`bench/metrics`, `graphify-out`) | Takes main's copy and regenerates | #225 |
| Merge server running old code | 🔴 Restarts only when the app rebuilds | open |

---

## The architecture: what runs where

![MARVIN's architecture](docs/diagrams/marvin-architecture.svg)

**Three places, one source of truth:**

- **GitHub is the shared truth.** Tickets, PRs, claims and the `main` branch live there, and both Macs read and write
  it. Everything costs a little of one shared **hourly allowance of 5,000 GitHub calls**. Tonight's fixes cut the
  biggest spenders: tests calling GitHub for real, and the dashboard re-reading every repo on every click.
- **The Mac mini is the factory.** It runs 24/7: the hourly scanner, the agents, the main merge server, main-health,
  and the health checks.
- **The laptop is where you work.** It runs your Claude sessions, the dashboard, a standby scanner (only if the mini
  goes quiet), and one agent slot.

**The safety parts that make it trustworthy:**

| Part | Plain words | Why it exists |
|---|---|---|
| **Claims** | "I'm on it" stickers on tickets | so two machines never build the same ticket |
| **Worktrees** | a private copy of the code per job | so an agent never touches your copy |
| **The merge gate** | the bouncer at the door to `main` | so broken or stale work can't get in |
| **main-health** | a smoke alarm on `main` | so a break is caught within minutes |
| **The failure breaker** | a fuse | so a broken machine stops burning runs |
| **The GitHub gate** (`bin/gh`) | a traffic light for GitHub calls | so the shared allowance never runs dry |
| **Session awareness** (#326) | a "who's working on what" board | so sessions don't duplicate each other |

---

## Where you want to be

You said it: **"a constant CI/CD of production and accomplishing tasks and reaching goals and dreams."**
In practice that means:

1. **Goals turn into tickets on their own.** North stars and purpose metrics produce the next tickets. You set
   direction; you don't write to-dos.
2. **Tickets flow without waiting.** Triage, priority, dispatch and recovery all act on their own.
3. **You approve only what's risky.** Small, green, low-risk PRs merge themselves, and you see a summary. Big or risky
   ones still wait for you.
4. **Merged means running.** Both Macs, the apps and the website update within minutes, safely.
5. **Every change proves it helped.** Missed purposes become new tickets automatically.

## Where we are

![Today vs where you want to be](docs/diagrams/flow-readiness.svg)

*The percentages are my honest estimate of how automatic each stage is today, not a measurement.*

**The short of it:**
- **The factory floor works:** triage, dispatch, build, verify and merge.
- **The doors at both ends are mostly manual:** where work comes from (ideas, goals) and where it lands (approve,
  deploy, proving its purpose).

---

## Where it breaks: the red list

The problems we know about, most flow-blocking first. Each has a next step.

| # | 🔴 Problem | What it does to flow | Next step |
|---|---|---|---|
| 1 | **Every PR waits for your Approve** | Work stops at review: **median 9.4 h** per PR (last 46), even small green ones | Auto-merge for low-risk PRs (green, small, no shared files, not touching the gate itself); you get a summary |
| 2 | **Recovery agents are propose-only** (stale claims, refeed) | Sent-back or stale tickets park instead of retrying (#255 sat 12 h) | Let them act, starting with "sent back and still claimed, nothing running" |
| 3 | **Prioritize is propose-only until 10-12** | The most important work isn't reliably first | Let it act (it only changes `priority:` labels) |
| 4 | **Deploy lags and restarts are manual** | Merged code isn't running for 30–60+ min; the mini's app was down tonight | Pull on merge (not every 30 min); always restart the merge server and app after a rebuild; Health alarm when the app isn't running |
| 5 | **Sync collisions on generated files** (#280) | Stalls a Mac's sync; twice tonight | Stop syncing generated metrics files through git, or always take the newer copy |
| 6 | **Other projects' dispatch is off** | Portfolio and nourished tickets never start | Your switch, per project, once each has a test command you trust |
| 7 | **Chains waiting on you** | 4 mobile tickets wait on one 5-minute task (#153) | A "needs you" list ranked by how much each unblocks |
| 8 | **UI changes aren't checked before merge** (#126) | A blank screen reached `main` tonight | Render each tab in a test (and screenshot) before merge |
| 9 | **Sessions on different Macs can't see each other** | Duplicate work is still possible across Macs | Share the "working on" list between Macs |
| 10 | **Few tickets carry a purpose metric** | We can't tell if work helped | The to-issues skill asks for one on every "faster / fewer / cheaper" ticket |

## The next five moves, in order

1. **Let the recovery agents and prioritize act.** These are config changes, like tonight's triage switch. They
   unblock stuck tickets with no new code.
2. **Fast deploy.** Pull and restart right after a merge, plus a Health alarm when an app isn't running. "Merged"
   then means "running" within minutes.
3. **Auto-merge for low-risk PRs.** The biggest step toward constant flow. Needs a short design together first:
   what counts as low-risk is your call.
4. **Render checks for UI PRs (#126).** Stops blank-screen bugs before merge, which makes auto-merge safe for UI too.
5. **Goals → tickets.** North stars and missed purposes file their own tickets, closing the big loop.

---

## Glossary

| Word | For a five-year-old | For a professional |
|---|---|---|
| **Ticket** | a to-do card | a GitHub issue with acceptance criteria and state labels |
| **Triage** | sorting the cards into piles | assigning a state: ready-for-agent, ready-for-human, needs-info |
| **Claim** | an "I'm on it" sticker | a `claimed:<machine>` label; the dispatcher skips claimed tickets |
| **Agent** | a helper robot that writes code | a headless Claude run with a scoped allowlist in its own worktree |
| **Worktree** | its own copy of the toy, so it can't break yours | a separate git checkout on its own branch |
| **PR (pull request)** | "please add my change" | a reviewed, tested proposal to merge a branch into `main` |
| **main** | the real toy everyone plays with | the default branch both Macs run |
| **Merge gate** | the bouncer at the door | pre-merge checks: base, sent-back, CI, overlap-aware retest |
| **Rebase** | moving your change onto the newest toy | replaying a branch's commits on top of the current `main` |
| **Conflict** | two people drew on the same spot | the same lines changed on both sides; git can't choose |
| **Stacked PR** | a change built on another unfinished change | a PR whose base is another PR's branch |
| **main-health** | a smoke alarm | the suite re-run on every `main` move; merges refused while red |
| **Failure breaker** | a fuse that trips | pauses a project's dispatch after repeated same-signature failures |
| **Propose-only** | "tell me, don't do it" | an agent that records planned changes without applying them |
| **Purpose metric** | "did it actually help?" | a measurable claim checked after a date: ✅ met / ❌ missed |
| **CI/CD** | build, check and ship, over and over, by itself | continuous integration and deployment |

*Related: ADR 0026 (merge gate), 0047 (dispatch weighting), 0052 (parallel dispatch), 0060 (projects and boards),
0061 (overlap rule), 0062 (session awareness). CONTEXT.md has the full history.*
