Here are my project notes (my saved learnings from earlier bench runs), pasted in full:

<notes>
- [config] Project 'marvin-bench' uses stack: python
  outcome: 
- [pattern] Project 'marvin-bench' imports these third-party modules: __future__, score
  outcome: 
- [failed] [BUG] in 'marvin-bench/tasks/task-001-bugfix/files/stats.py' line 2: mutates caller's list
  outcome: 
- [failed] [BUG] in 'marvin-bench/tasks/task-001-bugfix/files/stats.py' line 4: wrong for even-length lists
  outcome: 
- [worked] lean profile (13-line CLAUDE.md, TDD/grill defaults only) saves 9-10% tokens on coding vs marvin profile, with ZERO recall regression vs clean. Routing rule: use claude-lean for mechanical coding, claude for recall/research/architecture.
  outcome: 9-10% cost saving on coding sessions; zero recall regression confirmed in Run 3
- [worked] Efficiency-when-correct metric: all profiles eventually reach correct answer on navigational QA tasks, but MARVIN used 2 tool calls vs clean's 6 and 52% fewer tokens (45,905 vs 95,682). Memory reduces navigation cost even when binary correctness is identical.
  outcome: 52% token reduction on navigational QA; discovered as new metric beyond binary correct/incorrect
- [failed] Caveman mode anti-correlated: output tokens clean=176, marvin=215 on task-004. More verbose than base despite being designed to reduce verbosity. Anti-correlated with the north-star goal. Dropped from lean profile; opt-in only.
  outcome: removed anti-feature; lean profile now only carries TDD/grill defaults
- [failed] Claude Code 2.x keychain poisoning bug: failed auth writes blank path-specific keychain entry at service name 'Claude Code-credentials-<sha256[:8] of config dir abs path>'. Blank entry permanently blocks .credentials.json reads for that path. Fix: security delete-generic-password -s <service>. Added purge_blank_entry() to setup.sh.
  outcome: fixed bench auth failures; setup.sh now idempotent against this bug
- [anti-pattern] Grading string specificity trap: substring grading must match ALL valid correct solutions, not just one approach. 'strptime' missed datetime.date() and fromisoformat(). 'return None' missed next(..., None) sentinel. 'datetime.date' covers both; ', None)' covers both sentinel and explicit return.
  outcome: fixed false 0.50 scores in Run 4; all profiles actually solved tasks correctly
- [pattern] QA task discriminator design: tasks where the answer is in a readable file are NOT memory discriminators — all profiles can read files. True discriminators need either (a) answer only in ChromaDB/session history, or (b) file access restricted for clean/lean profiles.
  outcome: redesigned task-007; identified need for isolated-memory QA task type
- [pattern] ChromaDB cosine distance is in the range 0-2 (0=identical, 2=opposite), NOT 0-1 like cosine similarity. Threshold of 1.1 is a valid mid-range filter. LLM judges frequently confuse distance with similarity and reject correct answers.
  outcome: Similarity conversion: sim = 1.0 - dist/2.0. Use substring score as ground truth when judge fails on numeric thresholds.
- [pattern] Full context injection (15 memory files, ~4000 tokens) fails for jargon-recall tasks with local LLMs. Model's training priors override project-specific terms when noise is high. RAG injection (~300 tokens, top-3 semantic hits) fixes this by eliminating competing context.
  outcome: 14B + RAG achieves semantic parity at $0.00. Context quality matters more than model size for jargon retrieval.
- [pattern] RAG context injection: the #1 semantic hit for the MARVIN venv question is marvin-venv-interpreter.md at similarity 0.86. Full injection floods the model with 14 other files (Python stdlib docs, file-org notes, etc.) that activate stronger training priors than the project-specific note.
  outcome: Use n_results=3 for RAG injection; more than 3 reintroduces noise.
- [config] 70B models require ~40 GB RAM for Q4 quantization. Not feasible on 16 GB MacBook. qwen2.5:14b (9 GB) is the largest practical local model for this hardware.
  outcome: Use qwen2.5:14b as the ceiling for local zero-cost runs on 16 GB machines.
- [worked] qwen2.5:14b + RAG injection achieves semantic parity with Haiku on jargon-recall tasks at $0.00 cost. Judge passes; substring scorer fails because the model adds one extra word ('tag-keyword matching' vs 'tag matching'). Model size threshold: 7B + RAG still fails, 14B + RAG passes judge.
  outcome: Proven cost hierarchy: local 14B+RAG ($0.00 semantic) -> Haiku+marvin (~$0.02 exact) -> Sonnet+marvin (~$0.05 full).
- [pattern] MARVIN's advantage GROWS on weaker models (Haiku). task-007 clean FAILS on Haiku (0 tool calls, no search) where it passed slowly on Sonnet. MARVIN provides the context that prevents Haiku from taking shortcuts.
  outcome: Route recall + research tasks to marvin+haiku, not clean+haiku. Clean profile fails on Haiku for tasks requiring memory.
- [pattern] CLAUDE_CONFIG_DIR env var switches Claude Code profiles. Set to a dir with a CLAUDE.md to activate that profile. Clean profile = no CLAUDE.md dir at all (or empty dir). Used by marvin-bench to isolate profiles without touching ~/.claude.
  outcome: Bench profiles: ~/.agents/bench/profiles/clean|lean|marvin
- [pattern] Substring grading (v0) passes any output containing the expected phrase, even if the reasoning is wrong. LLM judge grading (v1) catches plausible-wrong answers but fails on valid paraphrases. Both are needed: substr = exact signal, judge = semantic signal.
  outcome: Run both; trust substr for exact-phrase tasks, judge for semantic tasks.
</notes>

Using these notes, answer the following questions about what the bench runs proved about local model context injection.

1. What did bench runs establish about using full context injection (all
   memory files) vs RAG injection (top-N targeted passages) with local LLMs?
2. Which model size was the minimum to achieve semantic parity with Haiku,
   and what injection method was required?
3. What does the stored outcome say about context quality vs model size?

Report each answer concisely.
