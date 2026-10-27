# MARVIN Dictate

Hold **Fn**, talk, let go: the words are typed wherever the cursor is (Claude Code, the dashboard, Mail, a browser).
It runs on Apple's on-device speech engine (the one Seal Speak uses), so there's no usage cap, no account, and the
audio never leaves the Mac. Ticket: marvin#730.

| Do this | What happens |
|---|---|
| Hold Fn, talk, let go | Listens while held; types when you let go |
| Double-tap Fn | Hands-free: keeps listening until you press Fn again |
| Esc while listening | Throws it away (and the Esc doesn't reach the app) |
| Fn + another key | Treated as the shortcut it is, not dictation |

What it types is tidied: "um", "uh", "ah", "er" are dropped, spacing is fixed, and a finished sentence gets a space
after it so the next dictation doesn't run into it.

## Install

```sh
tools/dictate/install.sh
```

Builds, signs with your Apple Development identity (so permissions survive rebuilds), installs to
`~/Applications/MARVIN Dictate.app`, starts it, and adds it to Login Items. On first start macOS asks for:

- **Accessibility** and **Input Monitoring**: to see Fn and to paste. System Settings → Privacy & Security.
- **Microphone**.

If the Globe/Fn key opens the emoji picker, set System Settings → Keyboard → "Press 🌐 key to" → **Do Nothing**.

## Your words

`~/.config/marvin-dictate/words.txt` (menu → Open word list). One per line:

```
MARVIN                      fixes capitals
clod code => Claude Code    replaces a word or phrase
```

The list is also handed to the speech engine as hints. Changes apply from the next dictation.

## History and speed

Every dictation is appended to `~/Library/Application Support/MARVIN Dictate/history.jsonl`: when, seconds spoken,
`finishMs` (time from letting go of Fn to the words being typed), the app, and the text.

## Tests

```sh
swift test --package-path tools/dictate
```

The key gesture, clean-up, word list, clipboard restore and history are unit tests. The engine tests have `say` speak
a sentence into a file and check the real engine hears it; they skip where the English model isn't installed.
`MarvinDictate --transcribe <audio file>` does the same from the command line.
