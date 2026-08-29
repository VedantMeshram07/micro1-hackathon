"""
Headless demo: point this at any public GitHub repo and get a full
baseline-vs-agent due-diligence comparison printed to the terminal — the
same thing the Streamlit "Analyze a new repo" tab does, no UI required.

Usage:
    python demo.py https://github.com/some/repo.git
    python demo.py https://github.com/some/repo.git <pinned-commit-sha>
"""

import sys
from dotenv import load_dotenv
load_dotenv()

from ingest.ingest import ingest
from baseline.rate_repo import baseline_rate
from agent.audit_repo import audit_repo
from agent.trajectory_logger import TrajectoryLogger
from llm.client import LLMClient
from report.generate_report import render_markdown


def main():
    if len(sys.argv) < 2:
        print("Usage: python demo.py <github-url> [pinned-commit]")
        sys.exit(1)

    url = sys.argv[1]
    pinned_commit = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"\n{'='*60}")
    print(f"  Analyzing: {url}")
    print(f"{'='*60}\n")

    client = LLMClient()
    logger = TrajectoryLogger(run_id="demo")

    print("Cloning and detecting language/structure...")
    ir = ingest(url, pinned_commit=pinned_commit)
    print(f"  Languages detected: {ir.languages or 'none matched'}")
    print(f"  Files: {len(ir.file_tree)}\n")

    print("Running baseline (surface skim)...")
    baseline_report = baseline_rate("demo_repo", ir, client)

    print("Running full agent audit (build/test, deps, code review, activity)...")
    agent_report = audit_repo("demo_repo", ir, client, logger, github_url=url)

    print(f"\n{'='*60}")
    print("  BASELINE (surface-level skim)")
    print(f"{'='*60}")
    print(render_markdown(baseline_report))

    print(f"\n{'='*60}")
    print("  AGENT (evidence-based)")
    print(f"{'='*60}")
    print(render_markdown(agent_report))

    print(f"\nDone. Trajectory logged to trajectories/demo.jsonl")


if __name__ == "__main__":
    main()