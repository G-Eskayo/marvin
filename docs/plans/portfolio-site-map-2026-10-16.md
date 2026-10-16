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
| Back-end lead for an AI-driven mobile app; LLM benchmarking with Snorkel AI | About §2 (decision below: is this current? Charter isn't mentioned) |
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
| B.S. Computer Science Engineering, CU Boulder, graduated Aug 2025 | Education §1 |
| 19 courses (includes Designing for Defense, Intelligent Leadership, Writing in Arts & Sciences) | Education §3; fix the "Anlysis" typo |
| Capstone: Designing for Defense: DoD sponsors, SDA TAP Lab, CCDM detection, the goals, Python / Node-RED / AWS DoD cloud | Education §2 |

### Certificates (`/education/certificates/`), being retired
| Certificate | Completed | Length | Image | Verify link |
|---|---|---|---|---|
| The Complete Python Developer (Udemy) | 2024-02-05 | 31 h | `/wp-content/uploads/2024/03/PythonDevCert-1.jpg` | https://ude.my/UC-c3c60dce-c75b-4c77-aadc-364b09c49210 |
| Web Security and Bug Bounty (Udemy) | 2024-03-12 | 10.5 h | `/wp-content/uploads/2024/03/Web-Security-certificate.jpg` | https://www.udemy.com/certificate/UC-4293b115-5d24-405b-9e82-5d196915adc6/ |
| UML Class Diagrams for Programmers (Udemy) | 2025-09-06 | 1.5 h | `/wp-content/uploads/2025/10/UML-Certificate.jpg` | https://www.udemy.com/certificate/UC-74c5e0ce-5892-455d-bfbc-d6b888426e00/ |

All three go to Education §4. Gil's spec: the certificate image is the card, it reacts on hover, and a click opens the verify link in a new tab.
Fix the "Lenght" typo while moving them.

### Skills (`/education/skills/`), being retired
| Content | Goes to |
|---|---|
| AI / ML: agents, supervised, unsupervised and deep learning, recommenders, fairness; Colab, LiquidMetal AI, Vercel; NumPy, pandas, scikit-learn, TensorFlow, PyTorch | Education §5 (decision below) |
| Back-end: Python 3.9, Java, JS, SQL; Flask, Node.js, Multer, REST, auth; PostgreSQL; Docker, AWS, Linux, Git | Education §5 |
| Cybersecurity: XSS, CSRF, OSINT, Nmap, Wireshark, Burp Suite, Metasploit, Hashcat | Education §5 |

### Contact (`/contact/`)
| Content | Goes to |
|---|---|
| Phone (000) 000-0000, geskayo@gmail.com, LinkedIn, GitHub | Contact (decision below on the phone number) |

### Resume (`/resume/`)
| Content | Goes to |
|---|---|
| Three PDFs: AI Software Engineer, Python Software Engineer, Cybersecurity Engineer | Resume, unchanged |

### Not in this pass
- Project hubs (All Projects, AI & ML, Software Engineering, Cybersecurity) were rebuilt on 2026-10-08.
- Project pages are deferred.
- Orphans ml-projects-2, backend and website-build, plus the duplicate `/distributed-llm-inference/` (page 5950), get removed.

## Order of work
1. **Education first.** Most of its content is already settled, and Education A was the one mockup Gil partly liked. Certificate cards to his spec.
2. About Me, then Gil approves the copy.
3. Home.
4. Contact, Resume, then the nav and redirects.

## Decisions
<!-- marvin:decisions -->
### hero: Home hero
- [ ] Keep the "Hello. I am..." typing animation
- [ ] Replace it with a portrait and the one-line pitch
- [ ] Decide when we reach Home

### work: About §2 "What I work on"
- [ ] Rewrite it around Charter (current job)
- [ ] Keep the mobile app and Snorkel AI work, and add Charter
- [ ] I'll tell you what's current (text below)

### work-text: What's current at work? (text) (optional)

### skills: Where the Skills list lives
- [ ] Education, trimmed to what's still true
- [ ] Education, kept in full
- [ ] Drop it from the site (the resume covers it)

### phone: Phone number on Contact
- [ ] Keep it public
- [ ] Remove it (email, LinkedIn and GitHub only)
