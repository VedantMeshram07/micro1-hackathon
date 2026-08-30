"""
Checks every file touched tonight for a specific marker string proving the
LATEST version actually landed — a recent file-modified date isn't proof
of correct content, only this is. Run: python verify_files.py
"""

import os

CHECKS = [
    ("agent/audit_repo.py", "max_tokens=3500", "Latest fix: bumped synthesis token limit"),
    ("agent/audit_repo.py", "license_check", "License/remediation evidence wired in"),
    ("agent/audit_repo.py", "HARD REQUIREMENT", "Hard citation requirement present"),
    ("agent/check_license.py", "detect_project_license", "License checker exists"),
    ("agent/check_license.py", "PROJECT_LICENSE_SIGNATURES", "License signature list present"),
    ("agent/remediation_estimate.py", "estimate_remediation_cost", "Remediation estimator exists"),
    ("agent/scan_secrets.py", "KEYWORD_CONTEXT", "Three-layer secret detection (not old pattern-only version)"),
    ("agent/scan_secrets.py", "LOCK_FILE_NAMES", "Lock-file exclusion fix present"),
    ("report/generate_report.py", "render_business_report", "Business report renderer exists"),
    ("llm/client.py", "parse_failures", "complete_json retry-before-advance fix present"),
]

print(f"{'FILE':<35} {'CHECK':<50} RESULT")
print("-" * 100)

all_passed = True
for filepath, marker, description in CHECKS:
    if not os.path.exists(filepath):
        print(f"{filepath:<35} {description:<50} MISSING FILE")
        all_passed = False
        continue
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    if marker in content:
        print(f"{filepath:<35} {description:<50} OK")
    else:
        print(f"{filepath:<35} {description:<50} MISSING MARKER")
        all_passed = False

print("-" * 100)
if all_passed:
    print("ALL CHECKS PASSED — every file has today's actual changes, not stale content.")
else:
    print("SOME CHECKS FAILED — see MISSING lines above. Those specific files need re-replacing.")