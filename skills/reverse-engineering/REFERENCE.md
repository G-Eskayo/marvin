# Reverse Engineering — Reference

Detailed flags, examples, and troubleshooting for each tool.

## Ghidra Headless

### Command Reference

```bash
python3 scripts/ghidra_report.py \
  --binary <path/to/binary> \
  --i-own-this-target \
  [--function <name>] \
  [--all-functions] \
  [--output <json-file>] \
  [--ghidra-project-dir <dir>]
```

### Flags

- `--binary <path>` (required): Path to the ELF/PE/Mach-O binary to analyze.
- `--i-own-this-target` (required): Authorization gate — confirms you own or have written authorization for this target.
- `--function <name>`: Decompile a specific function (e.g., `main`, `strlen`). If omitted, lists all functions without decompilation.
- `--all-functions`: Decompile every discovered function. Warning: can be slow for large binaries.
- `--output <file>` (default: `stdout`): Write JSON to a file instead of stdout.
- `--ghidra-project-dir <dir>` (default: `/tmp/ghidra-projects`): Directory where Ghidra stores its analysis project. Reuse across runs to skip re-analysis.

### Output Format

JSON object with keys:
- `binary`: path to the analyzed binary
- `arch`: detected architecture (e.g., `x86-64`, `ARM`)
- `entry_point`: entry point address (hex)
- `functions`: array of function objects, each with:
  - `name`: function name
  - `address`: start address (hex)
  - `size`: function size in bytes
  - `decompilation`: pseudocode (if `--function` or `--all-functions` specified)
- `strings`: array of discovered string literals
- `imports`: external functions (dynamic linking symbols)
- `xrefs`: cross-reference records (source → targets)

### Examples

**List all functions in a binary:**
```bash
python3 scripts/ghidra_report.py --binary ./myapp --i-own-this-target | jq '.functions[] | {name, address}'
```

**Decompile main() and write to file:**
```bash
python3 scripts/ghidra_report.py --binary ./myapp --function main --i-own-this-target --output myapp-main.json
```

**Reuse a previous analysis (skip re-analysis):**
```bash
python3 scripts/ghidra_report.py --binary ./myapp --function main --i-own-this-target --ghidra-project-dir ~/.ghidra-cache
```

### Troubleshooting

- **"analyzeHeadless not found"**: Ghidra must be installed. Set `$GHIDRA_HOME` or ensure `ghidra_analyzeHeadless` is in `$PATH`.
- **"Failed to import binary"**: The binary format may not be recognized (e.g., custom packed format). Try with radare2 as a fallback.
- **Decompilation is poor/empty**: Some functions may not decompile well, especially if stripped, optimized, or in unusual architectures. Check `strings` and cross-references instead.

---

## radare2 / rizin

### One-liner (Quick Triage)

```bash
r2 -q -A -c 'aflj; izj; iij' <binary>
```

Flags:
- `-q`: quiet (minimal output)
- `-A`: auto-analyze (runs `aaa` internally)
- `-c '<commands>'`: run commands and exit
- `aflj`: function list (JSON)
- `izj`: strings (JSON)
- `iij`: imports (JSON)

### Reproducible Triage Script

```bash
bash scripts/r2_static_report.sh \
  --binary <path/to/binary> \
  --i-own-this-target \
  [--output <json-file>]
```

Runs a standard sequence in a deterministic order:
1. `aaa` — auto-analyze
2. `afl` — function list
3. `pdf @ main` — disassemble main function
4. `iz` — strings
5. `ii` — imports
6. `axt` — all xrefs to main

Output is a JSON object with keys for each analysis section.

### Flags (Script)

- `--binary <path>` (required)
- `--i-own-this-target` (required)
- `--output <file>` (default: `stdout`)

### Examples

**Quick triage of a binary:**
```bash
r2 -q -A -c 'aflj; izj; iij' ./unknown_binary | jq '.functions | length'
```

**Search for a string in radare2:**
```bash
r2 -q -c 'iz ~pattern' ./binary
```

**Disassemble a specific address:**
```bash
r2 -q -c 'pd 20 @ 0x400000' ./binary
```

### Transition to rizin

If using the community fork (`rizin`), substitute:
- `r2` → `rizin`
- `rz-bin` (for binary info)
- Same command syntax, same JSON output format

---

## Frida

### Python Launcher

```bash
python3 scripts/frida_attach.py \
  --spawn <path/to/binary> \
  --script <path/to/script.js> \
  --i-own-this-target \
  [--pid <pid>] \
  [--process-name <name>]
```

### Flags

