---
name: reverse-engineering
description: Static and dynamic binary analysis tool wrappers (radare2, Ghidra, Frida) for authorized reverse engineering, CTF, and defensive security contexts.
tags: [intent:analyze, intent:reverse-engineer, domain:security, type:skill]
---

# Reverse Engineering Skill

Provides gated access to static and dynamic binary analysis tools for authorized reverse engineering, CTF competitions, security research, and defensive security use cases.

## Authorization

These tools are dual-use: they can analyze binaries you own or have explicit written authorization to analyze (CTF targets, your own applications, authorized security testing). **They must never be used for:**
- Analyzing third-party software without authorization
- Mass targeting or automated scanning of multiple binaries you don't own
- Supply-chain compromise, malware development, or detection evasion
- Any use outside an authorized security context (CTF, pentesting engagement, research, defensive work)

Every wrapper script requires explicit authorization via either:
- `--authorized` flag, or
- `MARVIN_RE_AUTHORIZED=1` environment variable

Without authorization, the tool refuses to run and prints this requirement.

---

## Tools

### 1 — Radare2/Rizin Static Analysis

Disassemble, decompile, and inspect binary structure: functions, strings, imports, cross-references.

**Command:**
```bash
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/r2_analyze.py \
  --binary /path/to/binary \
  --authorized \
  [--output-format json|text]
```

**Features:**
- List all functions with addresses and sizes
- Extract all strings
- Show imports and external references
- Basic disassembly of key functions
- Cross-reference graph (callers/callees)

**Requirements:** radare2 or rizin installed (`brew install radare2` or `brew install rizin`)

**Example:**
```bash
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/r2_analyze.py \
  --binary ./crackme.bin \
  --authorized \
  --output-format json
```

---

### 2 — Ghidra Headless Analysis

Import binaries into Ghidra, run decompilation, extract high-level code structure.

**Command:**
```bash
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/ghidra_headless.py \
  --binary /path/to/binary \
  --authorized \
  [--function-name main] \
  [--output-format json|text]
```

**Features:**
- Full binary import and auto-analysis
- Decompilation of specific functions to pseudocode
- Symbol recovery and type inference
- Data cross-reference analysis
- Output to JSON or human-readable format

**Requirements:** Ghidra installed and `analyzeHeadless` on PATH

**Example:**
```bash
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/ghidra_headless.py \
  --binary ./crackme.bin \
  --authorized \
  --function-name main
```

---

### 3 — Frida Dynamic Instrumentation

Attach to or spawn a process and trace function calls, modify behavior in real-time.

**Command:**
```bash
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/frida_trace.py \
  --target-process firefox \
  --function-name malloc \
  --authorized \
  [--spawn]
```

**Features:**
- Attach to running processes or spawn new ones
- Trace calls to specified functions (arguments, return values)
- Log timestamps and thread IDs
- Real-time output

**Requirements:** Frida installed (`pip install frida-tools` or `brew install frida`)

**Example:**
```bash
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/frida_trace.py \
  --target-process /tmp/target.bin \
  --function-name main \
  --authorized \
  --spawn
```

---

## Behaviors

- **Dependency checking:** If a tool (radare2, ghidra, frida) is not found, the script exits with a clear install hint, not a traceback.
- **Timeouts:** All external tool invocations have finite timeouts (default 60s) to prevent hanging the agent session.
- **File validation:** Binary paths are checked for existence, readability, and size (max 500MB) before analysis.
- **Concurrency:** Each analysis gets its own temporary project/output directory; multiple runs against the same binary don't interfere.
- **Safe argument passing:** All binary paths are passed as literal argv elements (list-form subprocess, never shell=True) to prevent command injection.

---

## Workflow

1. **Identify the binary** you own or have authorization to analyze (CTF target, your own app, authorized pentest target).
2. **Choose a tool:**
   - Use **Radare2** for quick structural analysis (functions, strings, imports).
   - Use **Ghidra** for deep decompilation and type recovery.
   - Use **Frida** for dynamic behavior (runtime traces, function hooks).
3. **Invoke with authorization:** Include `--authorized` or set `MARVIN_RE_AUTHORIZED=1`.
4. **Interpret results:** Radare2/Ghidra output pseudo-code and symbol info; Frida outputs trace logs.

---

## Examples

### CTF: Reverse a crackme binary
```bash
# Quick structural analysis
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/r2_analyze.py \
  --binary ./crackme.bin --authorized

# Deep decompilation of main()
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/ghidra_headless.py \
  --binary ./crackme.bin --authorized --function-name main
```

### Security research: Trace malloc calls in a test binary
```bash
~/.agents/venv/bin/python ~/.agents/skills/reverse-engineering/scripts/frida_trace.py \
  --target-process ./test-app --function-name malloc --authorized --spawn
```

---

## Security notes

- These tools are not sandboxed; running unknown binaries (especially with Frida's dynamic attach) can be unsafe. Only analyze binaries you control or have explicit authorization for.
- Radare2 and Ghidra are static analysis (safe). Frida is dynamic (runs code; be cautious).
- All output is logged locally; nothing is uploaded to external services.
