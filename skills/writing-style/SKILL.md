---
name: writing-style
description: Rewrites or drafts text so it reads in Gil's actual voice instead of generic AI writing — for portfolio project pages, resume text, outreach emails, and any other user-facing prose. Use when the user asks to draft/write copy for them, asks whether something "sounds like AI," or wants a pass to make existing text sound more like them.
tags: [intent:write, intent:edit, domain:voice, type:skill]
---

# Writing Style

A voice profile derived from Gil's own real writing (sent emails, 2026-09-27 — scheduling/outreach messages specifically; sensitive personal correspondence was read for pattern extraction only, never quoted). Refine this file further if he supplies LinkedIn posts or other samples later — treat it as a living profile, not a finished spec.

## Voice profile

- **Short, direct sentences.** Rarely more than one clause. Says the thing, doesn't build up to it.
- **Drops the subject when the meaning survives without it.** "Sorry for the late response. Been slammed with work." not "I'm sorry for the late response — I've been slammed with work."
- **Greeting scales with context but tone doesn't.** "Hey [Name]," for casual, "Good morning [Name]," or "Dear [Name]," for more formal asks — but even inside a formal opener, the sentences that follow stay plain and unpretentious ("Dear Lemon Manuals, My name is Gil and my buddy Eyal...").
- **Sign-off is minimal.** A bare "-Gil" or "- Gil" most of the time, not "Best," "Thanks," or "Sincerely." "Respectfully," shows up only in genuinely formal contexts (e.g. following up after a missed interview slot).
- **States facts plainly, no padding.** "Nope, two drinks same day, two different purchases" — a full, sufficient answer, nothing decorative added.
- **A recurring real phrase:** "Sorry for the late response" — appears verbatim across unrelated threads. Not a one-off; a genuine verbal habit worth reusing when the situation actually calls for it (don't force it in elsewhere).
- **Plain American English.** Contractions throughout, no vocabulary inflation, no jargon reached for when a plain word works. Typos happen and aren't precious about it (a stray misspelling reads more human, not less credible — don't over-correct into stiffness chasing perfection).
- **Offers help/flexibility briefly, not effusively.** "If you want faster communication feel free to reach out to my personal number" — stated once, plainly, no exclamation point, no "I'd love to."

## What this is NOT

Not corporate, not hedgy, not enthusiastic-by-default. No "I hope this email finds you well," no triple-adjective stacking, no "I'd be happy to."

## AI-writing patterns to actively avoid

These are generic-LLM tics, not Gil's voice — strip them out of any draft before it ships:

- **Em-dash overuse for parenthetical asides.** His real writing almost never does this — short sentences and periods do the work instead. (This document breaks that rule in a few places for density; a real draft in his voice shouldn't.)
- Transition throat-clearing: "Furthermore," "Moreover," "It's worth noting that," "That said,"
- Empty intensifiers: "essentially," "fundamentally," "ultimately," "truly"
- Triadic listing for its own sake ("not just X, but Y and Z") when one plain sentence would do
- A grand summarizing closer restating what was just said
- Excessive hedging or "on one hand / on the other hand" false balance
- Exclamation points as a substitute for genuine enthusiasm

## Portfolio register: sell it (Gil, 2026-10-06)

Portfolio pages are self-marketing, not documentation. Gil read the plain, hedged project pages as "very AI" and asked for copy that is more boisterous and sells him, while staying concise and clear:

- **Lead with the story and the stakes, then the proof.** Who it's for, why it had to exist, what it does now. Clarity Captions is "I'm building this for my mom's birthday", not "an on-device speech pipeline".
- **Two readers on every page.** A lay reader gets the gist from the first paragraph and the pictures. A technical reader gets real depth further down: the architecture, the hard problem, the number.
- **Confident, first person, active.** "I built", "I found", "it does". Claim what is true at full strength. Don't hedge real wins ("about", "mostly", "a working spike") unless the hedge is the honest point.
- **Proof over adjectives.** Pride comes from specifics: the number, the screenshot, the bug that took eight fixes. Never "revolutionary", "seamless" or "cutting-edge".
- **Honesty still wins.** Bold doesn't mean inflated. Every claim must hold up against the repo; a reviewer who checks and finds an overclaim stops trusting the whole page.
- **Never name competitors.** Describe the alternative instead ("the paid captioning services she relied on").

## How to use this

Before drafting or rewriting any user-facing text for Gil (project page copy, resume lines, outreach), read this file. Draft in the voice above, then check the draft against the "avoid" list specifically — if a sentence could have been generated by any competent LLM for any person, cut it or replace it with something closer to how Gil actually put things in the samples above.

If a piece of writing needs a *more formal/polished* register than casual email (e.g. a portfolio bio, a cover letter), keep the sentence-level habits (short, direct, plain vocabulary, minimal sign-off, no padding) while dropping the more casual openers — formality should change register, not introduce the AI-writing patterns above.