- `--spawn <binary>`: Spawn a new process running `<binary>` and attach Frida.
- `--pid <pid>`: Attach Frida to an existing process by PID (alternative to `--spawn`).
- `--process-name <name>`: Attach by name (e.g., `--process-name chrome`).
- `--script <path>` (required): Path to a Frida instrumentation script (.js).
- `--i-own-this-target` (required): Authorization gate.

### Example Instrumentation Script (frida_trace_example.js)

```javascript
// Hook a named function, log args/retval/backtrace
const targetFunction = 'my_function_name'; // Edit this

const functions = Module.findExportByName(null, targetFunction);
if (!functions) {
  console.log(`[!] Function "${targetFunction}" not found.`);
} else {
  console.log(`[+] Hooked "${targetFunction}" at ${functions}`);
  Interceptor.attach(functions, {
    onEnter(args) {
      console.log(`[CALL] ${targetFunction}(`);
      for (let i = 0; i < args.length; i++) {
        console.log(`  arg${i}: ${args[i]}`);
      }
      console.log(')', {
        backtrace: Thread.backtrace(this.context, Backtracer.ACCURATE)
          .map(DebugSymbol.fromAddress)
          .join('\n  ')
      });
    },
    onLeave(retval) {
      console.log(`[RETURN] retval: ${retval}`);
    }
  });
}
```

### Examples

**Trace a function in a spawned binary:**
```bash
python3 scripts/frida_attach.py --spawn ./myapp --script ./hook.js --i-own-this-target
```

**Attach to a running process by PID:**
```bash
python3 scripts/frida_attach.py --pid 1234 --script ./hook.js --i-own-this-target
```

**Attach by process name:**
```bash
python3 scripts/frida_attach.py --process-name firefox --script ./hook.js --i-own-this-target
```

### Extending the Trace Script

Add multiple `Interceptor.attach()` calls to trace different functions:
```javascript
Interceptor.attach(Module.findExportByName(null, 'function1'), { ... });
Interceptor.attach(Module.findExportByName(null, 'function2'), { ... });
```

Hook syscalls (Linux/Android):
```javascript
const libc = Module.findExportByName(null, 'libc.so.6');
Interceptor.attach(libc, { ... });
```

Modify behavior on the fly (change a return value):
```javascript
onLeave(retval) {
  return new NativePointer(0); // override retval
}
```

### Troubleshooting

- **"Frida not installed"**: `pip install frida` or download from https://frida.re.
- **"Failed to attach"**: Ensure the process is running and you have permission (may need sudo on some systems).
- **"Function not found"**: The target function may be stripped from symbols. Try `Module.getExportByName()` on libname if it's in a loaded library, or search by offset if you know the address.

---

## Hex Tools

### Quick Byte Inspection

```bash
hexdump -C <binary> | head -50
xxd <binary> | head -50
```

### ImHex (Interactive)

GUI hex editor with grammar-based parsers for binary formats:
1. Open binary in ImHex.
2. Load a `.pat` grammar (hundreds available in the ImHex repo).
3. Structure dissection updates live as you edit.

Not agent-automatable; use directly for interactive work.

---

## Common Workflows

### 1. Analyze a Stripped ELF

1. Get a high-level map with radare2:
   ```bash
   r2 -q -A -c 'afl; iz; ii' ./binary
   ```
2. Decompile interesting functions with Ghidra:
   ```bash
   python3 scripts/ghidra_report.py --binary ./binary --function 0x400000 --i-own-this-target
   ```
3. Confirm runtime behavior with Frida (trace calls, modify return values).

### 2. Vulnerability Research

1. Identify candidate functions (Ghidra decompilation, manual code review).
2. Trace the function at runtime (Frida), feed malicious input, observe crashes or unexpected behavior.
3. Develop exploit (outside this skill's scope), verify locally.

### 3. Malware Triage

1. Run `r2_static_report.sh` for a quick overview (functions, strings, imports).
2. Search for suspicious patterns (crypto libraries, network APIs, file I/O).
3. Use Ghidra to decompile suspicious functions.
4. Sandbox execution with Frida if runtime behavior is needed (system call tracing, file access interception).

### 4. Binary Format Reverse-Engineering

1. Use `hexdump` or ImHex for a byte-level view of a few examples.
2. Ghidra to decompile the parser code.
3. Frida to trace parsing functions with real input, record parsed structures.

---

## Notes

- **Project reuse**: Store Ghidra analysis projects in a cache directory (`~/.ghidra-cache`) to skip re-analysis on repeat invocations.
- **Performance**: For very large binaries (>100 MB), Ghidra analysis can be slow. Start with radare2 for a quick triage.
- **Architecture detection**: All tools auto-detect architecture; if detection fails, specify explicitly (tool-dependent).
- **Symbol stripping**: Stripped binaries lose function names but retain structure. radare2 and Ghidra auto-analysis still find functions via CFG heuristics.
