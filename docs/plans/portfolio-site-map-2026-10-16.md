# Portfolio site map: non-project pages (2026-10-16)

Before we design any page, this sets out where every piece of current content ends up. We'll then build one page at a time.
This replaces the 2026-10-09 mockups. Gil turned them down, apart from parts of Education A.

![Site map: every piece of content and the page it moves to](docs/screenshots/portfolio-site-map-2026-10-16.png)

## Content index

Everything below comes from the dev site (localhost:8080) as of today.

### Home (`/`)
| Content | Goes to |
|---|---|
| "Hello. I am..." typing animation (`[wp_code id="1"]`) | Home, hero (decision below) |

### About Me (`/about-me/`)
| Content | Goes to |
|---|---|
| "Hi, I'm Gil!" plus the pitch "I build AI systems that are meant to work in the real world." | About §1, with the pitch also on Home §2 |
| Early-career AI engineer: ranking, personalization, evaluation, agentic behavior | About §1 |
| Back-end lead for an AI-driven mobile app; LLM benchmarking with Snorkel AI | **Replaced.** About §2 becomes MARVIN and the projects built with it; Charter becomes a secondary line. Snorkel AI is removed everywhere (only on /about-me/ today) |
| Veteran, CBRN Defense Specialist | About §3 |
| Mother: immigrant, single parent, lost her hearing in her 30s, built a software career without a degree | About §3 |
| "AI as a system, not just a model" paragraph and closing line | About §4 |

### Achievements (`/achievements/`), being retired
| Content | Goes to |
|---|---|
| Hackathon 1st place, AI Tinkerers SF, "Agents That Buy & Sell" | About §5, linked to the Hackathon Winner project page |
| Eagle Scout: 22 merit badges, 2 Eagle Palms, service project | About §5 |
| Certificate of Merit for life-saving action, Scouting America | About §5 |

### Organizations (`/organizations/`), being retired
| Content | Goes to |
|---|---|
| CU Boulder Formula SAE, chassis team, telemetry project (Jan 2024 to now) | About §6 |
| CU Boulder Endurance Racing Team (Jan 2024 to now) | About §6 |
| Cybersecurity Club (Jan 2024 to now) | About §6 |
| Bug Bounty Collective (Jan 2024 to now) | About §6 |
| Computer Automation and Design Club, President, College of San Mateo (2019 to 2020) | About §6 |
| Israeli American Council, Mishelanu Fellow (Oct 2021 to May 2023) | About §6 |

### LinkedIn Recommendations (`/linkedin-recommendations/`), being retired
| Content | Goes to |
|---|---|
| Jose Gutierrez, Associate Professor, College of San Mateo (long quote) | About §7 |
| Cheyanne Curtis-Ramirez, Manager, Nordstrom Espresso Bar (quote) | About §7 |

### Computer Science (`/education/computer-science/`), being retired
| Content | Goes to |
|---|---|
| B.S. Computer Science Engineering, CU Boulder, graduated Aug 2025 | Education §1 as a diploma card. Fix the title: the diploma says **Bachelor of Science in Computer Science**, conferred 20 August 2025 |
| 19 courses (includes Designing for Defense, Intelligent Leadership, Writing in Arts & Sciences) | Education §3; fix the "Anlysis" typo |
| Capstone: Designing for Defense: DoD sponsors, SDA TAP Lab, CCDM detection, the goals, Python / Node-RED / AWS DoD cloud | **Removed** (Gil: no longer pertinent). The course name stays in Coursework |

### Certificates (`/education/certificates/`), being retired
| Certificate | Completed | Length | Image | Verify link |
|---|---|---|---|---|
| The Complete Python Developer (Udemy) | 2024-02-05 | 31 h | `/wp-content/uploads/2024/03/PythonDevCert-1.jpg` | https://ude.my/UC-c3c60dce-c75b-4c77-aadc-364b09c49210 |
| Web Security and Bug Bounty (Udemy) | 2024-03-12 | 10.5 h | `/wp-content/uploads/2024/03/Web-Security-certificate.jpg` | https://www.udemy.com/certificate/UC-4293b115-5d24-405b-9e82-5d196915adc6/ |
| UML Class Diagrams for Programmers (Udemy) | 2025-09-06 | 1.5 h | `/wp-content/uploads/2025/10/UML-Certificate.jpg` | https://www.udemy.com/certificate/UC-74c5e0ce-5892-455d-bfbc-d6b888426e00/ |

