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


def render_business_report(report: dict, repo_name: str | None = None) -> str:
    """The business-framed one-pager: leads with the remediation-cost
    estimate as the headline number, not just a score — this is the view
    meant for the tool's actual intended user (a buyer doing due diligence),
    versus render_markdown()'s more technical evidence-dump style."""
    name = repo_name or report.get("repo", "Repository")
    score = report.get("score", "—")
    remediation = report.get("remediation_estimate", {})
    total_hours = remediation.get("total_hours_estimate")
    low = remediation.get("range_low")
    high = remediation.get("range_high")

    lines = [f"# Due-Diligence Report: {name}", ""]

    if total_hours is not None:
        lines.append(f"## Verdict: {score}/10 — Est. {low}-{high} engineer-hours to acquisition-ready")
    else:
        lines.append(f"## Verdict: {score}/10")
    lines.append("")
    lines.append(report.get("summary", ""))
    lines.append("")
    lines.append("---")
    lines.append("")

    if remediation.get("line_items"):
        lines.append("## 💰 Remediation Cost Estimate")
        lines.append("")
        lines.append("| Item | Hours | Basis |")
        lines.append("|---|---|---|")
        for item in remediation["line_items"]:
            lines.append(f"| {item['item']} | {item['hours']} | {item['basis']} |")
        lines.append("")
        lines.append(f"**Total: {total_hours} hours (range: {low}-{high}h)**")
        lines.append("")
        lines.append(f"> {remediation.get('disclosure', '')}")
        lines.append("")
        lines.append("---")
        lines.append("")

    if report.get("risks"):
        lines.append("## ⚠️ Risks")
        for r in report["risks"]:
            lines.append(f"- **{r.get('point', '')}** — _{r.get('evidence', '')}_")
        lines.append("")

    if report.get("strengths"):
        lines.append("## ✅ Strengths")
        for s in report["strengths"]:
            lines.append(f"- **{s.get('point', '')}** — _{s.get('evidence', '')}_")
        lines.append("")

    license_check = report.get("raw_evidence", {}).get("license_check", {})
    if license_check:
        proj_lic = license_check.get("project_license", {})
        dep_lic = license_check.get("dependency_licenses", {})
        lines.append("## 📄 License")
        lines.append(f"- Project license: **{proj_lic.get('license') or 'not found'}**"
                      + (f" (`{proj_lic['file']}`)" if proj_lic.get("file") else ""))
        if dep_lic.get("attempted"):
            lines.append(f"- Dependencies checked: {dep_lic.get('checked', 0)}, "
                          f"conflicts: {len(dep_lic.get('conflicts', []))}, "
                          f"unknown license: {dep_lic.get('unknown_count', 0)}")
            for c in dep_lic.get("conflicts", []):
                lines.append(f"  - ⚠️ **{c['package']}** — {c['license']} (copyleft — legal review recommended)")
        lines.append("")

    if report.get("unverifiable"):
        lines.append("## ❓ Could Not Verify")
        for u in report["unverifiable"]:
            lines.append(f"- {u}")
        lines.append("")

    lines.append("---")
    lines.append("*Every claim above is backed by evidence in the full JSON report — "
                  "this is a summary view, not a separate assessment.*")

    return "\n".join(lines)
