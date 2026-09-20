# Autonomous GitHub Issue Resolution Agent

> An AI software-engineering agent that reads a GitHub issue, retrieves relevant code
> using hybrid lexical + semantic search, produces a structured implementation plan,
> generates a safe unified diff, validates and executes it inside a Docker sandbox,
> and reports verified test results — all from a single CLI command.

---

## What Problem Does This Solve?

Fixing bugs requires three things a model is good at: **reading context**, **reasoning about code**, and **generating targeted changes**. What makes it hard is everything around that: finding the right files in a large repo, ensuring the generated change is safe to apply, running the tests without polluting the host machine, and feeding test failures back for correction.

This project builds a complete, end-to-end pipeline for that workflow. Each stage is modular and independently testable, and the system degrades gracefully when optional components (Docker) are unavailable.

---

## Live Demo

```bash
python main.py \
  --repo eventsesame-lgtm/ai-agent-test \
  --issue 1 \
  --apply \
  --docker
```

**Real output:**

```
=== Issue ===
#1: Fix multiplication function

=== Candidate files (4) ===
  score=0.251  calculator.py
    symbol matches "multiply"; content matches "return"; lexical=0.21, semantic=0.33

=== Implementation plan ===
{
  "summary": "multiply function returns sum instead of product",
  "root_cause": "Implementation mistakenly uses addition operator instead of multiplication",
  "files_to_modify": [{"path": "calculator.py", "reason": "multiply is defined here"}],
  "implementation_steps": ["locate multiply", "change return a + b to return a * b"],
  "tests_to_run": ["pytest tests/test_calculator.py"]
}

=== Proposed patch ===
diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -9,1 +9,1 @@
-    return a + b
+    return a * b

=== Docker sandbox: SUCCESS ===
Patch applied inside sandbox: True
Duration: 49.51s
Sandbox cleaned up: True

=== Tests: PASS ===
3 passed in 0.18s
```

---

## Architecture

```
GitHub Issue
     │
     ▼
GitHubClient ──────────────── GitHub REST API + shallow git clone
     │
     ▼
CodeRetriever ─────────────── Hybrid retrieval
     │   ┌──────────────────────────────────┐
     │   │ Lexical: keyword/path/symbol     │
     │   │ Semantic: token-vector cosine    │
     │   │ Hybrid:  alpha·lex + beta·sem    │
     │   └──────────────────────────────────┘
     │
     ▼
LLMPlanner.plan_fix() ──────── Structured investigation plan
     │   problem · root_cause · files_to_modify · risks
     │
     ▼
LLMPlanner.propose_fix() ───── Unified diff patch
     │   uses the plan as input context
     │
     ▼
PatchManager ───────────────── Validation
     │   path-traversal check · git apply --check
     │   hunk normalization · whitespace tolerance
     │
     ▼
DockerSandbox ──────────────── Isolated test execution
     │   temp copy → mount → apply patch → install deps → pytest
     │   timeout · resource limits · cleanup
     │
     ▼
Result ─────────────────────── exit_code · stdout · stderr · duration
```

---

## AI / Engineering Techniques

| Technique | Where |
|---|---|
| LLM structured generation (JSON) | `LLMPlanner` — forces strict JSON output so the pipeline never parses free text |
| Two-stage LLM pipeline | `plan_fix()` investigates, `propose_fix()` generates — separating reasoning from code output |
| Hybrid lexical + semantic retrieval | `CodeRetriever` — cosine similarity on token vectors combined with keyword/symbol matching |
| Symbol-aware chunking | `CodeRetriever` — splits by `def`/`class` to preserve function boundaries in LLM context |
| Configurable retrieval modes | `keyword`, `semantic`, `hybrid` — weights adjustable via env vars |
| Safe patch application | `PatchManager` — validates target paths, rejects traversal, normalizes hunk counts |
| LLM output format validation | Rejects Cursor-format patches, non-standard diffs, missing fields, invalid types |
| Docker sandbox isolation | `DockerSandbox` — patch applied only inside a container-mounted temp copy; host repo untouched |
| Resource-limited execution | Configurable memory, CPU, network, timeout per run |
| Fallback model routing | `GROQ_MODEL_A` primary → `GROQ_MODEL_B` fallback on API error or JSON parse failure |
| 24/24 unit tests, no external API calls required | All mocked; Docker tests use `monkeypatch` |

---

## Project Structure

```
ai-issue-agent/
├── main.py                  # CLI — --repo --issue --apply --docker
├── src/
│   ├── config.py            # env var loading and validation
│   ├── github_client.py     # GitHub REST API + git clone
│   ├── repo_explorer.py     # keyword baseline (preserved for comparison)
│   ├── retrieval.py         # hybrid lexical + semantic retrieval
│   ├── llm_planner.py       # planning + patch generation, LLM abstraction
│   ├── patcher.py           # patch validation, normalization, application
│   ├── docker_sandbox.py    # Docker-based sandboxed execution
│   ├── test_runner.py       # host-based pytest runner (--no-docker fallback)
│   └── agent.py             # orchestrates the full pipeline
└── tests/
    ├── test_agent.py        # retrieval + config tests
    ├── test_patcher.py      # patch validation + LLM output validation
    ├── test_retrieval.py    # hybrid retrieval ranking tests
    └── test_docker_sandbox.py  # sandbox mocked unit tests
```