All three go to Education §4, the last section, keeping today's design. Gil's spec: the certificate image is the card, it reacts on hover, and a click opens the verify link in a new tab.
Fix the "Lenght" typo while moving them.

### Aerospace coursework (new), from the CU Boulder course history in Dropbox
Course names only. Grades and the student ID never go on the site.
| Course | Goes to |
|---|---|
| Aerospace Computing · Statics and Structures · Dynamics (transfer credit) | Education, Coursework (Aerospace) |
| Statics, Structures & Materials · Thermodynamics & Aerodynamics · Experimental/Computational Methods in Aerospace | Education, Coursework (Aerospace) |
| Dynamics & Systems · Vehicle Design & Performance · Thermodynamics & Heat Transfer | Education, Coursework (Aerospace) |
| Structures · Aerodynamics · Aerospace Sciences Lab II | Education, Coursework (Aerospace) |

Left out: Aircraft Dynamics, which was never completed. The ROTC leadership courses (Methods of Leadership & Management 1–2, Military Operations & Training 1–2) could support the veteran story on About (decision below).

### Skills (`/education/skills/`), being retired
| Content | Goes to |
|---|---|
| AI / ML: agents, supervised, unsupervised and deep learning, recommenders, fairness; Colab, LiquidMetal AI, Vercel; NumPy, pandas, scikit-learn, TensorFlow, PyTorch | Education §5 (decision below) |
| Back-end: Python 3.9, Java, JS, SQL; Flask, Node.js, Multer, REST, auth; PostgreSQL; Docker, AWS, Linux, Git | Education §5 |
| Cybersecurity: XSS, CSRF, OSINT, Nmap, Wireshark, Burp Suite, Metasploit, Hashcat | Education §5 |

### Contact (`/contact/`)
| Content | Goes to |
|---|---|
| Phone, email, LinkedIn, GitHub | Contact: email, LinkedIn and GitHub only. **Phone removed** |

### Resume (`/resume/`)
| Content | Goes to |
|---|---|
| Three PDFs: AI Software Engineer, Python Software Engineer, Cybersecurity Engineer | Replaced by **one master resume** PDF. Building the resume tailor into the site stays parked |

### Not in this pass
- Project hubs (All Projects, AI & ML, Software Engineering, Cybersecurity) were rebuilt on 2026-10-08.
- Project pages are deferred.
- Orphans ml-projects-2, backend and website-build, plus the duplicate `/distributed-llm-inference/` (page 5950), get removed.

