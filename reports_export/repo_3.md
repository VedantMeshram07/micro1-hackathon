# Due-Diligence Report: repo_3

✅ *Self-audit passed: every finding this report gathered is cited below — nothing was dropped.*

## Verdict: 4/10 — Est. 34-62 engineer-hours to acquisition-ready

repo_3 is an academic C++ process scheduling simulator with no build system, no dependency manifest, and no automated tests. Bus-factor risk is present with top contributor share at 100.0% and 243 days since last push. Total remediation cost is estimated at 48 hours (range 34-62h).

---

## 💰 Remediation Cost Estimate

| Item | Hours | Basis |
|---|---|---|
| Stand up a working automated test suite | 8 | Flat estimate — tests did not run successfully during audit |
| Knowledge-transfer risk: safely onboard a new team onto this codebase | 40 | Flat estimate — 100.0% of commits from one contributor, no push in 243 days (bus-factor risk, not a code defect) |

**Total: 48 hours (range: 34-62h)**

> Heuristic estimate based on the stated per-item assumptions above, not a professional engineering quote. Presented as a range (34-62h) to avoid false precision. Does not include general code-quality improvements beyond the specific findings listed.

---

## ⚠️ Risks
- **Bus-factor risk: top contributor holds 100.0% of commits and last push was 243 days ago.** — _Ownership risk: top_contributor_share_pct: 100.0, days_since_last_push: 243, bus_factor_flag: true._
- **No automated build or test support available.** — _Build/test evidence: attempted: false, reason: No deep build/test support for detected language(s)._

## ✅ Strengths
- **No secret findings detected in scanned files.** — _Secret scan: findings: [], files_scanned: 6._
- **README documents educational scope clearly.** — _README states academic and learning project purpose._

## 📄 License
- Project license: **not found**

## 👥 Ownership & Continuity Risk
- 1 contributor(s), top contributor: 100.0% of commits, last push: 243 days ago
  - ⚠️ **Bus-factor risk**: commit history is highly concentrated in one contributor and the repo has gone quiet — factor in onboarding time for a new team.

## ❓ Could Not Verify
- Build/test correctness because language is not supported by pipeline.
- Dependency vulnerabilities because no manifest was found.

---
*Every claim above is backed by evidence in the full JSON report — this is a summary view, not a separate assessment.*