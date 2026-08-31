"""
Generates a polished business-report .md AND .pdf for every agent report
in data/reports/, into reports_export/. Run after eval.run_eval completes.

Usage: python export_reports.py
"""

import glob
import json
import os

from report.generate_report import render_business_report
from report.generate_pdf import render_pdf_report

OUTPUT_DIR = "reports_export"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    agent_reports = glob.glob("data/reports/*__agent.json")

    if not agent_reports:
        print("No agent reports found in data/reports/ — run eval.run_eval first.")
        return

    for path in sorted(agent_reports):
        with open(path, "r", encoding="utf-8") as f:
            report = json.load(f)

        if report.get("score") is None:
            print(f"SKIPPED (no score / still pending): {path}")
            continue

        repo_id = os.path.basename(path).replace("__agent.json", "")

        markdown = render_business_report(report, repo_id)
        md_path = os.path.join(OUTPUT_DIR, f"{repo_id}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"Wrote {md_path}")

        pdf_path = os.path.join(OUTPUT_DIR, f"{repo_id}.pdf")
        render_pdf_report(report, repo_id, pdf_path)
        print(f"Wrote {pdf_path}")

    print(f"\nDone. {len(agent_reports)} report(s) processed into {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
