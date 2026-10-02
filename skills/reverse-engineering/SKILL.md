---
name: reverse-engineering
description: Static and dynamic binary analysis via Ghidra headless, radare2/rizin, and Frida — disassembly, decompilation, string/xref extraction, runtime instrumentation. Gated to owned or explicitly authorized targets only. Use when asked to reverse-engineer, disassemble, decompile, or instrument a binary, or for CTF/pentest binary-analysis tasks.
tags: [domain:security, intent:analyze, intent:reverse-engineer, type:skill]
---

# Reverse Engineering

Binary analysis, disassembly, decompilation, and instrumentation for owned or authorized targets only.

## Authorization Gate

**Do not proceed without authorization.** This skill operates on binaries and system processes to extract code and behavior — powerful tools that can cross into unethical territory if misused.

Before using any tool in this skill, you must confirm:

1. **Target ownership or explicit authorization**: The binary/process is one you own, work on as part of an authorized engagement (pentest, bug bounty, red-team contract), or solve for an educational context (CTF, security course).
2. **Scope is a binary or process, not a live third-party system**: This skill handles static analysis of compiled code and dynamic instrumentation of local processes. Live network targets and infrastructure belong elsewhere.
3. **Findings stay local**: Do not auto-exfiltrate results, auto-report to external services, or distribute findings without the user's explicit instruction.

The wrapper scripts enforce this gate via an `--i-own-this-target` flag or equivalent — the gate has a real mechanical tooth, not just prose.

Refuse targets that:
- Are someone else's shipped software without explicit written authorization.
- Are malware samples intended for redistribution.
- Are third-party systems with the goal of circumventing DRM, license checks, or security controls as an end goal (not a means to audit your own system or fulfill a lawful contract).

## Tools

### 1. Ghidra Headless — Static Analysis (Functions, Decompilation, Strings, Xrefs)

**Quick start:**
```bash
python3 scripts/ghidra_report.py --binary <path/to/binary> --i-own-this-target
```

Dumps to JSON:
- **Functions**: all discovered function entry points and boundaries
- **Decompilation**: pseudocode for one or all functions (specify `--function main` or `--all-functions`)
- **Strings**: defined string literals in .rodata / .data sections
- **Cross-references**: xrefs to/from named functions

Output is agent-parseable JSON suitable for further analysis. For full flag reference, see `REFERENCE.md`.

### 2. radare2/rizin — Static Analysis (Quick Triage)

**One-liner:**
```bash
r2 -q -A -c 'aflj; izj; iij' <binary>
```

Returns JSON listings of:
- Functions (`aflj`), strings (`izj`), imports (`iij`).

**Reproducible triage script** (optional):
```bash
bash scripts/r2_static_report.sh --binary <path/to/binary> --i-own-this-target
```

Bundles a standard sequence: `aaa` (auto-analyze), `afl` (function list), `pdf @ main` (disassemble main), `iz` (strings), `ii` (imports), `axt` (all xrefs to main). Deterministic, suitable for repeated invocation.

**Note:** `rizin` (the community fork) is a drop-in alternative with the same command surface (`rz-bin`, `rizin -A`).

### 3. Frida — Dynamic Instrumentation (Runtime Tracing)

**Example trace**: hook an exported function, log args/return/backtrace:
```bash
python3 scripts/frida_attach.py \
  --spawn <path/to/binary> \
  --script scripts/frida_trace_example.js \
  --i-own-this-target
```

`frida_trace_example.js` is a minimal Frida instrumentation script that:
- Attaches to a named function (configurable by editing the script)
- Logs function arguments, return value, and a call stack on each invocation
- Streams output back to the parent Python process

Extend the script with additional `Interceptor.attach()` calls to trace multiple functions, hook syscalls, or modify behavior on the fly.

### 4. Hex Tools — Byte-Level Inspection

For quick byte-level inspection without a full tool:
```bash
hexdump -C <binary> | head -20
xxd <binary> | head -20
```

For interactive hex editing and structured dissection (not agent-automatable):
- **ImHex**: GUI hex editor with a grammar-based parser for binary formats.

## Workflow

**Static → Dynamic:**
1. Start with Ghidra or radare2 to map function names, entry points, and high-level structure.
2. Identify interesting functions or data structures.
3. Use Frida to instrument those functions at runtime, observe actual behavior.

**Common patterns:**
- **Malware analysis**: Ghidra for intent, Frida to confirm behavior without full execution.
- **Vulnerability research**: Ghidra to find candidate functions, Frida to test exploitation paths.
- **Reverse-engineering a binary format**: radare2 strings + Ghidra decompilation to understand parsing logic.
- **Debugging a compiled binary**: Frida instrumentation with printf-debugging instead of gdb breakpoints.

## Unsupported / Deferred

- **IDA Pro**: deferred — no licensed idalib/idapython install present. Revisit if available.
- **Live debuggers (GDB, LLDB)**: out of scope for this skill. Use your system debugger directly.

---

For detailed flag documentation, examples, and troubleshooting, see `REFERENCE.md`.