---

## Setup

```bash
git clone <this-repo>
cd ai-issue-agent
python -m venv .venv && .venv\Scripts\activate   # Windows
# source .venv/bin/activate                        # Linux/macOS
pip install -r requirements.txt
cp .env.example .env
# Fill in GITHUB_TOKEN and GROQ_API_KEY
```

**Requirements:** Python 3.11+, Docker (for `--docker`), a [Groq API key](https://console.groq.com) (free tier works).

---

## Configuration

All credentials and settings live in `.env`. No hard-coded values.

```env
# GitHub
GITHUB_TOKEN=ghp_...

# Groq (OpenAI-compatible)
GROQ_API_KEY=gsk_...
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL_A=openai/gpt-oss-120b     # primary
GROQ_MODEL_B=groq/compound           # fallback

# Retrieval weights (hybrid = alpha·lexical + beta·semantic)
RETRIEVAL_MODE=hybrid
RETRIEVAL_LEXICAL_WEIGHT=0.65
RETRIEVAL_SEMANTIC_WEIGHT=0.35
RETRIEVAL_TOP_K=8

# Docker sandbox
DOCKER_IMAGE=python:3.11-slim
DOCKER_TIMEOUT=120
DOCKER_TEST_COMMAND=python -m pytest -q
DOCKER_MEMORY=512m
DOCKER_CPUS=1.0
DOCKER_NETWORK_DISABLED=false
```

---

## Usage

```bash
# Dry run — fetch issue, retrieve code, produce plan + patch (no writes)
python main.py --repo owner/repo --issue 17

# Apply patch to local checkout and run tests on host
python main.py --repo owner/repo --issue 17 --apply

# Apply patch and run tests inside Docker sandbox (recommended)
python main.py --repo owner/repo --issue 17 --apply --docker
```

---

## Tests

```bash
python -m pytest -v
```

```
24 passed in 1.17s
```

All tests run without Docker, a GitHub token, or a Groq API key. Docker-specific tests use `monkeypatch` to mock `subprocess.run`.

---

## Sandbox Isolation

When `--docker` is used:

1. The cloned repository is **copied** into a temporary directory on the host.
2. That copy is **volume-mounted** into a fresh Docker container.
3. The patch is **applied inside the container** by a Python helper script.
4. Tests run inside Docker. The container is removed when finished.
5. The **original cloned repository on the host is never modified**.

This means LLM-generated code executes inside Docker, not directly on the host machine.

---

## Design Decisions

**Why two LLM calls (plan then patch)?**
Separating investigation from code generation produces higher-quality patches. The first call (`plan_fix`) reasons about root cause and which files to touch. The second call (`propose_fix`) receives that plan as context and focuses purely on writing a correct diff.

**Why hybrid retrieval over embeddings-only?**
Lexical search catches exact identifiers and function names that embedding models can miss. Semantic search catches conceptually related code. Combining them with configurable weights gives better coverage than either alone without requiring an external vector database.

**Why unified diffs instead of full-file rewrites?**
A diff is reviewable, auditable, and safe to apply. A full-file rewrite silently discards unrelated changes and makes code review meaningless. `PatchManager` validates the diff structure, normalizes malformed hunk counts from the LLM, and runs `git apply --check` before touching any file.

**Why Docker?**
LLM-generated code should not run directly on the developer's machine. Docker provides a disposable, resource-limited environment with no access to the host filesystem beyond the mounted sandbox copy.

---

## Limitations

- Single-file patches only (multi-file diffs planned for next stage).
- Python projects only (test runner assumes `pytest`).
- No retry loop yet — test failures are reported but not fed back to the LLM for correction.
- No git branch/commit/PR workflow yet.
- Semantic retrieval uses local token-vector cosine similarity, not a heavyweight embedding model. It is fast and requires no external service, but may miss distant semantic relationships.
- Docker image pull adds ~30–60s on the first run.

---

## Roadmap

| Stage | Status | Description |
|---|---|---|
| Hybrid retrieval | ✅ Done | lexical + semantic + symbol-aware chunking |
| Explicit planning | ✅ Done | structured plan before patch generation |
| Patch generation | ✅ Done | unified diff with validation and normalization |
| Docker sandbox | ✅ Done | isolated execution, resource limits, cleanup |
| Retry / debug loop | 🔲 Next | feed test failures back to LLM, max 3 attempts |
| Git branch + commit | 🔲 Next | `agent/fix-issue-N` branch, meaningful commit |
| Pull request | 🔲 Next | optional `--create-pr` with structured description |
| Evaluation benchmark | 🔲 Planned | 10–20 real issues, retrieval + patch + test metrics |
| Structured observability | 🔲 Planned | run IDs, stage timing, structured logs |
