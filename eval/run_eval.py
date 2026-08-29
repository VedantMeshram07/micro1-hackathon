"""
Runs baseline and agent over the fixed, pinned repo set and reports how well
each one's scores correlate with your own ground-truth ranking. This is what
produces the comparison table for the README / submission.

Usage:
    python -m eval.run_eval
"""

import os

import yaml
from dotenv import load_dotenv
from scipy.stats import spearmanr

from agent.audit_repo import audit_repo
from agent.trajectory_logger import TrajectoryLogger
from baseline.rate_repo import baseline_rate
from ingest.ingest import ingest
from llm.client import LLMClient
from report.generate_report import load_report, save_report

load_dotenv()


def main():
    with open("repos_manifest.yaml") as fh:
        manifest = yaml.safe_load(fh)["repos"]
    with open("eval/ground_truth.yaml") as fh:
        ground_truth = yaml.safe_load(fh)["rankings"]

    missing_gt = [r["id"] for r in manifest if ground_truth.get(r["id"]) is None]
    if missing_gt:
        print(f"⚠ Ground truth ranking missing for: {missing_gt}")
        print("  Fill in eval/ground_truth.yaml with your own blind ranking before running eval.")
        return

    unfilled = [r["id"] for r in manifest if not r.get("github_url")]
    if unfilled:
        print(f"⚠ repos_manifest.yaml has empty github_url for: {unfilled}")
        return

    client = LLMClient()

    baseline_scores, agent_scores, gt_ranks = [], [], []

    for r in manifest:
        repo_id = r["id"]
        print(f"\n=== {repo_id} ({r['github_url']}) ===")

        cached_baseline = load_report(repo_id, "baseline")
        cached_agent = load_report(repo_id, "agent")

        if cached_baseline and cached_agent:
            print("  Using cached reports (delete data/reports/*.json to force a re-run)")
            baseline_report, agent_report = cached_baseline, cached_agent
        else:
            ingest_result = ingest(r["github_url"], pinned_commit=r.get("pinned_commit") or None)
            logger = TrajectoryLogger(run_id=repo_id)

            print("  Running baseline...")
            baseline_report = baseline_rate(repo_id, ingest_result, client)
            save_report(baseline_report, repo_id, "baseline")

            print("  Running agent audit (this is the slow one)...")
            agent_report = audit_repo(repo_id, ingest_result, client, logger,
                                       github_url=r["github_url"],
                                       github_token=os.environ.get("GITHUB_TOKEN"))
            save_report(agent_report, repo_id, "agent")

        b_score = baseline_report.get("score")
        a_score = agent_report.get("score")
        print(f"  Baseline score: {b_score}   Agent score: {a_score}   Ground truth rank: {ground_truth[repo_id]}")

        if b_score is not None:
            baseline_scores.append(b_score)
            agent_scores.append(a_score if a_score is not None else 0)
            gt_ranks.append(ground_truth[repo_id])

    if len(gt_ranks) < 3:
        print("\nNot enough scored repos yet to compute a meaningful correlation.")
        return

    # Ground truth is a rank (1 = best); scores are 1-10 (10 = best) — flip
    # sign on correlation interpretation isn't needed, spearmanr handles
    # monotonic relationships regardless of direction, but we negate ground
    # truth so "higher is better" lines up on both sides for readability.
    gt_as_quality = [-r for r in gt_ranks]

    baseline_corr, _ = spearmanr(baseline_scores, gt_as_quality)
    agent_corr, _ = spearmanr(agent_scores, gt_as_quality)

    print("\n=== Results ===")
    print(f"Baseline correlation with your ranking: {baseline_corr:.3f}")
    print(f"Agent correlation with your ranking:    {agent_corr:.3f}")
    print(f"Improvement: {agent_corr - baseline_corr:+.3f}")


if __name__ == "__main__":
    main()
