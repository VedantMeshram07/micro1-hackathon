"""
Saves structured report dicts to disk and renders them as readable markdown
for the hosted browser / README / video.
"""

import json
import os


def save_report(report: dict, repo_id: str, method: str, output_dir: str = "data/reports") -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{repo_id}__{method}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return path


def load_report(repo_id: str, method: str, output_dir: str = "data/reports") -> dict | None:
    path = os.path.join(output_dir, f"{repo_id}__{method}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def render_markdown(report: dict) -> str:
    if report.get("method") == "baseline":
        return (
            f"### Baseline rating: {report.get('score', '—')}/10\n\n"
            f"{report.get('reasoning', '(no reasoning returned)')}\n"
        )

    lines = [f"### Agent report: {report.get('score', '—')}/10", ""]
    lines.append(report.get("summary", ""))
    lines.append("")

    if report.get("strengths"):
        lines.append("**Strengths**")
        for s in report["strengths"]:
            lines.append(f"- {s.get('point', '')} _— {s.get('evidence', '')}_")
        lines.append("")

    if report.get("risks"):
        lines.append("**Risks**")
        for r in report["risks"]:
            lines.append(f"- {r.get('point', '')} _— {r.get('evidence', '')}_")
        lines.append("")

    if report.get("unverifiable"):
        lines.append("**Could not verify**")
        for u in report["unverifiable"]:
            lines.append(f"- {u}")
        lines.append("")

    return "\n".join(lines)
