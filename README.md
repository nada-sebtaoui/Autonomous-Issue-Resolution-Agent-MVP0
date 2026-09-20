# AI GitHub Issue Resolution Agent — MVP

An agent that takes a GitHub issue, explores the target repository, proposes
a code fix with an LLM, and runs the test suite to check whether the fix
actually works.

This is the **Level 1 (MVP)** slice of a larger roadmap — see [Roadmap](#roadmap) below.

## Architecture

```
GitHub Issue
     │
     ▼
GitHubClient.fetch_issue()   ──► title, body, labels
     │
     ▼
GitHubClient.clone_repo()    ──► local checkout
     │
     ▼
RepoExplorer.find_relevant_files()
     │   (keyword-overlap scoring over file paths + contents)
     ▼
Candidate files (top-k, ranked)
     │
     ▼
LLMPlanner.propose_fix()     ──► Groq (OpenAI-compatible API)
     │   reasons over issue + candidate files
     ▼
Proposed fix (target file + explanation + new content)
     │
     ▼
TestRunner.run()             ──► pytest
     │
     ├── PASS ──► done
     └── FAIL ──► (Level 2 adds a debug/retry loop here)
```

## Project layout

```
ai-issue-agent/
├── README.md
├── requirements.txt
├── .env.example
├── main.py                  # CLI entrypoint
├── src/
│   ├── config.py             # env var loading
│   ├── github_client.py      # GitHub API + git clone
│   ├── repo_explorer.py      # keyword-based file relevance search
│   ├── llm_planner.py        # LLM reasoning -> proposed fix (JSON)
│   ├── test_runner.py        # runs pytest, reports pass/fail
│   └── agent.py               # orchestrates the pipeline above
└── tests/
    └── test_agent.py         # unit tests (no network/API key required)
```

## Setup

```bash
git clone <this-repo>
cd ai-issue-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in GITHUB_TOKEN and GROQ_* values
```

`.env` controls the Groq client:

- `GROQ_API_KEY` — Groq API key
- `GROQ_BASE_URL` — OpenAI-compatible endpoint (`https://api.groq.com/openai/v1`)
- `GROQ_MODEL_A` — primary planner model
- `GROQ_MODEL_B` — fallback if the primary call or JSON parse fails
- `GROQ_SKIP_TEMPERATURE` — comma-separated model ids that reject `temperature` (e.g. `groq/compound`)

## Usage

```bash
# Dry run: fetch issue, find candidate files, get a proposed fix (no writes)
python main.py --repo octocat/Hello-World --issue 17

# Apply the fix to the local checkout and run tests
python main.py --repo octocat/Hello-World --issue 17 --apply
```

Example output:

```
=== Issue ===
#17: Login returns 500 when email is missing

=== Candidate files (5) ===
  score=274  src/auth/controller.py
  score=118  tests/test_auth.py
  ...

=== Proposed fix ===
{
  "target_file": "src/auth/controller.py",
  "explanation": "login() dereferences `email` before checking it's present..."
}

=== Tests: PASS ===
```

## Running the test suite

```bash
python -m pytest -v
```

The unit tests cover `RepoExplorer` (relevance ranking, ignoring vendored
directories) and `Config` (env var validation) without needing an API key
or network access, so they run in CI cleanly.

## Design decisions

- **Keyword scoring instead of embeddings for repo search.** For an MVP,
  TF-style keyword overlap over file paths + contents is enough to
  demonstrate the pipeline end-to-end and is trivial to reason about /
  debug. Swapping in embeddings (Level 3) is a drop-in replacement for
  `RepoExplorer.find_relevant_files` — nothing else in the pipeline needs
  to change.
- **Single-file, full-content fixes instead of diffs.** Full file
  replacement is simpler to implement and verify than diff/patch
  generation, at the cost of not scaling to multi-file changes. Level 2
  upgrades this to unified diffs so `git diff` and PR generation work
  cleanly on larger changes.
- **Shallow clone + local pytest instead of a sandboxed container.**
  Keeps the MVP runnable with nothing but git + pytest installed. Level 2
  moves test execution into an isolated Docker container so untrusted
  LLM-generated code never runs directly on the host.
- **JSON-only LLM output.** The planner prompt forces a strict JSON
  response so the rest of the pipeline can consume it programmatically
  without parsing markdown or free text.

## Roadmap

| Level | Adds |
|---|---|
| 🟢 1 — MVP (this repo) | issue ingestion, repo exploration, code retrieval, LLM reasoning, proposed fix, basic tests |
| 🟡 2 — Recruiter-ready | real code modification via diffs, Docker-isolated test execution, retry/debug loop, git branch + diff, PR generation, logging |
| 🔴 3 — Advanced | RAG/embeddings over large repos, multi-agent planning, long-term memory, security sandbox, model routing, evaluation benchmark, CI/CD, cloud deployment |

## Evaluation (planned for Level 2)

Once the debug/retry loop and PR generation land, this will be measured
against a fixed set of ~30 controlled GitHub issues, tracking: correct
file identified, fix generated, tests passed, successful PR rate, average
iterations, and average latency.
