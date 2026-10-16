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

## Degree: verifiable like the certs
The diploma (`Dropbox/Gil/Gil's resume/archive/2025/CollegeDiploma.pdf`) is a certified e-diploma with code **25Z8-DPSX-G40X** printed on it. Its verification page can be the click-through target, the same way the certs work. The exact verify URL still needs confirming.

## Order of work
1. **Education first**, with the hub, the diploma card and the certificate cards.
2. Home landing: prototype the 3D directions on the dev site and pick one.
3. About rewrite. Gil approves the copy.
4. Contact, Resume, then the nav, the header title and the redirects.

## Decisions
<!-- marvin:decisions -->
### title: Header title under your name (replaces "Software Engineer")
- [ ] AI Systems Engineer
- [ ] Autonomous Systems Engineer (ties together AI agents and aerospace)
- [ ] Applied AI & Security Engineer
- [ ] AI Engineer · Security · Research
- [ ] Something else (text below)

### title-text: Your own title idea (text) (optional)

### hero: Landing direction to prototype first (pick any)
- [ ] 3D MARVIN brain: a rotating node graph with depth; your name assembles from it and dissolves into the next line
- [ ] Living bridge: the bridge photo turned into a 3D parallax scene with moving fog and light; the text floats in 3D in front of it
- [ ] Particle type: each line forms out of thousands of glowing particles that react to the cursor, then scatters into the next line

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
