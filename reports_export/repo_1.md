# Due-Diligence Report: repo_1

✅ *Self-audit passed: every finding this report gathered is cited below — nothing was dropped.*

## Verdict: 6/10 — Est. 6-10 engineer-hours to acquisition-ready

repo_1 (JavaScript Snake) installs cleanly and the game runs, but the npm test script exits with an error so no automated quality verification was completed. The codebase contains 0 secrets, 0 vulnerable dependencies, and MIT project license. Total remediation cost is estimated at 8 hours (range 6-10h).

---

## 💰 Remediation Cost Estimate

| Item | Hours | Basis |
|---|---|---|
| Stand up a working automated test suite | 8 | Flat estimate — tests did not run successfully during audit |

**Total: 8 hours (range: 6-10h)**

> Heuristic estimate based on the stated per-item assumptions above, not a professional engineering quote. Presented as a range (6-10h) to avoid false precision. Does not include general code-quality improvements beyond the specific findings listed.

---

## ⚠️ Risks
- **No automated test suite — npm test script exits with error.** — _Build/test evidence: tests_ran: false, test_summary: Error: no test specified._
- **Both declared dependencies are unpinned.** — _Dependency evidence: unpinned_count: 2, total_declared: 2._

## ✅ Strengths
- **Clean security scan with 0 secrets and 0 vulnerable packages.** — _Secret scan: findings: []. Vulnerability scan: vulnerable: [], vulnerable_count: 0._
- **MIT license present with no dependency license conflicts.** — _License check: project_license: {found: true, license: MIT}, dependency_licenses: conflicts: []._

## 📄 License
- Project license: **MIT** (`LICENSE`)
- Dependencies checked: 2, conflicts: 0, unknown license: 0

## 👥 Ownership & Continuity Risk
- 28 contributor(s), top contributor: 51.2% of commits, last push: 36 days ago

## ❓ Could Not Verify
- No Docker or Compose file present — containerized deployment cannot be assessed.

---
*Every claim above is backed by evidence in the full JSON report — this is a summary view, not a separate assessment.*