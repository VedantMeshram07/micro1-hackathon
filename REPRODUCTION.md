# Reproduction Guide — Repo Due-Diligence Agent

This guide provides step-by-step instructions to set up, test, evaluate, and run the Repo Due-Diligence Agent locally or in a hosted environment.

---

## 📋 System Requirements & Dependencies

- **Operating System**: Windows, macOS, or Linux
- **Python**: Version 3.10+ (tested on Python 3.12)
- **Node.js / npm**: Version 18+ (required for Node.js repository build/test execution)
- **Git**: Installed and accessible on PATH

---

## ⚙️ Environment Setup

1. **Clone or navigate to repository**:
   ```bash
   cd D:\repo-audit-scaffold
   ```

2. **Create and activate virtual environment**:
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure `.env`**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

   Configure your preferred LLM provider in `.env`:
   ```env
   LLM_PROVIDER=groq
   GROQ_API_KEY=your_groq_api_key_here
   GROQ_MODEL=openai/gpt-oss-120b,openai/gpt-oss-20b
   
   # Optional: GitHub token to increase API rate limits for PR/issue mining
   GITHUB_TOKEN=your_github_token_here
   
   # Demo safety switch
   ENABLE_LIVE_INGEST=False
   ```

---

## 🧪 Running Offline Verification (Zero API Quota Used)

To verify all components (ingestion, Windows command execution via `shutil.which`, dependency checking, trajectory logging, reasoning trace stripping, and model pool failover) without burning API quotas:

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

## 📊 Running Live Evaluation & Benchmarking

To run both the baseline surface skim and full agent audit across all 6 pinned repositories in `repos_manifest.yaml` and compute Spearman correlation against `eval/ground_truth.yaml`:

```bash
python -m eval.run_eval
```

### Expected Output
- Audits are cached in `data/reports/<repo_id>__baseline.json` and `data/reports/<repo_id>__agent.json`.
- Per-run execution trajectories are incrementally written to `trajectories/<repo_id>.jsonl`.
- Final rank-correlation table output:
  ```
  === Results ===
  Baseline correlation with your ranking: 0.841
  Agent correlation with your ranking:    0.886
  Improvement: +0.045
  ```

To force a fresh re-audit of all repos, clear cached reports:
```bash
# Windows PowerShell:
Remove-Item -Recurse -Force data\reports\*, trajectories\*
```

---

## 🌐 Running the Streamlit Report Browser

Launch the web app interface:

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

- **Tab 1: Browse eval-set reports**: Inspect side-by-side baseline vs agent audits for all pre-audited repositories.
- **Tab 2: Analyze a new repo**: Live ingest & audit for arbitrary GitHub URLs or `.zip` uploads (gated behind `ENABLE_LIVE_INGEST=True` in `.env`).

---

## 🔒 Security & Live Ingest Sandbox Note

- When `ENABLE_LIVE_INGEST=True`, the agent clones and executes code from arbitrary repositories.
- Subprocess build & test calls run with a sandboxed timeout (`BUILD_TIMEOUT_SEC = 120`).
- **Recommendation**: Keep `ENABLE_LIVE_INGEST=False` when deploying `app.py` on public internet endpoints (e.g. Streamlit Community Cloud). Only enable live ingest for local/isolated runs.
