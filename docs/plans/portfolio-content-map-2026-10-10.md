# gileskayo.me content map (non-project pages)

Started 2026-10-10. Gil rejected the 10-09 mockups (Home 1-3, About A/B, Education A/B) and wants to go page by page: map where everything is and where it belongs first, then research successful examples, then design each page. Home is parked until Gil decides.

Source of current state: the live production pages, fetched 2026-10-10 (read only). Nav is the production menu (menu 79).

## Current nav

- Home
- Portfolio ▸ Hack Winner: Agentic AI Marketplace · AI / Machine Learning · Web App Backend · Cybersecurity · Helicopter Crutches
- Education ▸ Computer Science Degree · Certificates
- Skills (points at /education/skills/)
- About ▸ About Me · Achievements · LinkedIn Recommendations
- Contact
- Resume

Organizations (/organizations/) has no nav entry.

## Current pages: what's on each

| Page | URL | What's there | Notes |
|---|---|---|---|
| Home | / | Bridge background, typing line "Hello. I am... Gil Eskayo", one-line title. 20 words, no links. | Parked. |
| About Me | /about-me/ | Portrait (Gil-Eskayo.jpg), ~280 words: applied AI focus, back-end lead on an AI mobile app, Snorkel AI LLM benchmarking, veteran / CBRN specialist. | Copy to be rewritten in the sell-it voice; Gil approves the text. |
| Achievements | /achievements/ | Hackathon 1st place (AI Tinkerers SF), Eagle Scout, Certificate of Merit for life-saving action. ~76 words. | Event link carries `utm_source=chatgpt.com`. |
| Organizations | /organizations/ | CU Formula SAE chassis/telemetry, CU Endurance Racing, Cybersecurity Club, Bug Bounty Collective, CAD Club president (CSM), IAC Mishelanu Fellow. | Not in the nav. Dates say "Current" from Jan 2024. |
| LinkedIn Recommendations | /linkedin-recommendations/ | Two recs in a LinkedIn-style card with photo: Jose Gutierrez (CSM professor), Cheyanne Curtis-Ramirez (Nordstrom manager). | Gil likes this format. Wants each card to open the real rec on LinkedIn in a new tab. |
| Computer Science Degree | /education/computer-science/ | BS CS Engineering, CU Boulder, Aug 2025; 17 courses; capstone "Designing for Defense" (DoD sponsors). | Typo "Anlysis". |
| Certificates | /education/certificates/ | 3 Udemy certs (Python dev, Web Security & Bug Bounty, UML), each with a verify link. | Typo "Lenght" ×2. Course links carry coupon codes. |
| Skills | /education/skills/ | Grouped lists: AI/ML, back-end (languages, web, data), cybersecurity. | Mixes concepts ("Supervised Learning") with tools. |
| Resume | /resume/ | Three PDF resumes (AI Software Engineer, Python Software Engineer, Cybersecurity Engineer), each opens in a new tab. | |
| Contact | /contact/ | "LET'S CONNECT." Phone, email, LinkedIn, GitHub. 12 words. | Phone number is public. Gil's call whether to keep it. |

Site-wide: every page shows a byline and raw timestamp under the title (for example "Gil 2026-02-10T18:14:46-07:00"), and some bylines say "dorit". That's Avada's post meta leaking onto pages.

## Already decided (STEERING.md, 2026-10-09)

- Retire the orphans `ml-projects-2`, `backend`, `website-build`, and the duplicate top-level `/distributed-llm-inference/` (5950).
- Fold Certificates, Computer Science and Skills into one **Education** page.
- Fold Achievements, Organizations and LinkedIn Recommendations into **About Me** as sections.
- About Me copy gets rewritten; Gil approves the text before it lands on dev.

## Decided 2026-10-10

- The 10-09 mockups are rejected. No layout gets picked from them.
- Work goes page by page, Gil leading. Home waits.
- Recommendations keep the current LinkedIn-style card with photos. Each card links to the real recommendation in a new tab.
- Education uses the project-page look (hero + title card + sections) for parity with the project pages.
- Every page's design starts from research into successful real examples (reports in `~/.claude/outbox/portfolio-research-2026-10-10/`).

## Research findings (2026-10-10)

Full reports: `~/.claude/outbox/portfolio-research-2026-10-10/about-pages.md` and `education-resume-contact.md`.

