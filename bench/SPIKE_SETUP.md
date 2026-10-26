# Local Coding Spike Setup Guide

This guide prepares the Mac Mini for running the local coding spike measurement.

## Prerequisites

All code modules are complete and tested. This setup ensures the environment is ready.

### Step 1: Install opencode

The `opencode` CLI is required to interact with local Ollama models. Install from the Anthropic SDK examples:

```bash
# Clone the Anthropic SDK and install opencode from examples
git clone https://github.com/anthropics/anthropic-sdk-python.git
cd anthropic-sdk-python/examples/code_editor
pip install -e .

# Verify installation
opencode --help
```

Alternatively, if you have the SDK already, install just the example:
```bash
pip install -e anthropic-sdk-python/examples/code_editor
```

If the help output doesn't appear, check that the install location is in your PATH:
```bash
which opencode
```

### Step 2: Pull Ollama models

The spike uses two models for benchmarking. Ensure both are pulled:

```bash
# Start Ollama server (if not already running)
ollama serve &

# In another terminal, pull the models
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b

# Verify they're available
curl http://localhost:11434/api/tags | grep qwen2.5
```

If you already ran spike #563, these models are likely cached.

### Step 3: Configure passwordless sudo for powermetrics

Energy measurement requires `powermetrics` with root privileges. Configure passwordless sudo:

```bash
# Add a sudoers rule for passwordless powermetrics execution
echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/powermetrics" | sudo tee /etc/sudoers.d/powermetrics

# Verify it works
sudo -n powermetrics -n 1 --samplers cpu_power,gpu_power
# (Should output power samples without prompting for password)
```

If you see "Sorry, try again," the rule isn't applied correctly. Check:
```bash
cat /etc/sudoers.d/powermetrics
sudo -n -v  # Test passwordless sudo
```

## Running the Spike

Once setup is complete, run the spike from the repo root:

```bash
cd ~/.agents  # (or wherever the repo is)
python3 bench/local_coding_spike.py
```

### What happens:

1. **Preflight checks** — Verifies Ollama, opencode, and sudo are available
2. **Ticket selection** — Queries GitHub for 5 recent small PRs with conventional commits
3. **Measurements** — 5 tickets × 2 models = 10 runs:
   - Creates a historical git worktree at each PR's base commit
   - Runs `opencode` against local Ollama
   - Runs the real gate sequence (build_type_measure + metrics + test_change + code_review)
   - Measures wall time and energy (if sudo available)
   - Saves results to `bench/results/local-coding-spike-<timestamp>.json`
4. **Results** — Appends a summary to `bench/RESULTS.md`

### Output files:

- `bench/results/local-coding-spike-<timestamp>.json` — Raw run data
- `bench/RESULTS.md` — Updated with "## Run 31" section

## Troubleshooting

### "Ollama server not responding"
- Start Ollama: `ollama serve`
- Verify: `curl http://localhost:11434/api/tags`

### "Model 'qwen2.5:7b' not found"
- Pull it: `ollama pull qwen2.5:7b`
- Check: `ollama list`

### "opencode not found in PATH"
- Install: `pip install anthropic`
- Add to PATH: `export PATH="$HOME/.local/bin:$PATH"`
- Verify: `which opencode`

### "sudo: a password is required"
- Re-run sudo setup from Step 3
- Test: `sudo -n powermetrics --help` (should not prompt)

### "git worktree add failed"
- Ensure base_sha is present locally: `git fetch origin <sha>`
- Verify git is at repo root: `pwd` and `git status`

## Notes

- Each run takes ~1–2 minutes per ticket (opencode inference time varies)
- Energy measurement is optional; if sudo isn't available, energy_j will be `null` with a reason
- Real PRs are read-only; no labels, comments, or state are changed
- Worktrees are cleaned up automatically after each run
- Results are appended to RESULTS.md (no partial writes if interrupted)
