# Repo Due-Diligence Agent

Evidence-based codebase quality assessment: pick an unfamiliar repo, get a
scored report where every claim ties back to something actually checked —
not a vibe.

Built for the micro1 Agentic Workflows Hackathon 2026.

## Pipeline

```
ingest → baseline (surface-level) + agent (deep evidence-gathering) → report
```

- **`ingest/`** — normalizes a GitHub URL, `.zip`, or local folder into a
  checkout + language detection + file tree + README
- **`baseline/`** — one prompt, README + file tree only, no test execution.
  This is the "two-minute skim" a person does today.
- **`agent/`** — runs build/tests, checks dependency pinning and Docker
  presence, samples and LLM-reviews representative source files, mines
  GitHub PR/issue activity, then synthesizes everything into one
  evidence-linked report. Every step is logged to `trajectories/`.
- **`report/`** — saves/renders the structured reports
- **`eval/`** — runs baseline + agent over a fixed, pinned repo set and
  compares each one's scores against your own ground-truth ranking
- **`app.py`** — Streamlit hosted browser for the reports

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, optionally GITHUB_TOKEN
```

## Running the eval

1. Fill in `repos_manifest.yaml` with 6-8 real GitHub repos + pinned commits
2. **Review each repo yourself first, blind**, and fill in `eval/ground_truth.yaml`
   with your own quality ranking (1 = best) — this is your ground truth
3. Run:
   ```bash
   python -m eval.run_eval
   ```
   This runs baseline + agent on each repo (cached after first run — delete
   `data/reports/*.json` to force a re-run) and prints the rank-correlation
   comparison table.

## Running the hosted demo

```bash
streamlit run app.py
```

By default this only browses precomputed reports from the eval set — fast
and never fails live. A gated "Analyze a new repo" tab exists for live
ingest of arbitrary repos, off by default (`ENABLE_LIVE_INGEST=False` in
`.env`). See "Security note" below before turning it on anywhere public.

## Security note

Once this accepts arbitrary GitHub URLs or zip uploads, it's cloning and
running code from strangers — this is a genuinely different risk profile
than the fixed eval set. Keep `ENABLE_LIVE_INGEST=False` on any public
deployment; run that mode locally only, per this reproduction guide, not
on an open internet-facing URL. Every subprocess call already runs with a
timeout, but timeout alone isn't a full sandbox (no filesystem/network
isolation yet) — that's an explicit, disclosed limitation, not an oversight.

## Coding-agent disclosure

This scaffold was built with [Claude](https://claude.ai) as a coding agent
via chat + code execution. [Fill in: any additional coding agents used to
extend/iterate on this — Claude Code, Cursor, etc. — and note where their
trajectory logs / session exports live for submission.]

## Still to fill in before submission

- [ ] Pick and pin the 6-8 eval-set repos, including one "looks good, isn't" case
- [ ] Fill in `eval/ground_truth.yaml` with your blind ranking
- [ ] Run `eval/run_eval.py`, confirm agent correlation beats baseline
- [ ] Write the Improvement Changelog (see hackathon brief for the format)
- [ ] Deploy `app.py` (Streamlit Community Cloud is the fastest path)
- [ ] Record the 5-minute solution video
- [ ] Write the reproduction guide with exact versions + runtime/cost
- [ ] Package `trajectories/*.jsonl` for submission
- [ ] Write the "hot take" — the strongest real failure mode you hit and what it taught you