- **About:** short summary first (NN/g: people read 20-28% of a page), real headshot beside the name, recommendations with name, title, relationship and date. No per-recommendation LinkedIn URL exists: "Read on LinkedIn" goes to `/in/gileskayo/details/recommendations/` (logged-in only; logged out it redirects to the profile), and the recommender's name/photo goes to their profile. LinkedIn's brand policy forbids imitating its look, so the card should be in site styling with the official "in" logo.
- **Education:** proof before credentials (capstone leads), no skill bars, grouped skills with "Used in: [project]" links, certificate cards with a Verify button.
- **Resume:** HTML quick-scan summary plus a labelled PDF download per role. No embedded PDF viewer.
- **Contact:** never form-only; visible email (obfuscated against harvesters), LinkedIn, GitHub; optional 3-field form with Avada Honeypot + Turnstile and a reply-time line. Public phone number is Gil's call.
- **Nav:** 4-6 top items. Dropdown parents with no page of their own (Portfolio, Education, About today) go nowhere when clicked and fail on touch. Proposed: Home · Projects · Education · About · Resume · Contact.

Corrections to the agents' audits: recommendation and certificate images render fine (lazy-load placeholders fooled the fetch). Real defect: the UML certificate image's alt text is "web analytics". "Brooksource/Charter" in the About report's org timeline is unverified; don't use it without Gil.

## Decided 2026-10-10 (round 2)

- **Nav target accepted:** Home · Projects · Education · About · Resume · Contact.
- **Projects:** discussion and review before any change. A lot of work is already in it and a lot remains, so nothing there changes until it's been reviewed with Gil.
- **Employer:** Gil's current job is at Charter. Never mention the recruiter who placed him, anywhere.
- **About:** undecided between separate pages (clutter of pages) and one page with sections (clutter on one page).

## Organizing principle (Gil, 2026-10-16)

"Tailoring the website to the audience and each page to its purpose." Every page decision starts from who reads it and its one job.

**Audience (confirmed):** recruiters and hiring managers first, engineers on an interview loop second, Seal Speak users/family/press third (the marketing site serves them; the portfolio just needs to be a clean landing).

**Target roles (confirmed):** AI/ML engineer, security engineer, research. Not generic software engineering. Gil knows the security side is thin: more security projects are planned next, and the cert pipeline is AWS Certified Generative AI Professional, then CompTIA SecAI+ (neither held yet; show only as in progress if he's enrolled or scheduled).

| Page | Main reader | Its one job |
|---|---|---|
| Home | Everyone, first 10 seconds | Who Gil is and which roles he's after, then route: best 3-4 projects, Resume, Contact |
| Projects | Engineers, then recruiters | Prove he can build: story first, technical depth below |
| About | Recruiters | Trust and character (veteran, Eagle Scout, leadership), backed by recommendations |
| Education | Recruiters checking boxes | Confirm credentials fast: degree, verifiable certs, skills linked to the projects that prove them |
| Resume | Recruiters | The right role-specific PDF in one click, plus a quick-scan summary |
| Contact | Anyone ready to reach out | Make reaching him effortless |

The page jobs are a draft; the audience and roles are confirmed.

## Ideas brought in from other chats (gathered 2026-10-16)

From Gil's own messages in other sessions. None of these has been designed yet.

1. **Show the research behind decisions** (Seal Speak chat, 2026-10-09): "link that and display what we are grabbing from it and how it is leading our decisions", on the portfolio and/or the marketing pages. Memory rule: every research-informed decision goes in the repo's evidence log (source, takeaway, confidence, decision, public use). This redesign's own research (the two reports above) qualifies, and so does Seal Speak's.
2. **Redo the Clarity Captions project page** (2026-10-10) with the final app renderings and screenshots, at the level of detail the app is at now. The app is now called **Seal Speak** (renamed 2026-10-11; App Store name), so the page title, card and slug need the new name. This falls under the Projects discussion rule.
3. **Seal Speak marketing site on a gileskayo.me subdomain** (2026-10-10). Gil set up a HostGator CNAME for `seal-captions.gileskayo.me` pointing at GitHub Pages. Checked 2026-10-16: it redirects to `g-eskayo.github.io` and shows GitHub's "Site not found", so it isn't live. The one-page site (clarity-captions #44 "[W] Seal website: a one-page static site, previewed on GitHub Pages") is closed. Still open: #46 "[W] Domain, hosting and DNS: choose and buy the domain, connect the site, link it from the portfolio and GitHub" and #47 "[W] Marketing assets: screenshots, a short demo video and store-ready images". Open question: the subdomain still says "seal-captions" while the app is Seal Speak.
4. **v1 (bad) and v2 (better) versions of weaker projects** (2026-10-06): redo the less impressive projects, refine them for better results, and post both versions. Gil didn't know how to show version history on the site. MITRE is the one redo in progress. Projects discussion item.
5. **Component parity** (2026-10-02, mostly built into the template system): one GitHub button in the same place on every project page, interactive elements as the reference templates. Applies to the new non-project pages too: they should be built from the same elements.

## Open

- Resume and Contact: Gil mentioned earlier ideas for both; they weren't found in any transcript, handoff or doc, so they need restating.
- Final nav after consolidation.
- Where Skills lives once it's inside Education (nav item or not).
- Home.
