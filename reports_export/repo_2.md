# Due-Diligence Report: repo_2

✅ *Self-audit passed: every finding this report gathered is cited below — nothing was dropped.*

## Verdict: 3/10 — Est. 6-12 engineer-hours to acquisition-ready

repo_2 installs successfully but automated tests fail during collection, leaving core correctness unverified. Secret scan identified non-test credential findings in hl7_server_Production_DB.py. Total remediation cost is estimated at 9 hours (range 6-12h).

---

## 💰 Remediation Cost Estimate

| Item | Hours | Basis |
|---|---|---|
| Rotate 1 hardcoded credential(s) found in production code | 1 | 1h per finding (rotate + remove from code + wire to secrets manager) |
| Stand up a working automated test suite | 8 | Flat estimate — tests did not run successfully during audit |

**Total: 9 hours (range: 6-12h)**

> Heuristic estimate based on the stated per-item assumptions above, not a professional engineering quote. Presented as a range (6-12h) to avoid false precision. Does not include general code-quality improvements beyond the specific findings listed.

---

## ⚠️ Risks
- **Non-test secret finding in hl7_server_Production_DB.py.** — _Secret scan: file hl7_server_Production_DB.py, line 134, type High-entropy string (possible secret), in_test_dir: false._
- **Automated tests failed during collection.** — _Build/test evidence: ERROR hl7_client_2_one_test.py - ConnectionRefusedError._

## ✅ Strengths
- **All 3 declared dependencies are pinned.** — _Dependency evidence: unpinned_count: 0, total_declared: 3, manifest_type: requirements.txt._
- **No vulnerable dependencies detected.** — _Vulnerability scan: packages_checked: 3, vulnerable_count: 0._

## 📄 License
- Project license: **not found**
- Dependencies checked: 3, conflicts: 0, unknown license: 1

## 👥 Ownership & Continuity Risk
- 1 contributor(s), top contributor: 100.0% of commits, last push: 52 days ago

## ❓ Could Not Verify
- Project license status because project_license found is false.
- Container setup because has_dockerfile and has_compose are false.

---
*Every claim above is backed by evidence in the full JSON report — this is a summary view, not a separate assessment.*