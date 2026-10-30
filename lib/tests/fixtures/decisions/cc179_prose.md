<!-- excerpt of G-Eskayo/clarity-captions PR #179 body (as opened, 2026-10-28), trimmed to its Decisions section -->

## Decisions

- **d1. Banner look and wording (image 1).** "You're getting a call / Pause this conversation and caption the call?" with [ Caption call ] [ Not now ]. **Recommend: approve as shown.**
- **d2. The paused note during the call (image 2).** A slim strip under the pop-up: "Your conversation is paused. It comes back when the call ends." Options: (a) keep it, (b) drop it and show only the call. **Recommend (a)**, so she knows the room's words aren't lost.
- **d3. End-of-call step (image 3).** [ Save transcript ] [ Don't save ]. A saved call goes into the same saved conversations as the iPhone app (30 days, ADR 0022). The Mac app has **no saved-conversations list yet**, so for today a saved call is kept but can't be opened on the Mac. Options: (a) as shown, list is a follow-up, (b) also show a "Show transcript" button after saving that opens the text. **Recommend (a)** for 3 p.m.
- **d4. If she ignores the banner.** **Recommend:** it stays up for the whole call and the room keeps being captioned (same as Not now). It goes away when the call ends. Nothing switches by itself.
- **d5. Call answered while Seal Speak is open but not captioning.** **Recommend:** go straight to the call format with no banner, then the save step at the end. If Seal Speak isn't running, nothing happens (macOS won't start it for a call).
- **d6. What "the room" means from now on.** #172 made the default "room and call together". With #178, the normal mode becomes **the room (microphone) only**, and the call is captioned only after [ Caption call ]. Options: (a) room only, then switch, as the ticket describes, (b) keep "both" as the default and use the banner only to switch to call-only. **Recommend (a)**: it matches your answer "If they say no: keep captioning the room only".
- **d7. How the Mac knows about a call** (research, details in #178). CallKit's call observer is **not available on macOS** (marked unavailable in the macOS 27 SDK). The plan is to watch Core Audio's list of which apps are using sound, which is public and needs no permission: the call is live while FaceTime's call service is using the microphone and ends when it stops. **The Mac sees a call once it's answered (the mic opens), not while it rings**, so the banner shows as the call starts. Still to confirm on a live FaceTime call; the finding is in #178 and evidence E24.

## Checks
