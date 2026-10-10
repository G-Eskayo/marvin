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

## Open

- Resume and Contact: Gil mentioned earlier ideas for both; they weren't found in any transcript, handoff or doc, so they need restating.
- Final nav after consolidation.
- Where Skills lives once it's inside Education (nav item or not).
- Home.