## Gil's answers (2026-10-16)
- **Home** is a landing page that brings people in. No more information than today. Keep the text that pops in and out, but make it hyper-realistic, 3D and attention-grabbing.
- **About** gets rewritten. "What I work on" leads with MARVIN, its capabilities and the projects built with it, to show drive beyond the job. Charter is a secondary line that proves a real career in the field. Keep ideas from the current page.
- **Snorkel AI** comes off the site wherever it appears.
- **Nourished**, if it's mentioned anywhere, is "in development": it isn't on the App Store yet. It isn't on the site today.
- **Recommendations** keep today's layout (photo, pink name, role, quote), refined with cleaner photos and type.
- **Education** becomes a hub with a pink and blue left side menu, like the portfolio hubs. Order: Degree (shown like the certs, or as our own black and white line drawing, continuing the cert design up to it), Skills in full (where the Capstone was), Coursework (CS plus aerospace, which backs up the skills), Certificates (today's design). The Capstone is removed.
- **Contact:** email, LinkedIn and GitHub. No phone.
- **Resume:** just the master resume.

- **Title (provisional): "AI Engineer · Security · Research"**, to be checked with Gil's mum. No existing title fits him yet.
- **The landing page isn't about MARVIN.** MARVIN gets its own subdomain site later (like seal-speak.gileskayo.me), which can go much deeper on what it is and what it can do. Portfolio pages link to it one way.

## Landing options: 2, 3 and combined
Live on the dev site. Open them side by side at **http://localhost:8080/homepagefiles/landing-proto/compare.html**, and move the mouse over each one.

![Landing options side by side: 2 Living bridge, 3 Particle type, 2+3 Combined](docs/screenshots/portfolio-landing-options-2026-10-16.gif)

Sharper video: `docs/screenshots/portfolio-landing-options-2026-10-16.mp4`.

- **2 · Living bridge.** The bridge photo becomes a 3D scene. A depth map (made with Depth Anything V2) lets near parts of the bridge move more than the sky as the mouse moves, with fog drifting through and a soft light sweeping across. Each line's letters fly in from the viewer and fall away backwards.
- **3 · Particle type.** On a dark backdrop, each line is built from about 5,000 glowing particles with a few pink and blue sparks. The cursor pushes them apart, and they scatter and re-form into the next line.
- **2+3 · Combined.** The living bridge, dimmed, with the particle text floating in front and its own parallax, so the text feels closer than the bridge.

All three use today's text unchanged ("Gil Eskayo" / "Early-career AI Software Engineer" / "Focused on Machine Learning, Automation, and Agentic Systems"). The copy changes once the title is settled. They follow the system's reduced-motion setting, and use fewer particles on phones.

## Landing round 2: the painting comes alive
Gil's feedback on round 1: the whole-picture parallax doesn't suit the subject. What he wants instead:
- Bring the painting to life. Only the things that move in real life move, as if in a light breeze: fog and cloud strokes drift, plants sway, water shimmers.
- The mountains and the bridge stay solid.
- The mouse acts like a gust of wind.
- Keep the typing effect, and never break words.

Live at **http://localhost:8080/homepagefiles/landing-proto/compare2.html**.

![Round 2: A Alive painting, B Stroke rebuild](docs/screenshots/portfolio-landing-alive-2026-10-16.gif)

Sharper video: `docs/screenshots/portfolio-landing-alive-2026-10-16.mp4`.

- **A · Alive painting.** The original painting, split into regions: sky/fog, plants, water, and the solid bridge and mountains.
  - The regions come from a segmentation model plus the depth map, cleaned by hand-tuned rules (cables and towers are forced solid).
  - Plants sway and spring back from gusts. The sky's brush strokes drift and fold, and swirl where the mouse passes. Thin fog banks drift through.
- **B · Stroke rebuild.** The painting's own dark sky strokes (about 4,500 pieces) are lifted out and painted out of a clean copy of the sky.
  - They're then drawn back as separate ribbons, so each real stroke bends and gets swept by the mouse on its own.
  - Plants and water move as in A.
- **Text** is today's typing effect, with today's lines. Each line is laid out in full before it types, and words are unbreakable, so nothing jumps to a new line mid-word.

### Contact and Resume pages (added after Gil's review)
Gil liked the About mockup. He asked for real Contact and Resume pages, not links that jump to the bottom of About.

- **Contact** (`brand-proto/contact.html`): email, LinkedIn and GitHub as large cards, plus a line on the roles he's open to (AI/ML, security, research). No phone.
- **Resume** (`brand-proto/resume.html`): a web version of the master resume.
  - Left column: experience and selected projects. Side column: education, skills, training and recognition. A Download PDF button.
  - Built from `~/.claude/resume/master.md`, leaving out the entries it marks private (Nourished, Snorkel AI) and the phone number.
- The menu on every mockup page now goes to the real pages.
- The About page's Charter line is filled in from the master: AI Engineer, Charter Communications, Apr 2026 to now.

![Contact](docs/screenshots/portfolio-brand-contact-2026-10-16.png)
![Resume](docs/screenshots/portfolio-brand-resume-2026-10-16.png)
![Phone: Contact and Resume](docs/screenshots/portfolio-brand-phone-contact-resume-2026-10-16.png)

**Found while building:**
- **Eagle Scout merit badges:** the site says 22, the master resume says 31.
- **Aircraft Dynamics:** the master lists it (ASEN 3128) among the aerospace courses, but the course history shows it was never completed. I left it off the site.
- **The PDF button** needs a public master PDF. Nothing exists yet that exports a public version of the master (with private entries and the phone removed).

## Landing round 3: step into the painting
Gil's feedback on round 2:
- A wins on resolution, but the scene still feels disconnected.
- Each part should have its own physics:
  - fog you can swirl around in, along with the strokes
  - plants you can brush back and forth
  - water that flows
  - a bridge and mountains that look 3D but stay static and can't be messed with
- "As if I was there in that world and could interact with it."

Live at **http://localhost:8080/homepagefiles/landing-proto/living.html**.

![Round 3: stirring the fog, brushing the plants, crossing the water](docs/screenshots/portfolio-landing-living-2026-10-16.gif)

Sharper video: `docs/screenshots/portfolio-landing-living-2026-10-16.mp4`.

**How it works**
- **Air:** a small real-time air simulation runs under the picture, with swirl preservation (vorticity confinement). Only the mouse pushes it.
- **Fog / sky strokes** are carried by that air. Stirring leaves swirls that curl on and drift back over a few seconds. Fog banks get swirled too.
- **Plants** are damped springs driven by the air: brush them and they lean, then rock back and forth before settling. Tips move more than the base.
- **Water** flows continuously (two staggered phases, so it never visibly resets), with glints, and the air ripples it.
- **Bridge and mountains** never move. Every move shrinks to zero next to solid structure, so cables can't smear. Lighting from the depth map slowly shifts across them so they read as solid 3D forms.
- **Idle breeze:** a gentle breeze runs separately from the simulation, so it can't build up.

**Measured after brushing the plants** (mean pixel change): plants 8.8, bridge deck 0.2, tower 0.5, mountains 1.1 (fog and light only).

## Brand direction mockup (2026-10-16)
Gil asked what his marketable themes would do to the site.

- **Themes:**
  - Precision when it counts (CBRN, the life-saving award).
  - A builder who ships (hackathon, MARVIN, apps).
  - Range across disciplines (aerospace, CS, telemetry, security).
  - Technology for people (Clarity Captions for his mom).
  - Self-driven.
- **Mood:** grounded, precise, quietly bold, cinematic; warm underneath.
- **What it changes visually:**
  - The hero's monochrome, hand-drawn bridge carries through every page.
  - Paper-and-ink colours. Engineering-drawing details: numbered section labels, hairline rules, corner ticks around frames.
  - A crisp sans for headings, a warm serif for story text, and a mono font for labels.
  - Pink only marks "where you are / what matters", and blue only marks links.

Live on the dev site:
- About: **http://localhost:8080/homepagefiles/brand-proto/about.html**
- Education: **http://localhost:8080/homepagefiles/brand-proto/education.html**

![Before and after: About](docs/screenshots/portfolio-brand-about-before-after-2026-10-16.png)
![Education mockup](docs/screenshots/portfolio-brand-education-2026-10-16.png)
![Phone](docs/screenshots/portfolio-brand-phone-2026-10-16.png)

The copy is a first pass built from facts already on the site; the real rewrite is still for Gil to approve. "Day job · Charter" has a placeholder for his role.

## Degree: verifiable like the certs
The diploma (`Dropbox/Gil/Gil's resume/archive/2025/CollegeDiploma.pdf`) is a certified e-diploma with code **25Z8-DPSX-G40X** printed on it. Its verification page can be the click-through target, the same way the certs work. The exact verify URL still needs confirming.

## Order of work
1. **Education first**, with the hub, the diploma card and the certificate cards.
2. Home landing: prototype the 3D directions on the dev site and pick one.
3. About rewrite. Gil approves the copy.
4. Contact, Resume, then the nav, the header title and the redirects.

## Brand pages, round 2 (2026-10-22)
Gil looked at the pages in Chrome: he loves everything except the landing. Changes made:
- **Resume:** more room between the hero and "01 · Experience" (it also lines up with the header now). The Home Depot is replaced by **CBRN Defense Specialist · U.S. Army** (labelled "Service" until Gil gives dates). "What I build on my own time" is now **MARVIN, Seal Speak, Distributed LLM Inference**: the marketplace agent and Designing for Defense are gone.
- **About:** same three projects, same order as the resume (MARVIN flagship, then Seal Speak and Distributed LLM as cards). Clarity Captions is renamed Seal Speak, and the card no longer says "free" ($4.99 once). "Armed Forces" is now "Army".
- **MARVIN numbers, recounted 2026-10-22:** 33 skills (`skills/*/SKILL.md`), 4,300+ tests (4,383 collected by pytest), 75 merged `pipeline/` PRs on G-Eskayo/marvin, 19 `com.marvin.*` launchd jobs on the mac-mini. The old 35 / 2,770 / 60 / 18 had no recorded source.
- **Contact:** more space between the Email, LinkedIn and GitHub cards (16 px to 36 px).
- **Education:** Coursework shows the full lists: 18 CS courses and 12 aerospace. "…" opens the rest of the list in place, and "Show less ↑" closes it.

![Resume](docs/screenshots/portfolio-brand-resume-2026-10-22.png)
![About](docs/screenshots/portfolio-brand-about-2026-10-22.png)
![Contact](docs/screenshots/portfolio-brand-contact-2026-10-22.png)
![Coursework, closed](docs/screenshots/portfolio-brand-coursework-closed-2026-10-22.png)
![Coursework, CS opened](docs/screenshots/portfolio-brand-coursework-open-2026-10-22.png)

Second pass, same day (Gil views the site in a window under 900 px wide, so the narrow layout is what he sees):
- Resume project titles link to their pages: `/ai-projects/marvin/`, `/software-engineering/clarity-captions/` (the Seal Speak page, still titled Clarity Captions), `/ai-projects/distributed-llm-inference/`. About's project cards and "Read the build" use the same links, and the header name goes Home on every page.
- Narrow layout: Resume gets 88 px under the hero (was 40). On Contact, "Open →" stays beside its title instead of dropping under it.
- Coursework "…" looks like a list row again. It turns pink on hover; a click opens the full list, and a "↑" at the bottom (also pink on hover) closes it.
- About, Teams: Formula SAE, Endurance Racing, Cybersecurity Club and Bug Bounty Collective now end in 2025 (graduation).
- **Skill count:** MARVIN has 33 skills on both Macs and on GitHub. The dashboard's "36 SKILLS WIRED" counts `~/.claude/commands/*.md`: 32 skill wrappers plus 3 Raindrop commands (third-party) and a dead link to the deleted `self-optimize` skill, and it misses `variable-tracker`.

Still to do: refresh the MARVIN story on About (and the MARVIN page) with the newer work, and the Army dates.

## Portfolio hubs and landing, round 4 (2026-10-22)
Gil: the brand look is approved for Education, About, Contact and Resume. Extend it to Portfolio and Home. Resume Education now says "Plus 12 aerospace engineering courses".
- **Portfolio:** `brand-proto/portfolio.html` (All projects), `portfolio-ai.html`, `portfolio-security.html`, `portfolio-software.html`, generated by `brand-proto/build_portfolio.py` from `deploy/other-projects/manifest.json`. One side menu is the only filter. All projects opens with the top three (MARVIN, Seal Speak, Distributed LLM), then a grid of the other 15. Cards lift like the certificate cards, and the title turns pink on hover. Thumbnails are copied into `brand-proto/thumbs/`. Every page's nav now goes to these mockups.
- **Landing, Gil's direction:** keep the original's behaviour, with the refined painting behind it. The statements type out in one complete pass, then the page settles on the open screen with the site nav over the painting, and the painting stays interactive behind the nav. The statements must be new and grammatically correct (draft below, for Gil to approve). Gil will describe the painting look in his own words.

![Portfolio hub](docs/screenshots/portfolio-brand-hub-2026-10-22.png)

## Home usable, project pages in the brand look (2026-10-22)
- **Home (interim):** `landing-proto/home.html`: the round-3 painting with the site header over it (the painting still reacts to the mouse), today's typing lines, and "See my work" and "Resume" buttons. Every page's Home link goes here. The painting look and the new statements wait for Gil's description.
- **Narrow nav:** under 900 px the header nav no longer disappears. It becomes a scrollable row under the name, on every page.
- **Project pages:** `brand-proto/project-<slug>.html` for the 7 long-form pages (MARVIN, Seal Speak, Distributed LLM, Killer Sudoku, Hackathon agent, Paper Dive, Resume Tailor), generated by `build_projects.py` from `content/longform/*.json`. Hub cards, About and Resume link to them. The other 11 projects have no long-form content yet.
- **Seal Speak copy:** the long-form content still says Clarity Captions and calls it free ("free forever"). The mockup swaps in the name and flags the "free" lines for Gil's rewrite.
- **MARVIN numbers:** use `brain-map/scripts/facts.py` (`/wp-content/marvin-map/facts.json`, recounted nightly): 5,273 tests, 93 merged pipeline PRs (all repos), 20 background jobs. Skills: the real count is **33**. facts.py's 35 counts two memory entries in `~/.claude/manifest.json`'s index (`project-ai-development-theory`, `reference-mcp`), and the dashboard's 36 counts `~/.claude/commands`. Both counters need a fix.

![Home with nav, narrow](docs/screenshots/portfolio-home-nav-2026-10-22.png)
![MARVIN project page](docs/screenshots/portfolio-brand-project-marvin-2026-10-22.png)

## Every project page in the new look (2026-10-22)
Gil: the whole site gets this design. On project pages, the project's own generated hero is the banner background, and the bridge stays everywhere else.
- `brand-proto/build_projects.py` now builds all 18 `project-<slug>.html`. The 7 long-form pages come from `content/longform/*.json`. The 11 older pages are reduced from the dev site's rendered page: headings (h4–h6 and bold "Label:" lines become section headings), text, real lists (from "•" lines too), figures and links. Stray tags are balanced, and "ATT&CK" stays text. Heroes are copied to `brand-proto/heroes/<slug>-hero.jpg`.
- **Skill counters:** fixed in marvin PR #602 "Skill counts: count real skills (33), not memories or command files" (`facts.py` counts SKILL.md entries; the dashboard counts skill folders). Waiting for Gil's review. The MARVIN page's numbers come from facts.json, so they show 33 after the merge and the next nightly run.

## Decisions
<!-- marvin:decisions -->
### landing: Which landing look do we build?
- [ ] Round 3 · Step into the painting, as is
- [ ] Round 3, with changes (text below)
- [ ] None yet: change it (text below)

### landing-notes: What to change on the one you like (text) (optional)

### brand: The brand direction
- [ ] Yes, build the pages in this style
- [ ] Close, but change things (text below)
- [ ] No, try a different direction

### brand-notes: What to change (text) (optional)

### eagle: Eagle Scout merit badges
- [ ] 22 (what the site says)
- [ ] 31 (what the master resume says)

### clearance: Show "Secret clearance (reinstatable)" publicly on the Resume page?
- [ ] Yes
- [ ] No, resume PDF only

### homedepot: Keep The Home Depot on the public resume?
- [ ] Yes
- [x] No

### pdf: The resume PDF
- [ ] Generate one from the master (private entries and phone removed)
- [ ] I'll upload my own

### degree: How the degree shows
- [ ] The diploma image as a card, same as the certs
- [ ] Our own black and white line-drawn version
- [ ] Prototype both and I'll pick

### edu-layout: Education structure
- [ ] Hub: a separate page per section, with the left menu (like Portfolio)
- [ ] One page; the left menu jumps to each section

### rotc: Mention the ROTC leadership courses on About? (optional)
- [ ] Yes, in "How I got here"
- [ ] No
