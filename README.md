# Repo Due-Diligence Agent — micro1 Hackathon 2026

An evidence-based codebase due-diligence agent that produces scored, auditable quality reports for software repositories. Every claim in the agent's report is backed by real execution output, dependency analysis, Docker presence, sampled LLM code reviews, and GitHub activity mining — benchmarked directly against a surface-level single-prompt baseline.

---

## 🎯 Intended User & Bottleneck

- **Intended User**: Technical buyers, VC due-diligence analysts, software architects, and engineering managers evaluating third-party or open-source codebases.
- **The Bottleneck**: Auditing an unfamiliar repository manually takes 1–3 hours. Engineers must clone the repository, attempt local build and test execution, check dependency lockfiles, inspect core source code for architectural anti-patterns, and review commit/PR activity.
- **Why Baselines Fail**: Single-prompt surface skims (reading only the README and file tree) frequently fall for well-formatted documentation while missing broken test suites, unpinned dependencies, or unhandled runtime exceptions.

---

## 🏗️ Architecture & Pipeline Flow

```
                               ┌─────────────────────────────────────────┐
                               │             Input Source                │
                               │   (GitHub URL / .zip / Local path)      │
                               └────────────────────┬────────────────────┘
                                                    │
                                                    ▼
                               ┌─────────────────────────────────────────┐
                               │           ingest/ingest.py              │
                               │ (Windows-safe git, tree, language detection)
                               └──────────┬──────────────────┬───────────┘
                                          │                  │
                ┌─────────────────────────┘                  └─────────────────────────┐
                ▼                                                                      ▼
  ┌──────────────────────────┐                                           ┌──────────────────────────┐
  │   baseline/rate_repo.py  │                                           │   agent/audit_repo.py    │
  │ (Surface skim, 1 prompt) │                                           │ (Deep Evidence Gathering)│
  └─────────────┬────────────┘                                           └─────────────┬────────────┘
                │                                                                      │
                │                               ┌──────────────────────────────────────┼──────────────────────────────────────┐
                │                               │                                      │                                      │
                │                               ▼                                      ▼                                      ▼
                │                  ┌──────────────────────────┐           ┌──────────────────────────┐           ┌──────────────────────────┐
                │                  │  _run_build_and_tests    │           │   _check_dependencies    │           │   _sample_code_review    │
                │                  │ (pytest / npm test run)  │           │(PEP 621, Poetry, npm pins│           │(5 core files LLM review) │
                │                  └────────────┬─────────────┘           └────────────┬─────────────┘           └────────────┬─────────────┘
                │                               │                                      │                                      │
                │                               └──────────────────────────────────────┼──────────────────────────────────────┘
                │                                                                      │
                │                                                                      ▼
                │                                                        ┌──────────────────────────┐
                │                                                        │   _synthesize_report     │
                │                                                        │  (Rubric anchored JSON)  │
                │                                                        └─────────────┬────────────┘
                │                                                                      │
                ▼                                                                      ▼
  ┌──────────────────────────┐                                           ┌──────────────────────────┐
  │ baseline__<repo_id>.json │                                           │   agent__<repo_id>.json  │
  └──────────────────────────┘                                           └─────────────┬────────────┘
                                                                                       │
                                                                                       ▼
                                                                         ┌──────────────────────────┐
                                                                         │ trajectories/<id>.jsonl  │
                                                                         └──────────────────────────┘
```

### Core Components
1. **`ingest/ingest.py`**: Handles GitHub clone, local folder, or zip unpacking. Solves Windows git edge cases (read-only pack files, credential prompt hangs, shallow commit fetches).
2. **`baseline/rate_repo.py`**: Executes a 2-minute surface skim (README + file tree preview) to establish a benchmark baseline score.
3. **`agent/audit_repo.py`**:
   - Sandboxed build/test execution (`pip` + `pytest`, `npm install` + `npm test`).
   - Dependency freshness audit (`requirements.txt`, `package.json`, `pyproject.toml` PEP 621/Poetry).
   - Docker containerization check (`Dockerfile`, `docker-compose.yml`).
   - Sampled source file code review (up to 5 core logic files reviewed for readability, error handling, and risks).
   - GitHub activity mining (open issues and recent merged PR count via GitHub REST API).
   - Rubric-anchored synthesis into an evidence-linked JSON report.
4. **`llm/client.py`**:
   - Unified multi-provider LLM client (`groq`, `openrouter`, `anthropic`, `gemini`, `mock`).
   - **Model Pooling**: Automatically advances to subsequent models when daily quota or token limits are exhausted.
   - **Reasoning Trace & Structured JSON Handling**: Strips `<think>...</think>` tags and preamble text.
   - **Automatic Failover (`complete_json`)**: If a model returns output cut off mid-reasoning without valid JSON, automatically switches to the next pooled model.
5. **`agent/trajectory_logger.py`**: Writes JSONL log entries per run capturing steps, inputs, outputs, decisions, and active model names (`trajectories/*.jsonl`).
6. **`app.py`**: Hosted Streamlit report browser for inspecting side-by-side baseline vs agent audits.

---

# Improvement Changelog

Real entries from tonight's actual build — including the parts that went
wrong, since those are the most concrete evidence of iteration.

| Stage | What we tried and why | Evidence | Decision / Learning |
|---|---|---|---|
| **Baseline** | Single prompt, README + file tree only, no execution | Baseline correlation with our own blind expert ranking of the 6-repo eval set: **0.971** — already strong, because a careful gut-check from a capable model isn't nothing | Established the number the agent needed to beat |
| **v1 — Evidence pipeline** | Added real build/test execution (pytest/npm), dependency-manifest parsing, Docker presence check, sampled per-file LLM code review, GitHub PR/issue mining | Uncovered concrete, evidence-linked findings baseline couldn't see — e.g. `repo_1`'s array-bounds risk in `hamiltonianCycleGrid`, `repo_2`'s undefined functions causing `NameError`s | Real execution evidence, not just a skim, is what separates a due-diligence tool from a summarizer |
| **v2 — Multi-provider free-tier attempts** | Tried Gemini free tier, Groq (`llama-3.3-70b-versatile`, later `gpt-oss-120b`/`gpt-oss-20b`/`qwen3.x`), OpenRouter (`nvidia/nemotron`) to keep this cost-free during development | Each hit a genuinely different failure: Gemini's daily cap was 20 requests/day on a preview model; `llama-3.3-70b-versatile` turned out deprecated; Nemotron and `qwen3.6-27b` both burned their entire token budget on visible `<think>` reasoning traces before ever producing JSON; even when working, the smaller free models clustered scores in a narrow 3-5 band regardless of actual repo quality (pydantic and a repo with undefined functions scored within 1 point of each other) | Free-tier LLM APIs are wildly heterogeneous in structured-output reliability — this is *why* the pipeline has provider-agnostic pooling with automatic model fallback as a core feature, not an afterthought |
| **v3 — Real bugs found and fixed along the way** | `_check_dependencies` never parsed `pyproject.toml`, so it falsely reported pydantic — our best-quality repo — as having *no* dependency manifest at all; Windows `npm` couldn't be invoked directly via `subprocess` (needed `shutil.which` resolution); `complete_json()`'s pool-advancement logic had an off-by-one that could walk past the end of the model list after a quota switch + a bad response occurred back-to-back | Each caught via direct inspection of a failing report's raw evidence, not assumption | Don't trust a clean-looking correlation number without checking the evidence underneath — the pipeline's own philosophy applied to itself |
| **v4 — Coding-agent-as-model pass** | Routed both baseline and agent scoring through Antigravity directly (file-based prompt queue: `llm_queue/pending/` → agent answers → `llm_queue/done/`) instead of an HTTP API, to validate pipeline logic without burning free-tier quota | Produced the strongest correlation of the night (0.971 agent vs 0.971 baseline) — but manual batch-processing across ~40 structurally-similar prompts introduced **two separate data-integrity failures**: identical boilerplate code-review text reused across different files in one pass, and a full synthesis report accidentally swapped between two unrelated repos (`repo_2`'s report initially contained `repo_3`'s CPU-scheduling content) in a second pass | An agent is not automatically trustworthy just because it's capable — verification has to check the *content* matches its own evidence, not just that a plausible number came back. Fixed both, then independently confirmed via `findstr` searches for repo-specific terms across all 6 saved reports, not by trusting the agent's own self-report |
| **Final** | Combined all of the above | Agent correlation: **0.971**, matching baseline numerically — but the two scores tell a different story underneath: baseline rated our deliberate "looks good, isn't" hard case (`repo_1`, ground-truth rank 4) a `7`, tying it with a genuinely better repo (`repo_6`, rank 3); the agent correctly separated them (`6` vs `7`) | The headline correlation number understates the real improvement — look at how the hard case specifically was handled, not just the aggregate |
---

## 🔥 Hot Take & Key Insights

1. **Unbounded Reasoning Traces Can Break JSON Synthesis**: Models like `qwen3.6-27b` often spend their entire `max_tokens` budget on `<think>...</think>` reasoning traces before generating any JSON output. Stripping tags after the call is insufficient when the JSON itself is truncated.
2. **Model Pool Failover is essential for Free-Tier APIs**: Rather than treating malformed LLM responses as pipeline failures, treating unparseable JSON as a pool failover trigger allows the pipeline to self-heal by falling back to well-behaved models like `openai/gpt-oss-120b`.
3. **Evidence Beats Gut Impressions**: Surface skims consistently assign high quality scores to repos with well-written READMEs, even when automated test suites fail completely or dependencies are entirely unpinned. Grounding scores in build/test execution output provides true due-diligence value.

---

## 🧪 Verification & Testing

Run the offline test suite (no API keys or network connection required):

```bash
python test_offline.py
```

Expected output:
```
[1/3] Testing parse_json_response edge cases...
  [OK] All 7 parse_json_response test cases passed.

[2/3] Testing complete_json automatic model pool failover & exhaustion...
  [OK] Model pool successfully advanced from bad-model-1 to mock-model-2 on unparseable output.
  [OK] Clean error raised when all models in pool are exhausted.

[3/3] Testing full agent audit pipeline offline against repos/JavaScript-Snake...
  [OK] Full agent audit pipeline completed offline cleanly! Trajectory logged to trajectories\test_snake_offline.jsonl

=== ALL OFFLINE TESTS PASSED SUCCESSFULLY ===
```

---

## 🚀 Quick Start & Reproduction

For step-by-step setup, environment variable instructions, live eval execution, and Streamlit app deployment, see [REPRODUCTION.md](file:///d:/repo-audit-scaffold/REPRODUCTION.md).
